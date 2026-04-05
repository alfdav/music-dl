use std::net::TcpStream;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

const SIDECAR_URL: &str = "http://localhost:8765";
const POLL_INTERVAL: Duration = Duration::from_millis(200);
const POLL_TIMEOUT: Duration = Duration::from_secs(30);

// Wrapper so we can manage CommandChild in Tauri state (needs Send + Sync)
struct Sidecar(Mutex<Option<CommandChild>>);

/// Check if the sidecar is accepting TCP connections on port 8765.
fn sidecar_is_ready() -> bool {
    TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        Duration::from_millis(100),
    )
    .is_ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Spawn the Python FastAPI sidecar
            let sidecar_cmd = app.shell().sidecar("music-dl-server").unwrap();
            let (_rx, child) = sidecar_cmd.spawn().expect("failed to spawn sidecar");

            // Store child in managed state so it lives for the app lifetime
            app.manage(Sidecar(Mutex::new(Some(child))));

            // Poll for sidecar readiness in a background thread, then navigate
            let handle = app.handle().clone();
            thread::spawn(move || {
                let start = Instant::now();
                while start.elapsed() < POLL_TIMEOUT {
                    if sidecar_is_ready() {
                        if let Some(window) = handle.get_webview_window("main") {
                            // Navigate the webview to the sidecar-served frontend.
                            // This is a hardcoded URL, not user input — safe to eval.
                            let nav = format!("window.location.replace('{SIDECAR_URL}')");
                            let _ = window.eval(&nav);
                        }
                        return;
                    }
                    thread::sleep(POLL_INTERVAL);
                }

                // Timeout — show error on the loading page
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.eval(concat!(
                        "document.getElementById('spinner').style.display='none';",
                        "document.getElementById('error').style.display='block';",
                        "document.getElementById('error').textContent=",
                        "'Server failed to start. Please restart the app.';",
                    ));
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill sidecar when window is destroyed
                if let Some(state) = window.try_state::<Sidecar>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
