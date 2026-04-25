use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    ensure_debug_sidecar_placeholder();
    tauri_build::build()
}

fn ensure_debug_sidecar_placeholder() {
    if env::var("PROFILE").as_deref() != Ok("debug") {
        return;
    }

    let target = match env::var("TARGET") {
        Ok(value) => value,
        Err(_) => return,
    };
    let sidecar_path = PathBuf::from("binaries").join(format!("music-dl-server-{target}"));
    if sidecar_path.exists() {
        return;
    }

    if let Some(parent) = sidecar_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(&sidecar_path, "#!/usr/bin/env sh\nexit 0\n");

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(metadata) = fs::metadata(&sidecar_path) {
            let mut permissions = metadata.permissions();
            permissions.set_mode(0o755);
            let _ = fs::set_permissions(&sidecar_path, permissions);
        }
    }
}
