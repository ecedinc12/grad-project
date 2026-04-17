from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import gradio as gr
import httpx
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
API_KEY = os.environ.get("DROPLET_API_KEY", "")

# BACKEND_URL yoksa mock mod
USE_MOCK = not BACKEND_URL or os.environ.get("GRADIO_MOCK", "").strip().lower() in ("1", "true", "yes")

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

CUSTOM_CSS = """
.gradio-container {
    max-width: none !important;
    width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    box-sizing: border-box !important;
    padding-left: clamp(0.75rem, 2vw, 1.5rem) !important;
    padding-right: clamp(0.75rem, 2vw, 1.5rem) !important;
}
gradio-app {
    width: 100% !important;
    max-width: 100% !important;
}
footer { display: none !important; }
.gr-panel { border-radius: 10px !important; }

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

@media (max-width: 480px) {
    .gradio-container h3 { font-size: 1.05rem !important; line-height: 1.35 !important; }
    #dt-log-col textarea {
        min-height: 10rem !important;
        max-height: 45vh !important;
    }
}

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

#dt-video video,
#dt-video .container {
    width: 100% !important;
    max-width: 100% !important;
    height: auto !important;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _auth_headers() -> dict[str, str]:
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}


def _fetch_frames_after_run(log: Optional[List[str]] = None) -> List[Image.Image]:
    """Backend'den kareleri indir, PIL.Image listesi döndür.

    Hatalar hem print hem de log listesine yazılır (Gradio textarea'da görünür).
    """
    def _err(msg: str) -> None:
        print(msg)
        if log is not None:
            log.append(msg + "\n")

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{BACKEND_URL}/frames", headers=_auth_headers())
            resp.raise_for_status()
            data = resp.json()
            names: List[str] = data.get("frames", [])

        if not names:
            _err("[WARN] /frames endpoint boş döndü — rgb_*.png henüz yazılmamış olabilir.")
            return []

        images: List[Image.Image] = []
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            for name in names:
                url = f"{BACKEND_URL}/frame/{name}"
                try:
                    img_resp = client.get(url, headers=_auth_headers())
                    img_resp.raise_for_status()
                    img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                    images.append(img)
                except Exception as e:
                    _err(f"[WARN] Frame indirilemedi ({name}): {e}")
                    continue

        return images
    except Exception as e:
        _err(f"[ERROR] Frame fetch hatası: {e}")
        return []


def _download_video() -> Optional[str]:
    """output.mp4'ü geçici dosyaya indir, yolunu döndür."""
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{BACKEND_URL}/video", headers=_auth_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
    except Exception:
        return None


def _download_archive() -> Optional[str]:
    """En son tar.gz arşivini geçici dosyaya indir, yolunu döndür."""
    try:
        with httpx.Client(timeout=180) as client:
            resp = client.get(f"{BACKEND_URL}/archive", headers=_auth_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            suffix = ".tar.gz"
            cd = resp.headers.get("content-disposition", "")
            if "filename=" in cd:
                suffix = "." + cd.split("filename=")[-1].strip('"').split(".")[-1]
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
    except Exception as e:
        print(f"[ERROR] _download_archive: {e}")
        return None


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
Result = Tuple[str, List[Image.Image], Optional[str], Optional[str]]


def run_pipeline(prompt: str) -> Generator[Result, None, None]:
    log: List[str] = []
    _frames: List[Image.Image] = []
    _video: Optional[str] = None
    _archive: Optional[str] = None

    def emit() -> Result:
        return "".join(log), _frames, _video, _archive

    if not (prompt or "").strip():
        log.append("Hata: Sahne tanımı boş. Metin girin veya bir senaryo seçin.\n")
        yield emit()
        return

    # --- Mock mod ---
    if USE_MOCK:
        for i in range(1, 6):
            log.append(f"[MOCK] Adım {i}/5 — pipeline bağlantısı yok (BACKEND_URL tanımlı değil)\n")
            time.sleep(0.15)
            yield emit()
        log.append("[MOCK] Gerçek akış için Droplet .env dosyasına BACKEND_URL ekleyin.\n")
        yield emit()
        return

    # --- Gerçek akış: SSE ---
    log.append(f"[*] Backend bağlantısı: {BACKEND_URL}\n")
    yield emit()

    try:
        with httpx.Client(timeout=httpx.Timeout(None, connect=10.0)) as client:
            with client.stream(
                "POST",
                f"{BACKEND_URL}/generate",
                json={"prompt": prompt.strip()},
                headers={**_auth_headers(), "Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code == 409:
                    log.append("[WARN] Pipeline zaten çalışıyor. Lütfen bekleyin.\n")
                    yield emit()
                    return
                if resp.status_code == 401:
                    log.append("[ERROR] API anahtarı geçersiz (401 Unauthorized).\n")
                    yield emit()
                    return
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]

                    if chunk.startswith("[DONE]"):
                        ok = "ERROR" not in chunk
                        log.append(
                            "\n[✓] Pipeline tamamlandı.\n" if ok
                            else f"\n[!] Pipeline hatayla bitti: {chunk}\n"
                        )
                        yield emit()
                        break

                    if chunk.startswith("[FATAL]"):
                        log.append(f"\n[FATAL] {chunk}\n")
                        yield emit()
                        return

                    log.append(chunk + "\n")
                    yield emit()

    except httpx.ConnectError:
        log.append(f"\n[ERROR] Backend'e bağlanılamadı: {BACKEND_URL}\n"
                   "        RunPod pod'unun açık ve HTTP service'in etkin olduğundan emin olun.\n")
        yield emit()
        return
    except Exception as exc:
        log.append(f"\n[ERROR] {exc}\n")
        yield emit()
        return

    # --- Pipeline bitti: medyayı çek (SSE bağlantısı kapalı, RunPod hazır) ---
    log.append("[*] Kareler alınıyor...\n")
    yield emit()
    _frames = _fetch_frames_after_run(log)
    log.append(f"[*] {len(_frames)} kare alındı.\n")
    yield emit()

    log.append("[*] Video indiriliyor...\n")
    yield emit()
    _video = _download_video()
    log.append(f"[*] Video {'alındı' if _video else 'bulunamadı'}.\n")

    log.append("[*] Arşiv indiriliyor...\n")
    yield emit()
    _archive = _download_archive()

    log.append(f"[✓] {len(_frames)} kare, video={'var' if _video else 'yok'}, "
               f"arşiv={'var' if _archive else 'yok'}\n")
    yield emit()


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
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
                    label="İlk 12 RGB kare",
                    columns=4,
                    rows=3,
                    height=420,
                    object_fit="contain",
                    elem_id="dt-gallery",
                )
            with gr.Tab("Video & İndirme"):
                video = gr.Video(
                    label="Özet video",
                    elem_id="dt-video",
                )
                archive_fp = gr.File(
                    label="Dataset arşivi (.tar.gz)",
                    interactive=False,
                )

        if USE_MOCK:
            gr.Markdown(
                "⚠️ *Mock mod:* `BACKEND_URL` tanımlı değil. "
                "Gerçek pipeline için Droplet `.env` dosyasına `BACKEND_URL` ekleyin."
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

    return demo, theme


if __name__ == "__main__":
    app, ui_theme = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=ui_theme,
        css=CUSTOM_CSS,
    )
