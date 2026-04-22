
from __future__ import annotations

import base64
import glob
import html
import os
import subprocess
import sys
import time
from typing import Generator, Iterable, List, Optional, Tuple

try:
    import gradio as gr
except ModuleNotFoundError as e:
    if e.name != "gradio":
        raise
    sys.stderr.write(
        "Gradio bu Python için yüklü değil.\n"
        f"  Kullanılan yorumlayıcı: {sys.executable}\n"
        "  ui klasöründe sanal ortam:\n"
        "    cd ui && ./setup_venv.sh && ./run.sh\n"
    )
    raise SystemExit(1) from e

# -----------------------------------------------------------------------------
# Paths & presets
# -----------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "run_pipeline.sh")
DATASET_DIR = "/tmp/dataset"
RGB_GLOB = os.path.join(DATASET_DIR, "rgb_*.png")
ANNOTATED_VIDEO_PATH = os.path.join(DATASET_DIR, "output_annotated.mp4")
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
    m = os.environ.get("GRADIO_MOCK", "").strip().lower()
    if m in ("1", "true", "yes"):
        return True
    if m in ("0", "false", "no"):
        return False
    return not os.path.isdir("/workspace")


USE_MOCK_PIPELINE = _use_mock_pipeline()

# Mockup: charcoal + teal border + lime success + red fail (palette strip in design)
CUSTOM_CSS = """
:root {
    --bg: #0a0b0d;
    --panel: #12141a;
    --panel-inner: #161a22;
    --text: #e8eef6;
    --muted: #7a8496;
    --line: #2a303c;
    --teal: #3dd9c9;
    --teal-dim: rgba(61, 217, 201, 0.45);
    --lime: #b6ff5c;
    --red: #ff5a5a;
}
.gradio-container {
    max-width: none !important;
    width: 100% !important;
    margin: 0 !important;
    background: var(--bg) !important;
    color: var(--text) !important;
    padding: 1rem 1.1rem !important;
    box-sizing: border-box !important;
}
gradio-app { width: 100% !important; max-width: 100% !important; }
footer { display: none !important; }

#forge-shell {
    display: flex !important;
    flex-direction: row !important;
    align-items: stretch !important;
    gap: 10px !important;
    width: 100% !important;
    min-height: calc(100vh - 2.5rem) !important;
}

/* Far-left icon rail */
#forge-nav {
    flex: 0 0 52px !important;
    width: 52px !important;
    min-width: 52px !important;
    background: var(--panel) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    padding: 14px 0 !important;
    align-items: center !important;
}
#forge-nav .forge-nav-logo-wrap {
    width: 40px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
#forge-nav .forge-nav-logo-img {
    width: 40px !important;
    height: auto !important;
    max-height: 48px !important;
    object-fit: contain !important;
    display: block !important;
    border-radius: 4px !important;
}

/* Explorer: Project Name + lists + separators */
#forge-explorer {
    flex: 0 0 220px !important;
    width: 220px !important;
    min-width: 200px !important;
    max-width: 260px !important;
    background: var(--panel) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    padding: 0 !important;
    overflow: hidden !important;
}
#forge-explorer .forge-explorer-inner { padding: 14px 16px 18px; color: var(--text); font-size: 13px; line-height: 1.5; }
#forge-explorer .forge-explorer-header {
    display: flex !important; align-items: center !important; justify-content: space-between !important;
    font-weight: 600 !important; font-size: 14px !important; margin-bottom: 14px !important;
}
#forge-explorer .forge-chev { color: var(--muted) !important; font-size: 12px !important; letter-spacing: -2px !important; }
#forge-explorer .forge-file { color: var(--text) !important; padding: 6px 0 !important; font-weight: 400 !important; }
#forge-explorer hr.forge-sep {
    border: none !important; border-top: 1px solid var(--line) !important;
    margin: 12px 0 !important;
}

#forge-main {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 12px !important;
}

/* Main workspace: teal rounded frame */
#forge-workspace {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    background: var(--panel-inner) !important;
    border: 1px solid var(--teal-dim) !important;
    border-radius: 16px !important;
    padding: 10px 14px 14px !important;
    display: flex !important;
    flex-direction: column !important;
}
#forge-workspace .tab-nav, #forge-workspace .tabs {
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
    margin-bottom: 8px !important;
}
#forge-workspace button.tab {
    color: var(--muted) !important;
    border: none !important;
    background: transparent !important;
    font-size: 14px !important;
    padding: 6px 14px 6px 0 !important;
}
#forge-workspace button.tab.selected {
    color: var(--text) !important;
    border-bottom: 2px solid var(--teal) !important;
    border-radius: 0 !important;
}

/* Video tab: empty dark panel */
#forge-video-empty {
    flex: 1 1 auto !important;
    min-height: 420px !important;
    background: #0e1016 !important;
    border-radius: 10px !important;
    border: 1px solid var(--line) !important;
}

/* Logs: large dark area, status lines bottom-left */
#forge-log-mount .forge-log-frame {
    flex: 1 1 auto !important;
    min-height: 420px !important;
    background: #0e1016 !important;
    border-radius: 10px !important;
    border: 1px solid var(--line) !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-end !important;
    align-items: flex-start !important;
    padding: 20px 24px 28px !important;
    box-sizing: border-box !important;
}
#forge-log-mount .forge-log-frame.forge-log-stream {
    justify-content: flex-end !important;
}
#forge-log-mount .forge-log-scroll {
    width: 100% !important;
    max-height: 340px !important;
    overflow-y: auto !important;
    margin-bottom: 8px !important;
}
#forge-log-mount .forge-log-line { font-family: ui-monospace, Menlo, monospace !important; font-size: 13px !important; margin: 4px 0 !important; }
#forge-log-mount .forge-log-error { color: var(--red) !important; }
#forge-log-mount .forge-log-success { color: var(--lime) !important; }
#forge-log-mount .forge-log-body .forge-log-line { color: var(--muted) !important; }
#forge-log-mount .forge-log-body .forge-log-error { color: var(--red) !important; }
#forge-log-mount .forge-log-body .forge-log-success { color: var(--lime) !important; }

/* Bottom control strip (teal outline bar) */
#forge-footer {
    display: flex !important;
    flex-direction: row !important;
    align-items: stretch !important;
    justify-content: space-between !important;
    gap: 24px !important;
    padding: 16px 20px !important;
    background: var(--panel-inner) !important;
    border: 1px solid var(--teal-dim) !important;
    border-radius: 16px !important;
    flex-wrap: wrap !important;
}
#forge-footer .forge-hint {
    font-size: 11px !important;
    color: var(--muted) !important;
    margin-top: 6px !important;
    line-height: 1.3 !important;
}
#forge-footer label { color: var(--muted) !important; font-size: 11px !important; }
#forge-footer .wrap { min-width: 200px !important; }
/* Select preset = dropdown look muted */
#forge-footer input, #forge-footer .wrap-inner { border-color: var(--line) !important; }
/* Run → : teal border, dark fill (not solid teal pill) */
#forge-footer button.primary {
    background: var(--panel) !important;
    color: var(--text) !important;
    border: 1px solid var(--teal) !important;
    font-weight: 500 !important;
    box-shadow: none !important;
}
#forge-footer button.primary:hover {
    border-color: var(--teal) !important;
    background: #1a1f2a !important;
}

/* Hide labels on invisible pipeline outputs */
.forge-hidden-io { display: none !important; }
"""

