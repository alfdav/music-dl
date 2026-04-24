mod updater;

use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const APP_NAME: &str = "music-dl";
const READY_STATUS: &str = "ready";
const BROWSER_MODE: &str = "browser";
const SIDECAR_MODE: &str = "tauri-sidecar";
const HEALTH_PATH: &str = "/api/server/health";
const POLL_INTERVAL: Duration = Duration::from_millis(200);
const POLL_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Debug, PartialEq, Eq)]
struct HealthEndpoint {
    port: u16,
    path: String,
}

#[derive(Clone, Debug, serde::Deserialize)]
struct DaemonMetadata {
    app: String,
    status: String,
    pid: u32,
    base_url: String,
    health_url: String,
    mode: String,
}

#[derive(Debug, serde::Deserialize)]
struct HealthResponse {
    app: String,
    status: String,
}

#[derive(Default)]
pub(crate) struct SidecarState {
    child: Option<CommandChild>,
    base_url: Option<String>,
    health_url: Option<String>,
    owns_child: bool,
}

// Wrapper so we can manage CommandChild in Tauri state (needs Send + Sync)
pub(crate) struct Sidecar(pub(crate) Mutex<SidecarState>);

fn parse_health_url(url: &str) -> Result<HealthEndpoint, String> {
    let rest = url
        .strip_prefix("http://127.0.0.1:")
        .ok_or_else(|| "health_url must use http://127.0.0.1".to_string())?;
    let (port, path) = rest
        .split_once('/')
        .ok_or_else(|| "health_url must include a path".to_string())?;
    let port = port
        .parse::<u16>()
        .map_err(|_| "health_url must include a valid port".to_string())?;
    let path = format!("/{path}");

    if path != HEALTH_PATH {
        return Err("health_url must point at /api/server/health".to_string());
    }

    Ok(HealthEndpoint { port, path })
}

fn base_url_for(endpoint: &HealthEndpoint) -> String {
    format!("http://127.0.0.1:{}", endpoint.port)
}

fn metadata_base_url(meta: &DaemonMetadata) -> Result<String, String> {
    let endpoint = parse_health_url(&meta.health_url)?;
    let base_url = base_url_for(&endpoint);

    if meta.base_url != base_url {
        return Err("daemon metadata base_url does not match health_url".to_string());
    }

    Ok(base_url)
}

fn reusable_metadata(meta: &DaemonMetadata, health_ready: bool) -> bool {
    meta.app == APP_NAME && meta.status == READY_STATUS && health_ready
}

fn reusable_browser_metadata(meta: &DaemonMetadata, health_ready: bool) -> bool {
    meta.mode == BROWSER_MODE && reusable_metadata(meta, health_ready)
}

fn sidecar_metadata_matches(meta: &DaemonMetadata, pid: u32) -> bool {
    meta.mode == SIDECAR_MODE && meta.pid == pid
}

fn daemon_metadata_path() -> Result<PathBuf, String> {
    if let Ok(config_dir) = std::env::var("MUSIC_DL_CONFIG_DIR") {
        if !config_dir.trim().is_empty() {
            return Ok(PathBuf::from(config_dir).join("daemon.json"));
        }
    }

    let home = std::env::var("HOME").map_err(|_| "HOME is not set".to_string())?;
    Ok(PathBuf::from(home)
        .join(".config")
        .join(APP_NAME)
        .join("daemon.json"))
}

fn read_daemon_metadata() -> Option<DaemonMetadata> {
    let path = daemon_metadata_path().ok()?;
    let body = fs::read_to_string(path).ok()?;
    serde_json::from_str(&body).ok()
}

fn health_url_is_ready(health_url: &str) -> bool {
    parse_health_url(health_url)
        .and_then(|endpoint| read_health(&endpoint))
        .map(|health| health.app == APP_NAME && health.status == READY_STATUS)
        .unwrap_or(false)
}

fn metadata_is_ready(meta: &DaemonMetadata) -> bool {
    metadata_base_url(meta).is_ok()
        && reusable_metadata(meta, health_url_is_ready(&meta.health_url))
}

