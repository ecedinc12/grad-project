
from __future__ import annotations

import base64
import glob
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Generator, Iterable, List, Optional, Tuple

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
}


def _use_mock_pipeline() -> bool:
    m = os.environ.get("GRADIO_MOCK", "").strip().lower()
    if m in ("1", "true", "yes"):
        return True
    if m in ("0", "false", "no"):
        return False
    return not os.path.isdir("/workspace")


USE_MOCK_PIPELINE = _use_mock_pipeline()
DEFAULT_ENDPOINT = os.environ.get("RUNPOD_URL", "").strip()

# -----------------------------------------------------------------------------
# Styling (charcoal + teal)
# -----------------------------------------------------------------------------
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
#forge-nav .forge-nav-logo-wrap { width: 40px !important; display: flex !important; align-items: center !important; justify-content: center !important; }
#forge-nav .forge-nav-logo-img { width: 40px !important; height: auto !important; max-height: 48px !important; object-fit: contain !important; display: block !important; border-radius: 4px !important; }

/* Explorer */
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
#forge-explorer hr.forge-sep { border: none !important; border-top: 1px solid var(--line) !important; margin: 12px 0 !important; }

#forge-main { flex: 1 1 0 !important; min-width: 0 !important; display: flex !important; flex-direction: column !important; gap: 12px !important; position: relative !important; }

/* Workspace */
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
    border: none !important; box-shadow: none !important; background: transparent !important; margin-bottom: 8px !important;
}
#forge-workspace button.tab { color: var(--muted) !important; border: none !important; background: transparent !important; font-size: 14px !important; padding: 6px 14px 6px 0 !important; }
#forge-workspace button.tab.selected { color: var(--text) !important; border-bottom: 2px solid var(--teal) !important; border-radius: 0 !important; }

#forge-video-empty {
    flex: 1 1 auto !important; min-height: 420px !important;
    background: #0e1016 !important; border-radius: 10px !important; border: 1px solid var(--line) !important;
}

#forge-log-mount .forge-log-frame {
    flex: 1 1 auto !important; min-height: 420px !important;
    background: #0e1016 !important; border-radius: 10px !important; border: 1px solid var(--line) !important;
    display: flex !important; flex-direction: column !important;
    justify-content: flex-end !important; align-items: flex-start !important;
    padding: 20px 24px 28px !important; box-sizing: border-box !important;
}
#forge-log-mount .forge-log-scroll { width: 100% !important; max-height: 340px !important; overflow-y: auto !important; margin-bottom: 8px !important; }
#forge-log-mount .forge-log-line { font-family: ui-monospace, Menlo, monospace !important; font-size: 13px !important; margin: 4px 0 !important; color: var(--muted) !important; }
#forge-log-mount .forge-log-error { color: var(--red) !important; }
#forge-log-mount .forge-log-success { color: var(--lime) !important; }

/* Footer */
#forge-footer {
    display: flex !important; flex-direction: row !important;
    align-items: stretch !important; justify-content: space-between !important;
    gap: 24px !important; padding: 16px 20px !important;
    background: var(--panel-inner) !important; border: 1px solid var(--teal-dim) !important;
    border-radius: 16px !important; flex-wrap: wrap !important;
}
#forge-footer .forge-hint { font-size: 11px !important; color: var(--muted) !important; margin-top: 6px !important; line-height: 1.3 !important; }
#forge-footer label { color: var(--muted) !important; font-size: 11px !important; }
#forge-footer input, #forge-footer textarea { background: var(--panel) !important; border: 1px solid var(--line) !important; color: var(--text) !important; border-radius: 999px !important; padding: 8px 14px !important; }
#forge-footer #forge-prompt input, #forge-footer #forge-prompt textarea { border-radius: 999px !important; font-size: 13px !important; }

/* Endpoint row (bottom) */
#forge-endpoint-row {
    margin-top: -4px !important;
    padding: 10px 16px !important;
    background: var(--panel-inner) !important;
    border: 1px solid var(--line) !important;
    border-radius: 12px !important;
}
#forge-endpoint-row input, #forge-endpoint-row textarea {
    background: var(--panel) !important;
    border: 1px solid var(--line) !important;
    color: var(--text) !important;
    border-radius: 10px !important;
    font-family: ui-monospace, Menlo, monospace !important;
    font-size: 12px !important;
    padding: 8px 12px !important;
}
#forge-endpoint-row label { color: var(--muted) !important; font-size: 11px !important; }
#forge-endpoint-row .forge-hint { margin-top: 4px !important; }

/* Outline pill buttons (Select preset / Run) */
#forge-footer button.forge-pill {
    background: var(--panel) !important;
    color: var(--text) !important;
    border: 1px solid var(--line) !important;
    border-radius: 999px !important;
    padding: 8px 18px !important;
    font-weight: 500 !important;
    box-shadow: none !important;
}
#forge-footer button.forge-pill:hover { border-color: var(--teal) !important; background: #1a1f2a !important; }
#forge-footer button.forge-pill.forge-run { border-color: var(--teal) !important; }

