import os
import argparse
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

def extract_tar_to_tmp(tar_path):
    """Extract a dataset tar.gz to a temp directory and return the path."""
    tmp = tempfile.mkdtemp(prefix="video_view_")
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(tmp)
    candidate = os.path.join(tmp, "dataset")
    return candidate if os.path.isdir(candidate) else tmp

def make_handler(video_path):
    class VideoHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # silence access log

        def do_GET(self):
            if self.path == "/" or self.path == "":
                self.serve_html()
            elif self.path == "/video.mp4":
                self.serve_video()
            else:
                self.send_error(404)

        def serve_html(self):
            html = f"""<!DOCTYPE html>
<html>
<head>
<title>Video Viewer</title>
<style>
  body {{ background:#111; color:#eee; font-family:sans-serif; padding:16px; text-align:center; }}
  video {{ max-width: 90vw; max-height: 80vh; border: 2px solid #333; }}
</style>
</head>
<body>
<h1>Video Viewer &mdash; <small>{video_path}</small></h1>
<video controls autoplay loop>
  <source src="/video.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>
</body>
</html>"""
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_video(self):
            try:
                file_size = os.path.getsize(video_path)
                range_header = self.headers.get("Range", None)

                if not range_header:
                    # No range requested — serve the whole file
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()
                    with open(video_path, "rb") as f:
                        while True:
                            chunk = f.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return

                # Parse Range header (e.g. "bytes=0-1023")
                unit, ranges = range_header.split("=")
                if unit.strip() != "bytes":
                    self.send_error(416, "Only byte ranges are supported")
                    return

                range_start_str, range_end_str = ranges.split("-")
                range_start = int(range_start_str) if range_start_str else 0
                range_end = int(range_end_str) if range_end_str else file_size - 1
                range_end = min(range_end, file_size - 1)

                if range_start >= file_size or range_start > range_end:
                    self.send_error(416, "Range not satisfiable")
                    return

                content_length = range_end - range_start + 1

                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(content_length))
                self.send_header(
                    "Content-Range",
                    f"bytes {range_start}-{range_end}/{file_size}",
                )
                self.end_headers()

                with open(video_path, "rb") as f:
                    f.seek(range_start)
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(64 * 1024, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            except Exception as e:
                self.send_error(500, str(e))

    return VideoHandler

def main():
    parser = argparse.ArgumentParser(description="Headless video viewer.")
    parser.add_argument("--video", default="/tmp/dataset/output.mp4", help="Path to the MP4 video file")
    parser.add_argument("--tar", default=None, help="Path to dataset_*.tar.gz to serve the video directly from it")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()

    video_path = args.video
    if args.tar:
        print(f"Extracting {args.tar} ...")
        dataset_dir = extract_tar_to_tmp(args.tar)
        video_path = os.path.join(dataset_dir, "output.mp4")

    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return

    print(f"Serving video: {video_path}")
    print(f"Serving on http://0.0.0.0:{args.port}")
    print(f"  SSH tunnel : ssh -L {args.port}:localhost:{args.port} <user>@<host>")
    print(f"  RunPod URL : https://<pod-id>-{args.port}.proxy.runpod.net")
    
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(video_path))
    server.serve_forever()

if __name__ == "__main__":
    main()