def _logo_data_uri() -> Optional[str]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fp:
        return "data:image/png;base64," + base64.standard_b64encode(fp.read()).decode("ascii")


def _nav_html() -> str:
    uri = _logo_data_uri()
    if uri:
        logo = (
            f'<div class="forge-nav-logo-wrap" title="Logo">'
            f'<img class="forge-nav-logo-img" src="{uri}" alt="" />'
            f"</div>"
        )
    else:
        logo = """
<div class="forge-nav-logo-wrap" style="width:36px;height:36px;border-radius:4px;border:2px solid #3dd9c9;background:#1a1f28;display:flex;align-items:center;justify-content:center;">
  <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <rect x="6" y="20" width="20" height="5" rx="1" fill="#3d4450" stroke="#e8eef6" stroke-width="0.8"/>
    <path d="M10 20 L16 8 L22 20" stroke="#e8eef6" stroke-width="1.2" fill="#2a3038"/>
    <rect x="13" y="6" width="6" height="4" rx="0.5" fill="#3dd9c9" opacity="0.9"/>
  </svg>
</div>"""
    return f"""
<div style="display:flex;flex-direction:column;align-items:center;gap:22px;width:100%;">
  {logo}
  <div style="width:36px;height:36px;border-radius:6px;border:1px solid #3dd9c9;background:rgba(61,217,201,0.12);display:flex;align-items:center;justify-content:center;font-size:17px;line-height:1;" title="Project">&#128193;</div>
  <div style="opacity:0.75;color:#8b95a8;font-size:18px;line-height:1;" title="Assets">&#9638;</div>
</div>
"""

EXPLORER_HTML = """
<div class="forge-explorer-inner">
  <div class="forge-explorer-header"><span>Project Name</span><span class="forge-chev">&lt;&lt;</span></div>
  <div class="forge-file">label1.txt</div>
  <div class="forge-file">label2.txt</div>
  <div class="forge-file">label3.txt</div>
  <hr class="forge-sep" />
  <div class="forge-file">image1.png</div>
  <div class="forge-file">image2.png</div>
  <div class="forge-file">image3.png</div>
</div>
"""

VIDEO_EMPTY_HTML = """
<div id="forge-video-empty"></div>
"""


