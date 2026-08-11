// RX3000 desktop shell.
//
// The reason this exists rather than a browser bookmark: a pharmacy till is not
// a web page. It talks to a receipt printer, a cash drawer and a fiscal device,
// it must survive the internet being down, and it should open when the machine
// does without anyone typing an address. The device agent already owns the
// hardware; this shell owns the window and, critically, *which server the till
// talks to*.
//
// That last point is the whole design. Each pharmacy runs its own backend on
// the premises. A build with a hard-coded URL would be a build per customer,
// which is not a product. So the server address is configuration, resolved in
// this order:
//
//   1. RX3000_SERVER in the environment  (an operator overriding for one run)
//   2. server.txt beside the executable  (what the installer or IT writes)
//   3. http://localhost:8177             (the single-machine pharmacy)
//
// Wrong-server is the failure that wastes a support call, so the resolved
// address is written to the log at startup and shown in the window title.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{env, fs, path::PathBuf};

const DEFAULT_SERVER: &str = "http://localhost:8177";

/// Where this till's backend lives.
fn resolve_server() -> String {
    if let Ok(from_env) = env::var("RX3000_SERVER") {
        let trimmed = from_env.trim().to_string();
        if !trimmed.is_empty() {
            return trimmed;
        }
    }
    if let Some(path) = server_file() {
        if let Ok(contents) = fs::read_to_string(&path) {
            // First non-empty, non-comment line. A config file people edit by
            // hand acquires comments, and a comment read as a URL is a support
            // call that starts "it says it cannot connect".
            for line in contents.lines() {
                let line = line.trim();
                if !line.is_empty() && !line.starts_with('#') {
                    return line.trim_end_matches('/').to_string();
                }
            }
        }
    }
    DEFAULT_SERVER.to_string()
}

fn server_file() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    Some(exe.parent()?.join("server.txt"))
}

/// Exposed to the front end so it knows where to send its requests, and so the
/// System screen can show the operator which server this till is bound to.
#[tauri::command]
fn rx3000_server() -> String {
    resolve_server()
}

fn server_for_script() -> String {
    resolve_server()
}

fn main() {
    let server = resolve_server();
    println!("RX3000 desktop starting against {server}");

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // Injected before any page script runs, so the API layer knows where to
        // send its first request rather than resolving it asynchronously and
        // firing the first few calls at the wrong place.
        .append_invoke_initialization_script(format!(
            "window.__RX3000_SERVER__ = {:?};", server_for_script()
        ))
        .invoke_handler(tauri::generate_handler![rx3000_server])
        .setup(move |app| {
            use tauri::Manager;
            if let Some(window) = app.get_webview_window("main") {
                // The bound server in the title bar. On a four-till counter,
                // "which one is pointed at the wrong box" should be answerable
                // by looking, not by opening a settings screen.
                let _ = window.set_title(&format!("RX3000 Pharmacy Suite — {server}"));
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("RX3000 failed to start");
}
