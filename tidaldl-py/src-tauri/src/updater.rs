use std::sync::Mutex;
use std::time::Duration;

use log::info;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::Sidecar;

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UpdatePhase {
    Idle,
    Checking,
    UpToDate,
    UpdateAvailable,
    Downloading,
    ReadyToInstall,
    Installing,
    Error,
    UnsupportedInstallContext,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdaterState {
    pub phase: UpdatePhase,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl Default for UpdaterState {
    fn default() -> Self {
        Self {
            phase: UpdatePhase::Idle,
            version: None,
            error: None,
        }
    }
}

/// Managed wrapper for shared updater state.
pub struct UpdaterSharedState(pub Mutex<UpdaterState>);

/// Managed wrapper for a staged update ready to install (update handle + downloaded bytes).
pub struct StagedUpdate(pub Mutex<Option<(tauri_plugin_updater::Update, Vec<u8>)>>);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn set_state(app: &AppHandle, shared: &UpdaterSharedState, new: UpdaterState) {
    info!(
        "updater: {:?} -> {:?}",
        shared.0.lock().unwrap().phase,
        new.phase
    );
    *shared.0.lock().unwrap() = new.clone();
    let _ = app.emit("updater-state-changed", new);
}

/// On macOS, only allow updates when the app bundle lives in /Applications or
/// ~/Applications.  Reject DMG mounts (/Volumes/) and translocated paths.
/// On non-macOS platforms this always returns Ok(()).
fn check_install_context() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let exe = std::env::current_exe().map_err(|e| format!("cannot resolve exe path: {e}"))?;
        let canonical = exe.canonicalize().unwrap_or_else(|_| exe.clone());
        let path_str = canonical.to_string_lossy();

        // Reject DMG mounts
        if path_str.starts_with("/Volumes/") {
            return Err(
                "Running from a DMG mount. Please move the app to /Applications first.".into(),
            );
        }

        // Detect macOS app translocation (random path under /private/var/folders)
        if path_str.contains("/AppTranslocation/") {
            return Err(
                "App is translocated by macOS Gatekeeper. Move it to /Applications and relaunch."
                    .into(),
            );
        }

        // Must be under /Applications or ~/Applications
        let in_applications =
            path_str.starts_with("/Applications/") || path_str.contains("/Applications/");

        if !in_applications {
            return Err(format!(
                "App is not in /Applications (path: {}). Move it there to enable updates.",
                path_str
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_updater_state(
    state: State<'_, UpdaterSharedState>,
) -> Result<UpdaterState, String> {
    Ok(state.0.lock().unwrap().clone())
}

#[tauri::command]
pub async fn check_for_updates(
    app: AppHandle,
    shared: State<'_, UpdaterSharedState>,
    staged: State<'_, StagedUpdate>,
) -> Result<UpdaterState, String> {
    do_check(app, &shared, &staged).await;
    Ok(shared.0.lock().unwrap().clone())
}

#[tauri::command]
pub async fn install_update(
    app: AppHandle,
    shared: State<'_, UpdaterSharedState>,
    staged: State<'_, StagedUpdate>,
    sidecar: State<'_, Sidecar>,
) -> Result<(), String> {
    // Must have a staged update
    let (update, bytes) = staged
        .0
        .lock()
        .unwrap()
        .take()
        .ok_or_else(|| "No staged update available".to_string())?;

    // Kill sidecar first
    info!("updater: shutting down sidecar before install");
    {
        let mut guard = sidecar.0.lock().unwrap();
        let child = if guard.owns_child {
            guard.base_url = None;
            guard.health_url = None;
            guard.owns_child = false;
            guard.child.take()
        } else {
            None
        };

        if let Some(child) = child {
            let _ = child.kill();
        }
    }
    // Give sidecar time to die (brief blocking sleep is acceptable here)
    std::thread::sleep(Duration::from_secs(2));

    set_state(
        &app,
        &shared,
        UpdaterState {
            phase: UpdatePhase::Installing,
            version: None,
            error: None,
        },
    );

    // Install and restart
    if let Err(e) = update.install(bytes) {
        set_state(
            &app,
            &shared,
            UpdaterState {
                phase: UpdatePhase::Error,
                version: None,
                error: Some(format!("Install failed: {e}")),
            },
        );
        return Err(format!("Install failed: {e}"));
    }

    // Restart the app via the process plugin
    info!("updater: install complete, restarting app");
    app.restart();
}

// ---------------------------------------------------------------------------
// Core check + download logic (used by command and by setup)
// ---------------------------------------------------------------------------

async fn do_check(app: AppHandle, shared: &UpdaterSharedState, staged: &StagedUpdate) {
    use tauri_plugin_updater::UpdaterExt;

    // Install context gate
    if let Err(msg) = check_install_context() {
        info!("updater: unsupported install context — {msg}");
        set_state(
            &app,
            shared,
            UpdaterState {
                phase: UpdatePhase::UnsupportedInstallContext,
                version: None,
                error: Some(msg),
            },
        );
        return;
    }

    set_state(
        &app,
        shared,
        UpdaterState {
            phase: UpdatePhase::Checking,
            version: None,
            error: None,
        },
    );

    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            set_state(
                &app,
                shared,
                UpdaterState {
                    phase: UpdatePhase::Error,
                    version: None,
                    error: Some(format!("Updater init error: {e}")),
                },
            );
            return;
        }
    };

    match updater.check().await {
        Ok(Some(update)) => {
            let version = update.version.clone();
            info!("updater: update available — v{version}");
            set_state(
                &app,
                shared,
                UpdaterState {
                    phase: UpdatePhase::UpdateAvailable,
                    version: Some(version.clone()),
                    error: None,
                },
            );

            // Immediately download so it's staged
            set_state(
                &app,
                shared,
                UpdaterState {
                    phase: UpdatePhase::Downloading,
                    version: Some(version.clone()),
                    error: None,
                },
            );

            let mut bytes_so_far: usize = 0;
            match update
                .download(
                    |chunk_len, _content_len| {
                        bytes_so_far += chunk_len;
                        if bytes_so_far % (512 * 1024) < chunk_len {
                            info!("updater: downloaded {} KB", bytes_so_far / 1024);
                        }
                    },
                    || {
                        info!("updater: download finished");
                    },
                )
                .await
            {
                Ok(bytes) => {
                    info!("updater: download complete, staged for install");
                    *staged.0.lock().unwrap() = Some((update, bytes));
                    set_state(
                        &app,
                        shared,
                        UpdaterState {
                            phase: UpdatePhase::ReadyToInstall,
                            version: Some(version),
                            error: None,
                        },
                    );
                }
                Err(e) => {
                    set_state(
                        &app,
                        shared,
                        UpdaterState {
                            phase: UpdatePhase::Error,
                            version: Some(version),
                            error: Some(format!("Download failed: {e}")),
                        },
                    );
                }
            }
        }
        Ok(None) => {
            info!("updater: app is up to date");
            set_state(
                &app,
                shared,
                UpdaterState {
                    phase: UpdatePhase::UpToDate,
                    version: None,
                    error: None,
                },
            );
        }
        Err(e) => {
            set_state(
                &app,
                shared,
                UpdaterState {
                    phase: UpdatePhase::Error,
                    version: None,
                    error: Some(format!("Check failed: {e}")),
                },
            );
        }
    }
}

/// Spawn background update check (called from setup). Only runs in release builds.
pub fn spawn_update_check(app: &AppHandle) {
    if cfg!(debug_assertions) {
        info!("updater: skipping update check in debug build");
        return;
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        // Small delay so the UI can settle
        std::thread::sleep(Duration::from_secs(3));

        let shared = handle.state::<UpdaterSharedState>();
        let staged = handle.state::<StagedUpdate>();
        do_check(handle.clone(), &shared, &staged).await;
    });
}
