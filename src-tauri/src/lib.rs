use std::sync::OnceLock;

use tauri::Manager;

static API_TOKEN: OnceLock<String> = OnceLock::new();

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
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![app_data_dir, api_token, app_process_id])
        .run(tauri::generate_context!())
        .expect("error while running Story Guard");
}