fn browser_metadata_is_ready(meta: &DaemonMetadata) -> bool {
    metadata_base_url(meta).is_ok()
        && reusable_browser_metadata(meta, health_url_is_ready(&meta.health_url))
}

fn read_health(endpoint: &HealthEndpoint) -> Result<HealthResponse, String> {
    let addr = format!("127.0.0.1:{}", endpoint.port)
        .parse()
        .map_err(|_| "invalid health endpoint".to_string())?;
    let mut stream =
        TcpStream::connect_timeout(&addr, HEALTH_TIMEOUT).map_err(|e| e.to_string())?;
    stream
        .set_read_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|e| e.to_string())?;

    let request = format!(
        "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
        endpoint.path, endpoint.port
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| e.to_string())?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| e.to_string())?;
    let (head, body) = response
        .split_once("\r\n\r\n")
        .ok_or_else(|| "invalid health response".to_string())?;

    if !(head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")) {
        return Err("health endpoint returned a non-200 response".to_string());
    }

    serde_json::from_str(body).map_err(|e| e.to_string())
}

fn wait_for_ready_metadata(expected_pid: Option<u32>) -> Result<DaemonMetadata, String> {
    let start = Instant::now();
    while start.elapsed() < POLL_TIMEOUT {
        if let Some(meta) = read_daemon_metadata() {
            let pid_matches = expected_pid
                .map(|pid| sidecar_metadata_matches(&meta, pid))
                .unwrap_or(true);

            if pid_matches && metadata_is_ready(&meta) {
                return Ok(meta);
            }
        }
        thread::sleep(POLL_INTERVAL);
    }

    Err("Timed out waiting for daemon readiness".to_string())
}

fn state_from_external_metadata(meta: DaemonMetadata) -> Result<SidecarState, String> {
    let base_url = metadata_base_url(&meta)?;
    Ok(SidecarState {
        child: None,
        base_url: Some(base_url),
        health_url: Some(meta.health_url),
        owns_child: false,
    })
}

fn state_from_owned_child(
    child: CommandChild,
    meta: DaemonMetadata,
) -> Result<SidecarState, String> {
    let base_url = metadata_base_url(&meta)?;
    Ok(SidecarState {
        child: Some(child),
        base_url: Some(base_url),
        health_url: Some(meta.health_url),
        owns_child: true,
    })
}

fn spawn_sidecar(app: &tauri::AppHandle) -> Result<CommandChild, String> {
    let sidecar_cmd = app
        .shell()
        .sidecar("music-dl-server")
        .map_err(|e| e.to_string())?;
    let (_rx, child) = sidecar_cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar: {e}"))?;

    Ok(child)
}

fn spawn_and_wait_for_sidecar(app: &tauri::AppHandle) -> Result<SidecarState, String> {
    let child = spawn_sidecar(app)?;
    let pid = child.pid();

    match wait_for_ready_metadata(Some(pid)) {
        Ok(meta) => state_from_owned_child(child, meta),
        Err(err) => {
            let _ = child.kill();
            Err(err)
        }
    }
}

fn sidecar_state_is_ready(state: &SidecarState) -> bool {
    state
        .health_url
        .as_deref()
        .map(health_url_is_ready)
        .unwrap_or(false)
}

fn navigate_to(handle: &tauri::AppHandle, base_url: &str) {
    if let Some(window) = handle.get_webview_window("main") {
        let nav = format!("window.location.replace('{base_url}')");
        let _ = window.eval(&nav);
    }
}

fn show_loading_error(handle: &tauri::AppHandle, message: &str) {
    if let Some(window) = handle.get_webview_window("main") {
        let script = format!(
            "{}{}{}",
            "document.getElementById('spinner').style.display='none';",
            "document.getElementById('error').style.display='block';",
            format!(
                "document.getElementById('error').textContent={};",
                serde_json::to_string(message).unwrap_or_else(|_| {
                    "\"Server failed to start. Please restart the app.\"".to_string()
                })
            )
        );
        let _ = window.eval(&script);
    }
}