/* Preset modal overlay */
#forge-preset-modal {
    position: absolute !important;
    left: 0 !important; right: 0 !important; top: 0 !important; bottom: 0 !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
    background: rgba(6, 8, 12, 0.68) !important;
    z-index: 9999 !important;
    padding: 24px !important;
    backdrop-filter: blur(2px) !important;
}
#forge-preset-modal .forge-modal-card {
    width: min(520px, 92%) !important;
    background: var(--panel) !important;
    border: 1px solid var(--teal-dim) !important;
    border-radius: 14px !important;
    padding: 18px 20px !important;
}
#forge-preset-modal .forge-modal-head {
    display: flex !important; align-items: center !important; justify-content: space-between !important;
    margin-bottom: 10px !important;
}
#forge-preset-modal .forge-modal-title { font-size: 14px !important; font-weight: 600 !important; color: var(--text) !important; }
#forge-preset-modal .forge-modal-sub { font-size: 12px !important; color: var(--muted) !important; margin-bottom: 10px !important; }
#forge-preset-modal label { color: var(--muted) !important; }
#forge-preset-modal .gr-button { border-radius: 999px !important; }
#forge-preset-modal .forge-modal-foot {
    display: flex !important; justify-content: flex-end !important; gap: 10px !important; margin-top: 12px !important;
}

