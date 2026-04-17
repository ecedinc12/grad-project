from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import gradio as gr
import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("DROPLET_API_KEY", "")

# Backend URL: önce kalıcı dosyadan oku, yoksa env'den al
_CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "/opt/grad-project/.backend_url"))
_ENV_BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")


def _load_backend_url() -> str:
    try:
        if _CONFIG_FILE.is_file():
            url = _CONFIG_FILE.read_text().strip()
            if url:
                return url
    except OSError:
        pass
    return _ENV_BACKEND_URL


def _save_backend_url(url: str) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(url.strip())
    except OSError:
        pass


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


def _fetch_frames_after_run(backend_url: str) -> List[str]:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{backend_url}/frames", headers=_auth_headers())
            resp.raise_for_status()
            return resp.json().get("frames", [])
    except Exception:
        return []


def _download_video(backend_url: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{backend_url}/video", headers=_auth_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
    except Exception:
        return None


def _download_archive(backend_url: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.get(f"{backend_url}/archive", headers=_auth_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Backend URL kaydet + bağlantı testi
# ---------------------------------------------------------------------------
def save_and_test_backend(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        return "❌ URL boş bırakılamaz."
    _save_backend_url(url)
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"{url}/health", headers=_auth_headers())
            if resp.status_code == 200:
                return f"✅ Bağlantı başarılı — {url}"
            return f"⚠️ Sunucu yanıt verdi ama status: {resp.status_code}"
    except httpx.ConnectError:
        return f"❌ Bağlanamadı: {url}\n   Pod açık mı? HTTP Service port 8000 aktif mi?"
    except Exception as exc:
        return f"❌ Hata: {exc}"


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
Result = Tuple[str, List[str], Optional[str], Optional[str]]


def run_pipeline(prompt: str, backend_url: str) -> Generator[Result, None, None]:
    log: List[str] = []
    backend_url = backend_url.strip().rstrip("/")

    def emit() -> Result:
        return "".join(log), [], None, None

    if not (prompt or "").strip():
        log.append("Hata: Sahne tanımı boş. Metin girin veya bir senaryo seçin.\n")
        yield emit()
        return

    # --- Mock mod (URL yoksa) ---
    if not backend_url:
        for i in range(1, 4):
            log.append(f"[MOCK] Adım {i}/3 — BACKEND_URL tanımlı değil\n")
            time.sleep(0.15)
            yield emit()
        log.append("[MOCK] RunPod URL'sini aşağıdaki alana girin ve kaydedin.\n")
        yield emit()
        return

    log.append(f"[*] Backend: {backend_url}\n")
    yield emit()

    try:
        with httpx.Client(timeout=httpx.Timeout(None, connect=10.0)) as client:
            with client.stream(
                "POST",
                f"{backend_url}/generate",
                json={"prompt": prompt.strip()},
                headers={**_auth_headers(), "Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code == 409:
                    log.append("[WARN] Pipeline zaten çalışıyor. Lütfen bekleyin.\n")
                    yield emit()
                    return
                if resp.status_code == 401:
                    log.append("[ERROR] API anahtarı geçersiz (401).\n")
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
        log.append(
            f"\n[ERROR] Bağlanamadı: {backend_url}\n"
            "        Pod açık mı? HTTP Service port 8000 aktif mi?\n"
        )
        yield emit()
        return
    except Exception as exc:
        log.append(f"\n[ERROR] {exc}\n")
        yield emit()
        return

    log.append("[*] Kareler alınıyor...\n")
    yield emit()
    frames = _fetch_frames_after_run(backend_url)

    log.append("[*] Video indiriliyor...\n")
    yield emit()
    video_path = _download_video(backend_url)

    log.append("[*] Arşiv indiriliyor...\n")
    yield emit()
    archive_path = _download_archive(backend_url)

    log.append(
        f"[✓] {len(frames)} kare  |  "
        f"video={'✓' if video_path else '✗'}  |  "
        f"arşiv={'✓' if archive_path else '✗'}\n"
    )
    yield "".join(log), frames, video_path, archive_path


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

        # ------------------------------------------------------------------ #
        # RunPod bağlantı ayarı — her pod yeniden başladığında buradan güncelle
        # ------------------------------------------------------------------ #
        with gr.Accordion("⚙️ RunPod Bağlantısı", open=not bool(_load_backend_url())):
            with gr.Row():
                backend_url_tb = gr.Textbox(
                    label="RunPod Backend URL",
                    placeholder="https://<pod-id>-8000.proxy.runpod.net",
                    value=_load_backend_url(),
                    scale=5,
                )
                save_btn = gr.Button("Kaydet & Test Et", scale=1, variant="secondary")
            conn_status = gr.Markdown("")

        gr.Markdown("---")

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
                    show_copy_button=True,
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

        # ------------------------------------------------------------------ #
        # Event handlers
        # ------------------------------------------------------------------ #
        save_btn.click(
            fn=save_and_test_backend,
            inputs=backend_url_tb,
            outputs=conn_status,
        )

        preset_dd.change(
            fn=lambda k: PRESETS.get(k, ""),
            inputs=preset_dd,
            outputs=scene_tb,
        )

        run_btn.click(
            fn=run_pipeline,
            inputs=[scene_tb, backend_url_tb],
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
