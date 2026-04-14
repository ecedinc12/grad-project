
from __future__ import annotations

import glob
import os
import subprocess
import time
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Tuple

import gradio as gr

# -----------------------------------------------------------------------------
# Paths & presets
# -----------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "run_pipeline.sh")
DATASET_DIR = "/tmp/dataset"
RGB_GLOB = os.path.join(DATASET_DIR, "rgb_*.png")
VIDEO_PATH = os.path.join(DATASET_DIR, "output.mp4")
ARCHIVE_GLOB = os.path.join(PROJECT_ROOT, "dataset_*.tar.gz")

PRESETS: dict[str, str] = {
    "PPE İhlali": (
        "İşçi tehlike bölgesinde baret ve yelek olmadan; forklift arka planda."
    ),
    "Forklift Yakın Geçiş": (
        "Forklift ile işçi arasında dar koridor; yakın geçiş senaryosu, PPE uyumlu işçi."
    ),
    "Tehlike Bölgesi İhlali": (
        "İşçi sınırlı güvenlik çizgisinin dışına taşmış; zemin uyarı çizgileri görünür."
    ),
    "Gece Vardiyası / Düşük Işık": (
        "Gece vardiyası, yapay alan aydınlatması; PPE eksikliği vurgulu çekim."
    ),
    "Özel (aşağıdaki metni düzenleyin)": "",
}


def _use_mock_pipeline() -> bool:
    """RunPod: /workspace genelde vardır. Yerel geliştirme: mock akış."""
    m = os.environ.get("GRADIO_MOCK", "").strip().lower()
    if m in ("1", "true", "yes"):
        return True
    if m in ("0", "false", "no"):
        return False
    return not os.path.isdir("/workspace")


USE_MOCK_PIPELINE = _use_mock_pipeline()

# Industrial / engineering dashboard — tam genişlik + responsive
# fill_width=True + aşağıdaki kurallar: içerik tüm ekrana yayılır (yan siyah şerit kalkar).
CUSTOM_CSS = """
/* Viewport boyunca tam genişlik (Gradio’nun iç sınırlayıcıları gevşetilir) */
.gradio-container {
    max-width: none !important;
    width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    box-sizing: border-box !important;
    padding-left: clamp(0.75rem, 2vw, 1.5rem) !important;
    padding-right: clamp(0.75rem, 2vw, 1.5rem) !important;
}
/* Üst seviye uygulama kabı — tam genişlik */
gradio-app {
    width: 100% !important;
    max-width: 100% !important;
}
footer { display: none !important; }
.gr-panel { border-radius: 10px !important; }

/* Geniş ekranda iki sütun yan yana; oran korunur, üst sınır yok */
@media (min-width: 901px) {
    #dt-dashboard-row {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: flex-start !important;
        gap: 1rem !important;
        width: 100% !important;
    }
    #dt-sidebar-col {
        flex: 0 1 34% !important;
        min-width: 260px !important;
        max-width: none !important;
    }
    #dt-log-col {
        flex: 1 1 0 !important;
        min-width: 0 !important;
    }
}

/* Tablet/telefon: tek sütun */
@media (max-width: 900px) {
    #dt-dashboard-row {
        flex-direction: column !important;
        align-items: stretch !important;
    }
    #dt-sidebar-col,
    #dt-log-col {
        min-width: 0 !important;
        width: 100% !important;
        max-width: 100% !important;
    }
    #dt-log-col textarea {
        max-height: min(50vh, 28rem) !important;
    }
}

/* Çok dar ekran: başlık ve boşluk */
@media (max-width: 480px) {
    .gradio-container h3 { font-size: 1.05rem !important; line-height: 1.35 !important; }
    #dt-log-col textarea {
        min-height: 10rem !important;
        max-height: 45vh !important;
    }
}

/* Galeri: sütun sayısını ekrana göre sıkıştır; DOM farklıysa yatay kaydırma */
@media (max-width: 768px) {
    #dt-gallery {
        min-height: 280px !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
    #dt-gallery [class*="grid"],
    #dt-gallery [style*="grid-template"] {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
}
@media (max-width: 420px) {
    #dt-gallery [class*="grid"],
    #dt-gallery [style*="grid"] {
        grid-template-columns: 1fr !important;
    }
}

/* Video ve dosya: taşma yok */
#dt-video video,
#dt-video .container {
    width: 100% !important;
    max-width: 100% !important;
    height: auto !important;
}
"""


def _sorted_rgb_frames(limit: int = 12) -> List[str]:
    paths = glob.glob(RGB_GLOB)
    paths.sort()
    return paths[:limit]


def _newest_archive() -> Optional[str]:
    archives = glob.glob(ARCHIVE_GLOB)
    if not archives:
        return None
    archives.sort(key=lambda p: os.path.getmtime(p))
    return archives[-1]


def _video_if_exists() -> Optional[str]:
    return VIDEO_PATH if os.path.isfile(VIDEO_PATH) else None


