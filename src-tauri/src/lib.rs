use std::sync::OnceLock;

use tauri::Manager;

static API_TOKEN: OnceLock<String> = OnceLock::new();

struct InstanceLock(std::path::PathBuf);

impl Drop for InstanceLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[cfg(unix)]
fn owner_process_alive(pid: u32) -> bool {
    std::process::Command::new("kill")
        .args(["-0", &pid.to_string()])
        .status()
        .map(|status| status.success())
        .unwrap_or(true)
}

#[cfg(windows)]
fn owner_process_alive(pid: u32) -> bool {
    // `tasklist` is available on supported Windows versions and avoids a
    // platform-specific crate just for stale-lock recovery.
    std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/NH"])
        .output()
        .map(|output| {
            String::from_utf8_lossy(&output.stdout).contains(&pid.to_string())
        })
        .unwrap_or(true)
}

#[cfg(not(any(unix, windows)))]
fn owner_process_alive(_pid: u32) -> bool {
    true
}

fn acquire_instance_lock_at(path: std::path::PathBuf) -> Option<InstanceLock> {
    for attempt in 0..2 {
        match std::fs::OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(file) => {
                use std::io::Write;
                let mut file = file;
                let _ = writeln!(file, "{}", std::process::id());
                return Some(InstanceLock(path));
            }
            Err(_) if attempt == 0 => {
                // A force-quit can leave the marker behind. Reclaim it only
                // when the recorded owner process no longer exists; a live
                // owner still protects the single-instance invariant.
                let owner = std::fs::read_to_string(&path).ok()
                    .and_then(|value| value.trim().parse::<u32>().ok());
                let alive = owner.map(owner_process_alive).unwrap_or(true);
                if !alive {
                    let _ = std::fs::remove_file(&path);
                    continue;
                }
                return None;
            }
            Err(_) => return None,
        }
    }
    None
}

fn acquire_instance_lock() -> Option<InstanceLock> {
    acquire_instance_lock_at(std::env::temp_dir().join("story-guard-single-instance.lock"))
}

#[tauri::command]
fn app_data_dir(app: tauri::AppHandle) -> Result<String, String> {
    app.path()
        .app_data_dir()
        .map(|path| path.to_string_lossy().to_string())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn api_token(app: tauri::AppHandle) -> Result<String, String> {
    if let Some(token) = API_TOKEN.get() {
        return Ok(token.clone());
    }

    let token = load_or_create_api_token(&app)?;
    let _ = API_TOKEN.set(token);
    API_TOKEN
        .get()
        .cloned()
        .ok_or_else(|| "failed to initialize api token".to_string())
}

#[tauri::command]
fn app_process_id() -> u32 {
    std::process::id()
}

fn load_or_create_api_token(app: &tauri::AppHandle) -> Result<String, String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data_dir).map_err(|error| error.to_string())?;
    let token_path = app_data_dir.join("api_token");

    if let Ok(token) = std::fs::read_to_string(&token_path) {
        let trimmed = token.trim();
        if !trimmed.is_empty() {
            restrict_token_file_permissions(&token_path);
            return Ok(trimmed.to_string());
        }
    }

    let token = generate_api_token()?;
    std::fs::write(&token_path, &token).map_err(|error| error.to_string())?;
    restrict_token_file_permissions(&token_path);
    Ok(token)
}

#[cfg(unix)]
fn restrict_token_file_permissions(path: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;

    if let Ok(metadata) = std::fs::metadata(path) {
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o600);
        let _ = std::fs::set_permissions(path, permissions);
    }
}

#[cfg(not(unix))]
fn restrict_token_file_permissions(_path: &std::path::Path) {}

fn generate_api_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| error.to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

pub fn run() {
    // Finder/Dock can launch the bundle more than once. Keep one process and
    // let the second invocation exit before creating another window.
    let Some(_instance_lock) = acquire_instance_lock() else {
        return;
    };
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![app_data_dir, api_token, app_process_id])
        .run(tauri::generate_context!())
        .expect("error while running Story Guard");
}

#[cfg(test)]
mod tests {
    use super::acquire_instance_lock_at;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_lock_path() -> std::path::PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock before epoch")
            .as_nanos();
        std::env::temp_dir().join(format!("story-guard-test-{nonce}.lock"))
    }

    #[test]
    fn prevents_second_instance_until_owner_releases_lock() {
        let path = test_lock_path();
        let first = acquire_instance_lock_at(path.clone()).expect("first process should lock");
        assert!(acquire_instance_lock_at(path.clone()).is_none());
        drop(first);
        assert!(acquire_instance_lock_at(path.clone()).is_some());
        let _ = std::fs::remove_file(path);
    }
}
