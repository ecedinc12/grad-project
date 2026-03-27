import os
import io
import glob
import argparse
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


def find_frames(dataset_dir):
    npy_files = glob.glob(os.path.join(dataset_dir, "bounding_box_2d_tight_*.npy"))
    frames = []
    for p in sorted(npy_files):
        frame_str = os.path.splitext(os.path.basename(p))[0].split("_")[-1]
        rgb_path = os.path.join(dataset_dir, f"rgb_{frame_str}.png")
        if os.path.exists(rgb_path):
            frames.append(frame_str)
    return frames


def draw_frame(dataset_dir, frame_str, max_width=None):
    rgb_path = os.path.join(dataset_dir, f"rgb_{frame_str}.png")
    npy_path = os.path.join(dataset_dir, f"bounding_box_2d_tight_{frame_str}.npy")
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
            pass  # silence access log

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
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()

    frames = find_frames(args.dir)
    if not frames:
        print(f"No frames found in {args.dir}")
        return

    print(f"Found {len(frames)} frames in {args.dir}")
    print(f"Serving on http://localhost:{args.port}")
    print(f"  SSH tunnel: ssh -L {args.port}:localhost:{args.port} <user>@<host>")
    HTTPServer(("127.0.0.1", args.port), make_handler(args.dir, frames)).serve_forever()


if __name__ == "__main__":
    main()
