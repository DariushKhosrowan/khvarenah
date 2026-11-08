//! Khvarenah GUI (eframe/egui) — designed to be simple.
//!
//! The app is a single friendly window for a normal user. The primary surface
//! is the **Autopilot** panel: a big button starts everything (deploy →
//! find best clean IP → export the config → monitor & auto-swap). The right
//! pane streams live progress. A small "Advanced" section exposes the other
//! views for users who want them.

use crate::store::{self, AutopilotState};
use std::time::Duration;

// ---------------------------------------------------------------------------
// Async bridge (reused from the original scaffold; sends UiEvents to the UI)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum UiEvent {
    Log(String),
    TaskErr { task: String, error: String },
    StoreChanged,
}

pub type EventSender = tokio::sync::mpsc::UnboundedSender<UiEvent>;

pub fn channel() -> (EventSender, tokio::sync::mpsc::UnboundedReceiver<UiEvent>) {
    tokio::sync::mpsc::unbounded_channel()
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

const BG: egui::Color32 = egui::Color32::from_rgb(0x0a, 0x07, 0x05);
const GOLD: egui::Color32 = egui::Color32::from_rgb(0xff, 0xe0, 0x96);
const ACCENT: egui::Color32 = egui::Color32::from_rgb(0xa6, 0x7c, 0x1a);
const GREEN: egui::Color32 = egui::Color32::from_rgb(0x7f, 0xd9, 0x8f);
const RED: egui::Color32 = egui::Color32::from_rgb(0xff, 0x8c, 0x78);

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

pub struct KhvarenahApp {
    events_rx: tokio::sync::mpsc::UnboundedReceiver<UiEvent>,
    spawn_tx: EventSender,
    log_lines: Vec<String>,
    error_banner: Option<String>,
    autopilot: AutopilotState,
    monitor_started: bool,
}

impl KhvarenahApp {
    pub fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let profile = store::active_profile();
        let _ = store::ensure_profile(&profile);
        let (tx, rx) = channel();
        Self {
            events_rx: rx,
            spawn_tx: tx,
            log_lines: Vec::new(),
            error_banner: None,
            autopilot: store::autopilot_state(&profile),
            monitor_started: false,
        }
    }

    fn profile(&self) -> String {
        store::active_profile()
    }

    fn refresh_autopilot(&mut self) {
        self.autopilot = store::autopilot_state(&self.profile());
    }

    fn log(&mut self, line: String) {
        self.log_lines.push(line);
        const CAP: usize = 4000;
        if self.log_lines.len() > CAP {
            let excess = self.log_lines.len() - CAP;
            self.log_lines.drain(0..excess);
        }
    }

    fn apply_event(&mut self, ev: UiEvent) {
        match ev {
            UiEvent::Log(line) => self.log(line),
            UiEvent::TaskErr { task, error } => {
                self.error_banner = Some(format!("[{task}] {error}"));
            }
            UiEvent::StoreChanged => self.refresh_autopilot(),
        }
    }

    /// Build a `CommonArgs` from the profile's saved settings/token.
    fn common_args(&self) -> crate::CommonArgs {
        let profile = self.profile();
        let mut a = crate::CommonArgs::default();
        let settings = store::settings(&profile);
        if let Some(t) = store::get_account_token(&profile, &store::active_account_for(&profile)) {
            a.token = Some(t);
        }
        let acc = store::active_account_for(&profile);
        if !acc.is_empty() {
            a.account = Some(acc);
        }
        if let Some(n) = settings.worker_name.clone() {
            a.name = Some(n);
        }
        if let Some(u) = settings.uuid.clone() {
            a.uuid = Some(u);
        }
        if settings.clean_count > 0 {
            a.count = settings.clean_count;
        }
        if settings.clean_workers > 0 {
            a.workers = settings.clean_workers;
        }
        a
    }

    /// Start autopilot in a background thread (blocking ops, so a plain
    /// thread is the right tool). It runs the first cycle, then monitors.
    fn start_autopilot(&mut self) {
        if self.monitor_started {
            return;
        }
        self.monitor_started = true;
        let args = self.common_args();
        let profile = self.profile();
        let tx = self.spawn_tx.clone();

        std::thread::spawn(move || {
            let _ = tx.send(UiEvent::Log("▶ Starting autopilot…".to_string()));
            let _ = tx.send(UiEvent::Log("  (deploy → find clean IP → export config)".to_string()));
            let mut last = match crate::autopilot::run_once(&profile, &args) {
                Ok(st) => {
                    let _ = tx.send(UiEvent::Log(format!(
                        "✓ Done. Active clean IP: {}",
                        st.current_endpoint
                    )));
                    let _ = tx.send(UiEvent::StoreChanged);
                    st
                }
                Err(e) => {
                    let _ = tx.send(UiEvent::TaskErr {
                        task: "autopilot".to_string(),
                        error: e.to_string(),
                    });
                    return;
                }
            };

            // Monitor loop.
            loop {
                let interval_secs = (last.interval_minutes.max(1) as u64).saturating_mul(60);
                // Sleep in bounded chunks so stop/status updates feel responsive.
                let chunk = 5u64;
                let mut slept = 0u64;
                while slept < interval_secs {
                    std::thread::sleep(Duration::from_secs(chunk));
                    slept += chunk;
                }
                match crate::autopilot::monitor_tick(&profile, &args) {
                    Ok(next) => {
                        if next.current_endpoint != last.current_endpoint && !next.current_endpoint.is_empty() {
                            let _ = tx.send(UiEvent::Log(format!(
                                "🔄 Swapped to fresh clean IP: {}",
                                next.current_endpoint
                            )));
                        } else if !next.current_endpoint.is_empty() {
                            let _ = tx.send(UiEvent::Log(format!(
                                "✓ {} — healthy.",
                                next.current_endpoint
                            )));
                        }
                        let _ = tx.send(UiEvent::StoreChanged);
                        last = next;
                    }
                    Err(e) => {
                        let _ = tx.send(UiEvent::TaskErr {
                            task: "monitor".to_string(),
                            error: e.to_string(),
                        });
                    }
                }
            }
        });
    }

    fn stop_autopilot(&mut self) {
        let profile = self.profile();
        let mut st = store::autopilot_state(&profile);
        st.enabled = false;
        st.running = false;
        st.status = "Autopilot stopped.".to_string();
        let _ = store::save_autopilot_state(&profile, &st);
        self.monitor_started = false;
        self.refresh_autopilot();
        self.log("⏹ Autopilot stopped.".to_string());
    }
}