def _stream_process_output(proc: subprocess.Popen[str]) -> Iterable[str]:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        yield line
    proc.wait()
    if proc.returncode != 0:
        yield f"\n[process exited with code {proc.returncode}]\n"


def run_pipeline(
    prompt: str,
) -> Generator[Tuple[str, List[str], Optional[str], Optional[str]], None, None]:
    """
    Logları satır satır biriktirip yield eder; bittiğinde galeri / video / arşiv yollarını günceller.
    """
    log: List[str] = []

    def emit(
        chunk: str,
    ) -> Tuple[str, List[str], Optional[str], Optional[str]]:
        return "".join(log), _sorted_rgb_frames(), _video_if_exists(), _newest_archive()

    if not (prompt or "").strip():
        log.append("Hata: Serbest sahne tanımı boş. Metin girin veya bir senaryo seçin.\n")
        yield emit("")
        return

    # --- Mock: RunPod dışı / GRADIO_MOCK=1 — gerçek subprocess yok ---
    if USE_MOCK_PIPELINE:
        for i in range(1, 6):
            log.append(f"[MOCK] Log test {i}... pipeline çalışmıyor (USE_MOCK_PIPELINE=True)\n")
            time.sleep(0.15)
            yield emit("")
        log.append("[MOCK] Tamamlandı. RunPod (/workspace) veya GRADIO_MOCK=0 ile gerçek akış.\n")
        yield emit("")
        return

    # --- Gerçek çalıştırma ---
    cmd = ["/bin/bash", RUN_SCRIPT, prompt.strip()]
    # Yerelde subprocess yerine sahte log için: üstteki `if USE_MOCK_PIPELINE` bloğunu True kabul edin
    # veya `export GRADIO_MOCK=1` kullanın.
    proc: Optional[subprocess.Popen[str]] = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except OSError as e:
        log.append(f"Pipeline başlatılamadı ({cmd[0]} {RUN_SCRIPT}): {e}\n")
        yield emit("")
        return

    assert proc is not None
    p = proc
    try:
        for line in _stream_process_output(p):
            log.append(line)
            yield emit("")
    except Exception as e:  # noqa: BLE001 — UI'da göstermek için
        log.append(f"\n[runner error] {e}\n")
        yield emit("")
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    yield emit("")


def build_ui() -> Tuple[gr.Blocks, gr.themes.Soft]:
    theme = gr.themes.Soft(
        primary_hue="slate",
        secondary_hue="gray",
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    )

    with gr.Blocks(
        title="SDG Digital Twin — Kontrol",
        fill_width=True,
    ) as demo:
        gr.Markdown("### Endüstriyel Güvenlik — SDG Pipeline")
        with gr.Row(elem_id="dt-dashboard-row", equal_height=False):
            with gr.Column(scale=4, min_width=260, elem_id="dt-sidebar-col"):
                gr.Markdown("#### Kontrol Merkezi")
                preset_dd = gr.Dropdown(
                    choices=list(PRESETS.keys()),
                    value=next(iter(PRESETS)),
                    label="Hazır Senaryolar",
                )
                scene_tb = gr.Textbox(
                    label="Serbest Sahne Tanımı",
                    lines=6,
                    placeholder="Senaryo seçin veya doğrudan sahne tarifini yazın…",
                    value=PRESETS[next(iter(PRESETS))],
                )
                run_btn = gr.Button("▶ SİMÜLASYONU BAŞLAT", variant="primary")

            with gr.Column(scale=8, min_width=260, elem_id="dt-log-col"):
                gr.Markdown("#### Pipeline Log Akışı")
                log_tb = gr.Textbox(
                    label="stdout",
                    lines=22,
                    max_lines=30,
                    interactive=False,
                    buttons=["copy"],
                )

        gr.Markdown("---")
        with gr.Tabs():
            with gr.Tab("Görsel Galeri"):
                gallery = gr.Gallery(
                    label="İlk 12 RGB kare (`/tmp/dataset/rgb_*.png`)",
                    columns=4,
                    rows=3,
                    height=420,
                    object_fit="contain",
                    elem_id="dt-gallery",
                )
            with gr.Tab("Video & İndirme"):
                video = gr.Video(
                    label="Özet video (`/tmp/dataset/output.mp4`)",
                    elem_id="dt-video",
                )
                archive_fp = gr.File(
                    label="Dataset arşivi (`dataset_*.tar.gz` — proje kökü)",
                    interactive=False,
                )

        preset_dd.change(
            fn=lambda k: PRESETS.get(k, ""),
            inputs=preset_dd,
            outputs=scene_tb,
        )

        run_btn.click(
            fn=run_pipeline,
            inputs=scene_tb,
            outputs=[log_tb, gallery, video, archive_fp],
        )

        if USE_MOCK_PIPELINE:
            gr.Markdown(
                "*Mock mod:* `/workspace` yok veya `GRADIO_MOCK=1`. "
                "Gerçek pipeline için RunPod veya `GRADIO_MOCK=0` kullanın.*"
            )

    return demo, theme


if __name__ == "__main__":
    app, ui_theme = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
        theme=ui_theme,
        css=CUSTOM_CSS,
    )
