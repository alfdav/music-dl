use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

fn main() {
    ensure_debug_sidecar_placeholder();
    tauri_build::build()
}

fn ensure_debug_sidecar_placeholder() {
    if env::var("PROFILE").as_deref() != Ok("debug") {
        return;
    }

    let Some(target_triple) = env::var_os("TARGET") else {
        return;
    };

    let path = PathBuf::from("binaries").join(format!(
        "music-dl-server-{}",
        target_triple.to_string_lossy()
    ));
    if path.exists() {
        return;
    }

    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    #[cfg(windows)]
    let body = "@echo off\r\nexit /b 0\r\n";
    #[cfg(not(windows))]
    let body = "#!/bin/sh\nexit 0\n";

    if fs::write(&path, body).is_ok() {
        #[cfg(unix)]
        {
            if let Ok(mut permissions) = fs::metadata(&path).map(|meta| meta.permissions()) {
                permissions.set_mode(0o755);
                let _ = fs::set_permissions(&path, permissions);
            }
        }
    }
}