def _format_log_html(raw: str) -> str:
    text = (raw or "").strip()
    status = (
        '<div class="forge-log-line forge-log-error">Generation Failed</div>'
        '<div class="forge-log-line forge-log-success">Pipeline Success</div>'
    )
    if not text:
        return (
            f'<div id="forge-log-mount"><div class="forge-log-frame">{status}</div></div>'
        )
    lines = (raw or "").splitlines()
    inner = ""
    for line in lines:
        esc = html.escape(line)
        low = line.lower()
        cls = "forge-log-line"
        if any(
            k in low
            for k in (
                "fail",
                "error",
                "hata",
                "exited with code",
                "başlatılamadı",
                "[runner error]",
            )
        ):
            cls += " forge-log-error"
        elif any(
            k in low
            for k in (
                "success",
                "tamamlandı",
                "mock] tamam",
                "pipeline success",
            )
        ):
            cls += " forge-log-success"
        inner += f'<div class="{cls}">{esc}</div>'
    body = f'<div class="forge-log-scroll forge-log-body">{inner}</div>'
    return (
        f'<div id="forge-log-mount"><div class="forge-log-frame forge-log-stream">{body}</div></div>'
    )


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


def _annotated_video_if_exists() -> Optional[str]:
    return ANNOTATED_VIDEO_PATH if os.path.isfile(ANNOTATED_VIDEO_PATH) else None


def _stream_process_output(proc: subprocess.Popen[str]) -> Iterable[str]:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        yield line
    proc.wait()
    if proc.returncode != 0:
        yield f"\n[process exited with code {proc.returncode}]\n"


def run_pipeline(
    prompt: str,
) -> Generator[
    Tuple[str, List[str], Optional[str], Optional[str]],
    None,
    None,
]:
    log: List[str] = []

    def emit(
        chunk: str,
    ) -> Tuple[str, List[str], Optional[str], Optional[str]]:
        return (
            _format_log_html("".join(log)),
            _sorted_rgb_frames(),
            _annotated_video_if_exists(),
            _newest_archive(),
        )

    if not (prompt or "").strip():
        log.append("Hata: Serbest sahne tanımı boş. Metin girin veya bir senaryo seçin.\n")
        yield emit("")
        return

    if USE_MOCK_PIPELINE:
        for i in range(1, 6):
            log.append(f"[MOCK] Log test {i}... pipeline çalışmıyor (USE_MOCK_PIPELINE=True)\n")
            time.sleep(0.15)
            yield emit("")
        log.append("[MOCK] Tamamlandı. RunPod (/workspace) veya GRADIO_MOCK=0 ile gerçek akış.\n")
        yield emit("")
        return

    cmd = ["/bin/bash", RUN_SCRIPT, prompt.strip()]
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
    except Exception as e:  # noqa: BLE001
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


def build_ui() -> Tuple[gr.Blocks, gr.themes.Base]:
    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.gray,
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    ).set(
        body_background_fill="#0a0b0d",
        body_background_fill_dark="#0a0b0d",
        background_fill_primary="#12141a",
        background_fill_secondary="#0e1016",
        border_color_primary="#2a303c",
        color_accent="rgb(61, 217, 201)",
        color_accent_soft="rgba(61, 217, 201, 0.1)",
        body_text_color="#e8eef6",
        body_text_color_subdued="#7a8496",
        input_background_fill="#161a22",
        block_background_fill="#12141a",
        block_label_text_color="#7a8496",
        block_title_text_color="#e8eef6",
    )

    with gr.Blocks(
        title="SDG Forge — Pipeline",
        fill_width=True,
    ) as demo:
        with gr.Row(elem_id="forge-shell", equal_height=True):
            with gr.Column(scale=0, min_width=52, elem_id="forge-nav"):
                gr.HTML(_nav_html())

            with gr.Column(scale=0, min_width=200, elem_id="forge-explorer"):
                gr.HTML(EXPLORER_HTML)

            with gr.Column(scale=1, min_width=280, elem_id="forge-main"):
                with gr.Group(elem_id="forge-workspace"):
                    with gr.Tabs(elem_id="forge-work-tabs", selected=1):
                        with gr.Tab("Video"):
                            gr.HTML(VIDEO_EMPTY_HTML)
                        with gr.Tab("Logs"):
                            log_html = gr.HTML(value=_format_log_html(""))

                with gr.Column(visible=False, elem_classes=["forge-hidden-io"]):
                    video_annotated = gr.Video(elem_id="dt-video-annotated")
                    gallery = gr.Gallery(
                        columns=4,
                        rows=2,
                        height=120,
                        object_fit="contain",
                        elem_id="dt-gallery",
                    )
                    archive_fp = gr.File(interactive=False)

                scene_tb = gr.Textbox(
                    value=PRESETS[next(iter(PRESETS))],
                    lines=3,
                    visible=False,
                )

                with gr.Row(elem_id="forge-footer"):
                    with gr.Column(scale=5, min_width=200):
                        preset_dd = gr.Dropdown(
                            choices=list(PRESETS.keys()),
                            value=next(iter(PRESETS)),
                            label="Select preset",
                            container=True,
                        )
                        gr.Markdown("Select from common scenarios", elem_classes=["forge-hint"])
                    with gr.Column(scale=1, min_width=120):
                        run_btn = gr.Button("Run →", variant="primary")
                        gr.Markdown("Enter to run", elem_classes=["forge-hint"])

        preset_dd.change(
            fn=lambda k: PRESETS.get(k, ""),
            inputs=preset_dd,
            outputs=scene_tb,
        )

        run_btn.click(
            fn=run_pipeline,
            inputs=scene_tb,
            outputs=[log_html, gallery, video_annotated, archive_fp],
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
