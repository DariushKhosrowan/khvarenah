//! Khvarenah GUI (eframe/egui).
//!
//! Dark console theme: background #0a0705, primary/gold #ffe096, accent
//! #a67c1a. The left sidebar lists views; the central panel renders the active
//! view. Background work runs on a shared tokio runtime and streams `UiEvent`s
//! into the log pane on the right — the UI thread never blocks.

use crate::cf_api::CfError;
use tokio::sync::mpsc;

// ---------------------------------------------------------------------------
// Async bridge
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum UiEvent {
    Log(String),
    TaskErr { task: String, error: CfError },
    StoreChanged,
    Progress(String),
}

pub type EventSender = mpsc::UnboundedSender<UiEvent>;

pub fn spawn<F, E>(handle: &tokio::runtime::Handle, tx: EventSender, task: String, future: F)
where
    F: std::future::Future<Output = Result<(), E>> + Send + 'static,
    E: Into<CfError> + Send + 'static,
{
    handle.spawn(async move {
        if let Err(e) = future.await {
            let cf: CfError = e.into();
            let _ = tx.send(UiEvent::TaskErr { task, error: cf });
        }
    });
}

pub fn channel() -> (EventSender, mpsc::UnboundedReceiver<UiEvent>) {
    mpsc::unbounded_channel()
}

pub fn runtime() -> &'static tokio::runtime::Runtime {
    static RT: once_cell::sync::OnceCell<tokio::runtime::Runtime> = once_cell::sync::OnceCell::new();
    RT.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_time()
            .worker_threads(2)
            .build()
            .expect("failed to build tokio runtime")
    })
}

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------

const BG: egui::Color32 = egui::Color32::from_rgb(0x0a, 0x07, 0x05);
const GOLD: egui::Color32 = egui::Color32::from_rgb(0xff, 0xe0, 0x96);
const ACCENT: egui::Color32 = egui::Color32::from_rgb(0xa6, 0x7c, 0x1a);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum View {
    Profiles,
    Scan,
    Deploy,
    Link,
    Health,
    History,
}

impl View {
    fn title(&self) -> &'static str {
        match self {
            View::Profiles => "Profiles",
            View::Scan => "Scan",
            View::Deploy => "Deploy",
            View::Link => "Link",
            View::Health => "Health",
            View::History => "History",
        }
    }
}

pub struct KhvarenahApp {
    events_rx: mpsc::UnboundedReceiver<UiEvent>,
    spawn_tx: EventSender,
    rt: &'static tokio::runtime::Runtime,
    active_view: View,
    log_lines: Vec<String>,
    error_banner: Option<(String, CfError)>,
    reload_pending: bool,
    run_count: u32,
}

impl KhvarenahApp {
    pub fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let rt = runtime();
        let (tx, rx) = channel();
        Self {
            events_rx: rx,
            spawn_tx: tx,
            rt,
            active_view: View::Profiles,
            log_lines: Vec::new(),
            error_banner: None,
            reload_pending: false,
            run_count: 0,
        }
    }

    fn log(&mut self, line: String) {
        self.log_lines.push(line);
        const CAP: usize = 5000;
        if self.log_lines.len() > CAP {
            let excess = self.log_lines.len() - CAP;
            self.log_lines.drain(0..excess);
        }
    }

    fn apply_event(&mut self, ev: UiEvent) {
        match ev {
            UiEvent::Log(line) => self.log(line),
            UiEvent::Progress(line) => self.log(format!("… {line}")),
            UiEvent::TaskErr { task, error } => {
                self.error_banner = Some((task, error));
            }
            UiEvent::StoreChanged => {
                self.reload_pending = true;
            }
        }
    }

    fn run_test_task(&mut self) {
        let run = self.run_count;
        self.run_count += 1;
        let tx = self.spawn_tx.clone();
        let rt = self.rt;
        let label = format!("test-task-{run}");
        spawn(rt.handle(), self.spawn_tx.clone(), label.clone(), async move {
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            let _ = tx.send(UiEvent::Log(format!(
                "[{label}] tick 1 ({}%)",
                chrono::Utc::now().format("%H:%M:%S")
            )));
            tokio::time::sleep(std::time::Duration::from_millis(400)).await;
            let _ = tx.send(UiEvent::Log(format!(
                "[{label}] tick 2 ({}%)",
                chrono::Utc::now().format("%H:%M:%S")
            )));
            tokio::time::sleep(std::time::Duration::from_millis(300)).await;
            let _ = tx.send(UiEvent::Log(format!(
                "[{label}] done ({}%)",
                chrono::Utc::now().format("%H:%M:%S")
            )));
            Ok::<(), CfError>(())
        });
    }

    fn run_failing_task(&mut self) {
        let tx = self.spawn_tx.clone();
        let rt = self.rt;
        spawn(rt.handle(), self.spawn_tx.clone(), "failing-task".to_string(), async {
            let _ = tx;
            Err::<(), CfError>(CfError::new("test", "test", "test"))
        });
    }
}

