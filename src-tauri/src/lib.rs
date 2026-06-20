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
fn api_token() -> Result<String, String> {
    if let Some(token) = API_TOKEN.get() {
        return Ok(token.clone());
    }

    let token = generate_api_token()?;
    let _ = API_TOKEN.set(token);
    API_TOKEN
        .get()
        .cloned()
        .ok_or_else(|| "failed to initialize api token".to_string())
}

fn generate_api_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| error.to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![app_data_dir, api_token])
        .run(tauri::generate_context!())
        .expect("error while running Story Guard");
}
