import os
import io
import glob
import argparse
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
from PIL import Image, ImageDraw

PALETTE = [
    (255, 50, 50),
    (50, 200, 50),
    (50, 100, 255),
    (255, 200, 0),
    (200, 0, 255),
    (0, 220, 220),
]


def extract_tar_to_tmp(tar_path):
    tmp = tempfile.mkdtemp(prefix="ds_view_")
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(tmp)
    candidate = os.path.join(tmp, "dataset")
    return candidate if os.path.isdir(candidate) else tmp


def _resolve_dir(dataset_dir):
    replicator = os.path.join(dataset_dir, "Replicator")
    if os.path.isdir(replicator):
        return dataset_dir, replicator
    return dataset_dir, dataset_dir


def _find_file(dataset_dir, pattern):
    top_dir, session_dir = _resolve_dir(dataset_dir)
    for d in [top_dir, session_dir]:
        p = os.path.join(d, pattern)
        if os.path.exists(p):
            return p
    return None


def find_frames(dataset_dir):
    top_dir, session_dir = _resolve_dir(dataset_dir)

    txt_files = sorted(glob.glob(os.path.join(session_dir, "rgb_*.txt")))
    if not txt_files:
        txt_files = sorted(glob.glob(os.path.join(top_dir, "rgb_*.txt")))

    frames = []
    for p in txt_files:
        frame_str = os.path.splitext(os.path.basename(p))[0].split("_")[-1]
        if _find_file(dataset_dir, f"rgb_{frame_str}.png"):
            frames.append(frame_str)
    return frames


def draw_frame(dataset_dir, frame_str, max_width=None):
    rgb_path = _find_file(dataset_dir, f"rgb_{frame_str}.png")
    txt_path = _find_file(dataset_dir, f"rgb_{frame_str}.txt")
    img = Image.open(rgb_path).convert("RGB")
    original_width, original_height = img.width, img.height

    if max_width and img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, int(img.height * scale)), Image.LANCZOS)
    else:
        scale = 1.0
        
    draw = ImageDraw.Draw(img)
    
    if os.path.exists(txt_path):
        with open(txt_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cid = int(parts[0])
                    x_center = float(parts[1])
                    y_center = float(parts[2])
                    width = float(parts[3])
                    height = float(parts[4])
                    
                    x_min = (x_center - width / 2.0) * original_width * scale
                    y_min = (y_center - height / 2.0) * original_height * scale
                    x_max = (x_center + width / 2.0) * original_width * scale
                    y_max = (y_center + height / 2.0) * original_height * scale
                    
                    color = PALETTE[cid % len(PALETTE)]
                    draw.rectangle([x_min, y_min, x_max, y_max], outline=color, width=2)
                    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_handler(dataset_dir, frames):
    class GalleryHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_png(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path

            if path == "/" or path == "":
                self.serve_gallery()
            elif path.startswith("/thumb/"):
                frame_str = path[len("/thumb/"):]
                if frame_str in frames:
                    self.send_png(draw_frame(dataset_dir, frame_str, max_width=320))
                else:
                    self.send_error(404)
            elif path.startswith("/frame/"):
                frame_str = path[len("/frame/"):]
                if frame_str in frames:
                    self.send_png(draw_frame(dataset_dir, frame_str))
                else:
                    self.send_error(404)
            else:
                self.send_error(404)

        def serve_gallery(self):
            thumbs = "".join(
                f'<a href="/frame/{f}"><img src="/thumb/{f}" title="Frame {f}"></a>'
                for f in frames
            )
            html = f"""<!DOCTYPE html>
<html>
<head>
<title>Dataset Viewer ({len(frames)} frames)</title>
<style>
  body {{ background:#111; color:#eee; font-family:sans-serif; padding:16px; }}
  h1 {{ margin-bottom:12px; }}
  .grid {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .grid img {{ width:320px; height:auto; border:2px solid #333; cursor:pointer; }}
  .grid img:hover {{ border-color:#aaa; }}
</style>
</head>
<body>
<h1>Dataset Viewer &mdash; {len(frames)} frames &mdash; <small>{dataset_dir}</small></h1>
<div class="grid">{thumbs}</div>
</body>
</html>"""
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return GalleryHandler


def main():
    parser = argparse.ArgumentParser(description="Headless dataset gallery viewer.")
    parser.add_argument("--dir", default="/tmp/dataset", help="Dataset directory")
    parser.add_argument("--tar", default=None, help="Path to dataset_*.tar.gz to serve directly")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()

    if args.tar:
        print(f"Extracting {args.tar} ...")
        dataset_dir = extract_tar_to_tmp(args.tar)
    else:
        dataset_dir = args.dir

    frames = find_frames(dataset_dir)
    if not frames:
        print(f"No frames found in {dataset_dir}")
        top, sess = _resolve_dir(dataset_dir)
        print(f"  .txt in top: {len(glob.glob(os.path.join(top, 'rgb_*.txt')))}")
        print(f"  .txt in session: {len(glob.glob(os.path.join(sess, 'rgb_*.txt')))}")
        return

    print(f"Found {len(frames)} frames in {dataset_dir}")
    print(f"Serving on http://0.0.0.0:{args.port}")
    print(f"  SSH tunnel : ssh -L {args.port}:localhost:{args.port} <user>@<host>")
    print(f"  RunPod URL : https://<pod-id>-{args.port}.proxy.runpod.net  (requires port exposed in pod settings)")
    HTTPServer(("0.0.0.0", args.port), make_handler(dataset_dir, frames)).serve_forever()


if __name__ == "__main__":
    main()