impl eframe::App for KhvarenahApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Drain events (no blocking).
        while let Ok(ev) = self.events_rx.try_recv() {
            self.apply_event(ev);
        }
        // Always repaint so the live log pane updates even without input.
        ctx.request_repaint();

        // Dark background.
        ctx.set_visuals(egui::Visuals {
            dark_mode: true,
            panel_fill: BG,
            window_fill: BG,
            ..Default::default()
        });

        egui::SidePanel::left("sidebar")
            .exact_width(200.0)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.label(
                    egui::RichText::new("Khvarenah")
                        .size(18.0)
                        .color(GOLD)
                        .strong(),
                );
                ui.add_space(12.0);
                for view in [View::Profiles, View::Scan, View::Deploy, View::Link, View::Health, View::History] {
                    let is_active = self.active_view == view;
                    let text = egui::RichText::new(view.title())
                        .color(if is_active { GOLD } else { egui::Color32::LIGHT_GRAY });
                    if ui.selectable_label(is_active, text).clicked() {
                        self.active_view = view;
                        self.log(format!("switched view → {}", view.title()));
                    }
                }
                ui.add_space(16.0);
                if ui.button("Run Test Task").clicked() {
                    self.run_test_task();
                }
                if ui.button("Run Failing Task").clicked() {
                    self.run_failing_task();
                }
            });

        egui::SidePanel::right("log")
            .exact_width(340.0)
            .show(ctx, |ui| {
                ui.add_space(6.0);
                ui.label(egui::RichText::new("Log").color(GOLD).strong());
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
            if let Some((task, err)) = &self.error_banner {
                ui.colored_label(
                    egui::Color32::from_rgb(255, 140, 120),
                    format!("[{task}] {} — {}", err.title, err.detail),
                );
                if ui.small_button("dismiss").clicked() {
                    self.error_banner = None;
                }
            }
            if self.reload_pending {
                ui.colored_label(ACCENT, "store changed — data reloaded");
                self.reload_pending = false;
            }
            ui.add_space(8.0);
            ui.label(
                egui::RichText::new(format!("{} view", self.active_view.title()))
                    .size(24.0)
                    .color(GOLD),
            );
            ui.add_space(8.0);
            ui.label("Placeholder — full view coming in later phases.");
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cf_err() -> CfError {
        CfError::new("test", "test", "test")
    }

    #[test]
    fn spawn_converts_err_to_task_err() {
        let (tx, mut rx) = channel();
        let rt = runtime();
        spawn(rt.handle(), tx, "demo-task".to_string(), async {
            Err::<(), CfError>(cf_err())
        });

        let start = std::time::Instant::now();
        let got = loop {
            match rx.try_recv() {
                Ok(e) => break Some(e),
                Err(tokio::sync::mpsc::error::TryRecvError::Empty) => {}
                Err(_) => break None,
            }
            if start.elapsed() > std::time::Duration::from_secs(5) {
                break None;
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        };
        match got {
            Some(UiEvent::TaskErr { task, error }) => {
                assert_eq!(task, "demo-task");
                assert_eq!(error.title, "test");
            }
            other => panic!("expected TaskErr, got {other:?}"),
        }
    }
}