.forge-hidden-io { display: none !important; }
"""


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
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
        logo = (
            '<div class="forge-nav-logo-wrap" style="width:36px;height:36px;border-radius:4px;'
            'border:2px solid #3dd9c9;background:#1a1f28;">&nbsp;</div>'
        )
    return (
        '<div style="display:flex;flex-direction:column;align-items:center;gap:22px;width:100%;">'
        f"{logo}"
        '<div style="width:36px;height:36px;border-radius:6px;border:1px solid #3dd9c9;'
        "background:rgba(61,217,201,0.12);display:flex;align-items:center;justify-content:center;"
        'font-size:17px;line-height:1;" title="Project">&#128193;</div>'
        '<div style="opacity:0.75;color:#8b95a8;font-size:18px;line-height:1;" title="Assets">&#9638;</div>'
        "</div>"
    )


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

VIDEO_EMPTY_HTML = '<div id="forge-video-empty"></div>'


def _format_log_html(raw: str) -> str:
    text = (raw or "").strip()
    status = (
        '<div class="forge-log-line forge-log-error">Generation Failed</div>'
        '<div class="forge-log-line forge-log-success">Pipeline Success</div>'
    )
    if not text:
        return f'<div id="forge-log-mount"><div class="forge-log-frame">{status}</div></div>'
    inner = ""
    for line in (raw or "").splitlines():
        esc = html.escape(line)
        low = line.lower()
        cls = "forge-log-line"
        if any(k in low for k in ("fail", "error", "hata", "exited with code", "başlatılamadı", "[runner error]")):
            cls += " forge-log-error"
        elif any(k in low for k in ("success", "tamamlandı", "pipeline success")):
            cls += " forge-log-success"
        inner += f'<div class="{cls}">{esc}</div>'
    body = f'<div class="forge-log-scroll">{inner}</div>'
    return f'<div id="forge-log-mount"><div class="forge-log-frame">{body}</div></div>'


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


def _stream_runpod(endpoint: str, prompt: str) -> Iterable[str]:
    """POST JSON to a RunPod HTTP endpoint and yield streamed text lines."""
    url = endpoint.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/x-ndjson, text/plain",
        },
    )
    yield f"[runpod] POST {url}\n"
    try:
        with urllib.request.urlopen(req, timeout=60 * 30) as resp:
            yield f"[runpod] HTTP {resp.status}\n"
            buf = b""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    yield line.decode("utf-8", errors="replace") + "\n"
            if buf:
                yield buf.decode("utf-8", errors="replace") + "\n"
    except urllib.error.HTTPError as e:
        yield f"[runpod] HTTP hata {e.code}: {e.reason}\n"
        try:
            yield e.read().decode("utf-8", errors="replace") + "\n"
        except Exception:  # noqa: BLE001
            pass
    except urllib.error.URLError as e:
        yield f"[runpod] bağlantı hatası: {e.reason}\n"
    except Exception as e:  # noqa: BLE001
        yield f"[runpod] beklenmeyen hata: {e}\n"


# -----------------------------------------------------------------------------
# Run handler
# -----------------------------------------------------------------------------
def run_pipeline(
    prompt: str,
    endpoint: str,
) -> Generator[
    Tuple[str, List[str], Optional[str], Optional[str]],
    None,
    None,
]:
    log: List[str] = []

    def emit() -> Tuple[str, List[str], Optional[str], Optional[str]]:
        return (
            _format_log_html("".join(log)),
            _sorted_rgb_frames(),
            _annotated_video_if_exists(),
            _newest_archive(),
        )

    prompt = (prompt or "").strip()
    if not prompt:
        log.append("Hata: Önce bir preset seçin.\n")
        yield emit()
        return

    endpoint = (endpoint or "").strip()

    # Gerçek RunPod HTTP akışı
    if endpoint:
        log.append(f"[RUN] prompt: {prompt}\n")
        yield emit()
        for line in _stream_runpod(endpoint, prompt):
            log.append(line)
            yield emit()
        yield emit()
        return

    # Endpoint yok → mock veya yerel script
    if USE_MOCK_PIPELINE:
        log.append("[MOCK] RunPod URL boş; örnek akış çalışıyor.\n")
        yield emit()
        for i in range(1, 5):
            log.append(f"[MOCK] step {i}/4… {prompt[:40]}\n")
            time.sleep(0.2)
            yield emit()
        log.append("[MOCK] Pipeline Success\n")
        yield emit()
        return

    cmd = ["/bin/bash", RUN_SCRIPT, prompt]
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
        yield emit()
        return

    try:
        for line in _stream_process_output(proc):
            log.append(line)
            yield emit()
    except Exception as e:  # noqa: BLE001
        log.append(f"\n[runner error] {e}\n")
        yield emit()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    yield emit()


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
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

    with gr.Blocks(title="SDG Forge — Pipeline", fill_width=True) as demo:
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
                        columns=4, rows=2, height=120,
                        object_fit="contain", elem_id="dt-gallery",
                    )
                    archive_fp = gr.File(interactive=False)

                with gr.Row(elem_id="forge-footer"):
                    with gr.Column(scale=0, min_width=160):
                        preset_btn = gr.Button(
                            "Select preset",
                            elem_classes=["forge-pill"],
                        )
                    with gr.Column(scale=6, min_width=240, elem_id="forge-prompt-col"):
                        scene_tb = gr.Textbox(
                            value="",
                            placeholder="Prompt — sahneyi tarif edin…",
                            label="Prompt",
                            elem_id="forge-prompt",
                            container=True,
                            lines=1,
                            max_lines=3,
                        )
                    with gr.Column(scale=0, min_width=120):
                        run_btn = gr.Button(
                            "Run →",
                            variant="primary",
                            elem_classes=["forge-pill", "forge-run"],
                        )
                        gr.Markdown("Enter to run", elem_classes=["forge-hint"])

                with gr.Row(elem_id="forge-endpoint-row"):
                    with gr.Column(scale=1):
                        endpoint_tb = gr.Textbox(
                            value=DEFAULT_ENDPOINT,
                            placeholder="https://<pod-id>.proxy.runpod.net/generate",
                            label="RunPod URL (HTTP)",
                            elem_id="forge-endpoint",
                            container=True,
                        )

                # Preset modal overlay
                with gr.Column(
                    visible=False,
                    elem_id="forge-preset-modal",
                ) as preset_modal:
                    with gr.Column(elem_classes=["forge-modal-card"]):
                        gr.HTML(
                            '<div class="forge-modal-head">'
                            '<div class="forge-modal-title">Preset seç</div>'
                            "</div>"
                            '<div class="forge-modal-sub">Senaryolardan birini seçin, '
                            'alanı doldurup pencereyi kapatacağız.</div>'
                        )
                        preset_radio = gr.Radio(
                            choices=list(PRESETS.keys()),
                            value=None,
                            label="Senaryolar",
                            container=False,
                        )
                        with gr.Row(elem_classes=["forge-modal-foot"]):
                            modal_cancel = gr.Button("Vazgeç", elem_classes=["forge-pill"])
                            modal_apply = gr.Button(
                                "Uygula",
                                variant="primary",
                                elem_classes=["forge-pill", "forge-run"],
                            )

        # --- Events -----------------------------------------------------------
        def _open_modal() -> Any:
            return gr.update(visible=True)

        def _close_modal() -> Any:
            return gr.update(visible=False)

        def _apply_preset(choice: Optional[str]) -> Tuple[Any, Any]:
            if not choice:
                return gr.update(visible=False), gr.update()
            prompt = PRESETS.get(choice, "")
            return gr.update(visible=False), gr.update(value=prompt)

        preset_btn.click(fn=_open_modal, outputs=preset_modal)
        modal_cancel.click(fn=_close_modal, outputs=preset_modal)
        modal_apply.click(
            fn=_apply_preset,
            inputs=preset_radio,
            outputs=[preset_modal, scene_tb],
        )

        run_btn.click(
            fn=run_pipeline,
            inputs=[scene_tb, endpoint_tb],
            outputs=[log_html, gallery, video_annotated, archive_fp],
        )
        scene_tb.submit(
            fn=run_pipeline,
            inputs=[scene_tb, endpoint_tb],
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
