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

    npy_files = sorted(glob.glob(os.path.join(session_dir, "bounding_box_2d_tight_*.npy")))
    if not npy_files:
        npy_files = sorted(glob.glob(os.path.join(top_dir, "bounding_box_2d_tight_*.npy")))

    frames = []
    for p in npy_files:
        frame_str = os.path.splitext(os.path.basename(p))[0].split("_")[-1]
        if _find_file(dataset_dir, f"rgb_{frame_str}.png"):
            frames.append(frame_str)
    return frames


def draw_frame(dataset_dir, frame_str, max_width=None):
    rgb_path = _find_file(dataset_dir, f"rgb_{frame_str}.png")
    npy_path = _find_file(dataset_dir, f"bounding_box_2d_tight_{frame_str}.npy")
    img = Image.open(rgb_path).convert("RGB")
    if max_width and img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, int(img.height * scale)), Image.LANCZOS)
    else:
        scale = 1.0
    draw = ImageDraw.Draw(img)
    bboxes = np.load(npy_path, allow_pickle=True)
    for row in bboxes:
        x_min = float(row["x_min"]) * scale
        y_min = float(row["y_min"]) * scale
        x_max = float(row["x_max"]) * scale
        y_max = float(row["y_max"]) * scale
        cid = int(row["semanticId"])
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
        print(f"  .npy in top: {len(glob.glob(os.path.join(top, 'bounding_box_2d_tight_*.npy')))}")
        print(f"  .npy in session: {len(glob.glob(os.path.join(sess, 'bounding_box_2d_tight_*.npy')))}")
        return

    print(f"Found {len(frames)} frames in {dataset_dir}")
    print(f"Serving on http://0.0.0.0:{args.port}")
    print(f"  SSH tunnel : ssh -L {args.port}:localhost:{args.port} <user>@<host>")
    print(f"  RunPod URL : https://<pod-id>-{args.port}.proxy.runpod.net  (requires port exposed in pod settings)")
    HTTPServer(("0.0.0.0", args.port), make_handler(dataset_dir, frames)).serve_forever()


if __name__ == "__main__":
    main()