fn launch_initial_sidecar(handle: tauri::AppHandle) {
    thread::spawn(move || {
        if let Some(meta) = read_daemon_metadata() {
            if browser_metadata_is_ready(&meta) {
                match state_from_external_metadata(meta) {
                    Ok(state) => {
                        let base_url = state.base_url.clone();
                        if let Some(sidecar) = handle.try_state::<Sidecar>() {
                            *sidecar.0.lock().unwrap() = state;
                        }

                        if let Some(base_url) = base_url {
                            navigate_to(&handle, &base_url);
                        }
                    }
                    Err(err) => show_loading_error(&handle, &err),
                }
                return;
            }
        }

        let child = match spawn_sidecar(&handle) {
            Ok(child) => child,
            Err(err) => {
                show_loading_error(&handle, &err);
                return;
            }
        };
        let pid = child.pid();

        if let Some(sidecar) = handle.try_state::<Sidecar>() {
            let mut guard = sidecar.0.lock().unwrap();
            if guard.child.is_some() || guard.health_url.is_some() {
                let _ = child.kill();
                return;
            }

            *guard = SidecarState {
                child: Some(child),
                base_url: None,
                health_url: None,
                owns_child: true,
            };
        } else {
            let _ = child.kill();
            return;
        }

        match wait_for_ready_metadata(Some(pid)) {
            Ok(meta) => {
                let base_url = match metadata_base_url(&meta) {
                    Ok(base_url) => base_url,
                    Err(err) => {
                        show_loading_error(&handle, &err);
                        return;
                    }
                };

                let mut should_navigate = false;
                if let Some(sidecar) = handle.try_state::<Sidecar>() {
                    let mut guard = sidecar.0.lock().unwrap();
                    let current_pid = guard.child.as_ref().map(|child| child.pid());
                    if guard.owns_child && current_pid == Some(pid) {
                        guard.base_url = Some(base_url.clone());
                        guard.health_url = Some(meta.health_url);
                        should_navigate = true;
                    }
                }

                if should_navigate {
                    navigate_to(&handle, &base_url);
                }
            }
            Err(err) => {
                if let Some(sidecar) = handle.try_state::<Sidecar>() {
                    let mut guard = sidecar.0.lock().unwrap();
                    let current_pid = guard.child.as_ref().map(|child| child.pid());
                    if guard.owns_child && current_pid == Some(pid) {
                        if let Some(child) = guard.child.take() {
                            let _ = child.kill();
                        }
                        guard.base_url = None;
                        guard.health_url = None;
                        guard.owns_child = false;
                    }
                }

                show_loading_error(&handle, &err);
            }
        }
    });
}

// ── Sidecar lifecycle commands ───────────────────────────────────────────────

#[tauri::command]
fn sidecar_status(sidecar: tauri::State<'_, Sidecar>) -> bool {
    let guard = sidecar.0.lock().unwrap();
    sidecar_state_is_ready(&guard)
}

#[tauri::command]
fn stop_sidecar(sidecar: tauri::State<'_, Sidecar>) -> Result<(), String> {
    let mut guard = sidecar.0.lock().unwrap();

    if guard.health_url.is_some() && !guard.owns_child {
        return Err("Daemon is external".into());
    }

    match guard.child.take() {
        Some(child) if guard.owns_child => {
            guard.base_url = None;
            guard.health_url = None;
            guard.owns_child = false;
            child.kill().map_err(|e| e.to_string())
        }
        _ => Err("Sidecar is not running".into()),
    }
}

#[tauri::command]
fn start_sidecar(app: tauri::AppHandle, sidecar: tauri::State<'_, Sidecar>) -> Result<(), String> {
    let child = {
        let mut guard = sidecar.0.lock().unwrap();
        if sidecar_state_is_ready(&guard) {
            return Err("Daemon is already running".into());
        }

        let child = if guard.owns_child {
            guard.child.take()
        } else {
            None
        };
        guard.base_url = None;
        guard.health_url = None;
        guard.owns_child = false;
        child
    };

    if let Some(child) = child {
        let _ = child.kill();
        thread::sleep(Duration::from_millis(500));
    }

    let state = spawn_and_wait_for_sidecar(&app)?;
    let mut guard = sidecar.0.lock().unwrap();
    *guard = state;

    Ok(())
}