impl eframe::App for KhvarenahApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        while let Ok(ev) = self.events_rx.try_recv() {
            self.apply_event(ev);
        }
        // Re-read state each frame so other processes/CLI changes are seen.
        self.refresh_autopilot();
        ctx.request_repaint();

        ctx.set_visuals(egui::Visuals {
            dark_mode: true,
            panel_fill: BG,
            window_fill: BG,
            ..Default::default()
        });

        egui::SidePanel::left("sidebar")
            .exact_width(210.0)
            .resizable(false)
            .show(ctx, |ui| {
                ui.add_space(10.0);
                ui.label(
                    egui::RichText::new("Khvarenah")
                        .size(20.0)
                        .color(GOLD)
                        .strong(),
                );
                ui.label(egui::RichText::new("Cloudflare VLESS").size(12.0).color(ACCENT));
                ui.add_space(20.0);

                ui.label(egui::RichText::new("Autopilot").color(GOLD).strong());
                ui.add_space(6.0);
                let enabled = self.autopilot.enabled;
                let on_color = if enabled { GREEN } else { RED };
                ui.label(
                    egui::RichText::new(if enabled { "● ON" } else { "○ OFF" })
                        .size(16.0)
                        .color(on_color)
                        .strong(),
                );
                ui.add_space(8.0);

                if enabled {
                    if ui.button("Stop").clicked() {
                        self.stop_autopilot();
                    }
                } else {
                    if ui
                        .button(egui::RichText::new("▶ Start Autopilot").size(15.0).strong())
                        .clicked()
                    {
                        self.start_autopilot();
                    }
                }
                ui.add_space(12.0);

                if self.autopilot.enabled && !self.autopilot.current_endpoint.is_empty() {
                    ui.label("Active clean IP:");
                    ui.label(
                        egui::RichText::new(&self.autopilot.current_endpoint)
                            .color(GOLD)
                            .strong(),
                    );
                    ui.add_space(6.0);
                    if !self.autopilot.worker_name.is_empty() {
                        ui.label(format!("Worker: {}", self.autopilot.worker_name));
                    }
                    ui.label(format!("Every {} min", self.autopilot.interval_minutes));
                }
            });

        egui::SidePanel::right("log")
            .exact_width(330.0)
            .resizable(false)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.label(egui::RichText::new("Activity").color(GOLD).strong());
                ui.separator();
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .stick_to_bottom(true)
                    .show(ui, |ui| {
                        for line in &self.log_lines {
                            ui.label(egui::RichText::new(line).size(12.0));
                        }
                    });
            });

        egui::CentralPanel::default().show(ctx, |ui| {
            if let Some(err) = &self.error_banner {
                ui.colored_label(RED, err.clone());
                if ui.small_button("dismiss").clicked() {
                    self.error_banner = None;
                }
                ui.add_space(6.0);
            }

            ui.add_space(12.0);
            ui.label(
                egui::RichText::new("Your VPN, one click away")
                    .size(26.0)
                    .color(GOLD)
                    .strong(),
            );
            ui.add_space(8.0);
            ui.label("Khvarenah deploys your worker, finds the best clean IP, and keeps it alive automatically.");

            ui.add_space(24.0);

            let enabled = self.autopilot.enabled;
            // Big friendly button.
            let (text, color, action) = if enabled {
                ("Stop Autopilot", RED, 1usize)
            } else {
                ("Start Autopilot", GREEN, 0usize)
            };
            let btn = egui::Button::new(
                egui::RichText::new(text).size(18.0).color(BG).strong(),
            )
            .min_size(egui::vec2(260.0, 52.0))
            .fill(color);
            if ui.add(btn).clicked() {
                if action == 0 {
                    self.start_autopilot();
                } else {
                    self.stop_autopilot();
                }
            }

            ui.add_space(18.0);

            // Status card
            egui::Frame::none()
                .fill(egui::Color32::from_rgb(0x18, 0x12, 0x0e))
                .rounding(6.0)
                .inner_margin(12.0)
                .show(ui, |ui| {
                    ui.label(egui::RichText::new("Status").color(ACCENT).strong());
                    ui.separator();
                    ui.label(&self.autopilot.status);
                    ui.add_space(4.0);
                    if !self.autopilot.current_endpoint.is_empty() {
                        ui.label(format!(
                            "Active clean IP: {}",
                            self.autopilot.current_endpoint
                        ));
                    }
                    if self.autopilot.last_check_epoch > 0.0 {
                        ui.label(format!(
                            "Last check: {}",
                            store::now_iso()
                        ));
                    }
                });

            ui.add_space(16.0);
            ui.separator();
            ui.add_space(8.0);
            ui.label(egui::RichText::new("Where is my config?").color(ACCENT).strong());
            ui.label(
                "Your working vless config is saved to the profile's clean-configs.txt. \
                 In the terminal: khvarenah history",
            );
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn autopilot_state_default_is_off() {
        assert!(!AutopilotState::default().enabled);
        assert_eq!(AutopilotState::default().interval_minutes, 10);
    }
}