#[tauri::command]
fn restart_sidecar(
    app: tauri::AppHandle,
    sidecar: tauri::State<'_, Sidecar>,
) -> Result<(), String> {
    let child = {
        let mut guard = sidecar.0.lock().unwrap();
        if guard.health_url.is_some() && !guard.owns_child {
            return Err("Daemon is external".into());
        }

        let child = guard.child.take();
        guard.base_url = None;
        guard.health_url = None;
        guard.owns_child = false;
        child
    };

    if let Some(child) = child {
        let _ = child.kill();
    }

    // Brief pause so the port is freed before we respawn
    thread::sleep(Duration::from_millis(500));

    let state = spawn_and_wait_for_sidecar(&app)?;
    let mut guard = sidecar.0.lock().unwrap();
    *guard = state;

    Ok(())
}

// ── App entry ────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            updater::get_updater_state,
            updater::check_for_updates,
            updater::install_update,
            sidecar_status,
            stop_sidecar,
            start_sidecar,
            restart_sidecar,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Manage updater shared state
            app.manage(updater::UpdaterSharedState(Mutex::new(
                updater::UpdaterState::default(),
            )));
            app.manage(updater::StagedUpdate(Mutex::new(None)));

            app.manage(Sidecar(Mutex::new(SidecarState::default())));
            launch_initial_sidecar(app.handle().clone());

            // Spawn background update check (non-blocking, release only)
            updater::spawn_update_check(app.handle());

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill sidecar when window is destroyed
                if let Some(state) = window.try_state::<Sidecar>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if guard.owns_child {
                            guard.base_url = None;
                            guard.health_url = None;
                            guard.owns_child = false;
                        }

                        if let Some(child) = guard.child.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_health_url_extracts_dynamic_port() {
        let endpoint = parse_health_url("http://127.0.0.1:8766/api/server/health").unwrap();

        assert_eq!(endpoint.port, 8766);
        assert_eq!(endpoint.path, "/api/server/health");
    }

    #[test]
    fn parse_health_url_rejects_unsupported_hosts() {
        assert!(parse_health_url("http://localhost:8766/api/server/health").is_err());
        assert!(parse_health_url("https://127.0.0.1:8766/api/server/health").is_err());
        assert!(parse_health_url("http://127.0.0.1:8766/").is_err());
    }

    #[test]
    fn reusable_metadata_requires_music_dl_ready_health() {
        let meta = DaemonMetadata {
            app: APP_NAME.to_string(),
            status: READY_STATUS.to_string(),
            pid: 123,
            base_url: "http://127.0.0.1:8766".to_string(),
            health_url: "http://127.0.0.1:8766/api/server/health".to_string(),
            mode: "browser".to_string(),
        };

        assert!(reusable_metadata(&meta, true));
        assert!(!reusable_metadata(&meta, false));
    }

    #[test]
    fn reusable_browser_metadata_rejects_other_sidecars() {
        let meta = DaemonMetadata {
            app: APP_NAME.to_string(),
            status: READY_STATUS.to_string(),
            pid: 123,
            base_url: "http://127.0.0.1:8766".to_string(),
            health_url: "http://127.0.0.1:8766/api/server/health".to_string(),
            mode: SIDECAR_MODE.to_string(),
        };

        assert!(!reusable_browser_metadata(&meta, true));
    }

    #[test]
    fn sidecar_metadata_must_match_spawned_pid() {
        let meta = DaemonMetadata {
            app: APP_NAME.to_string(),
            status: READY_STATUS.to_string(),
            pid: 123,
            base_url: "http://127.0.0.1:8766".to_string(),
            health_url: "http://127.0.0.1:8766/api/server/health".to_string(),
            mode: "tauri-sidecar".to_string(),
        };

        assert!(sidecar_metadata_matches(&meta, 123));
        assert!(!sidecar_metadata_matches(&meta, 456));
    }
}
