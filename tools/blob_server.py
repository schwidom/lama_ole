"""Minimal HTTP server serving ollama model store blobs and manifests.

Endpoints:
  GET /health                  -> {"status": "ok"}
  GET /manifest/<name>/<tag>   -> manifest JSON
  GET /blobs/<safe-digest>     -> blob binary data
  GET /show/<name>/<tag>       -> config blob JSON

Usage:
  python3 -m lama_ole.tools.blob_server [--port PORT] [--host HOST]
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

MODELS_DIR = None


def _find_models_dir():
    env = os.environ.get("OLLAMA_MODELS")
    if env and os.path.isdir(os.path.join(env, "blobs")):
        return env
    candidates = [
        os.path.expanduser("~/.ollama/models"),
        "/usr/share/ollama/.ollama/models",
        "/var/snap/ollama/common/models",
    ]
    for path in candidates:
        if os.path.isdir(os.path.join(path, "blobs")):
            return path
    return os.path.expanduser("~/.ollama/models")


class Handler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        try:
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except OSError:
            self.send_error(404, "Not found")

    def _manifest_path(self, name, tag):
        if "/" in name:
            parts = ["manifests", "registry.ollama.ai"] + name.split("/")
        else:
            parts = ["manifests", "registry.ollama.ai", "library", name]
        return os.path.join(MODELS_DIR, *parts, tag)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._send_json({"status": "ok"})
            return

        if path.startswith("/manifest/"):
            rel = path[len("/manifest/"):]
            idx = rel.rfind("/")
            if idx < 0:
                self.send_error(400, "Bad request")
                return
            tag = rel[idx + 1:]
            name = rel[:idx]
            mpath = self._manifest_path(name, tag)
            if os.path.exists(mpath):
                with open(mpath) as f:
                    self._send_json(json.load(f))
            else:
                self.send_error(404, "Manifest not found")
            return

        if path.startswith("/blobs/"):
            safe = path[len("/blobs/"):]
            blob_path = os.path.join(MODELS_DIR, "blobs", safe)
            self._send_file(blob_path)
            return

        if path.startswith("/show/"):
            rel = path[len("/show/"):]
            idx = rel.rfind("/")
            if idx < 0:
                self.send_error(400, "Bad request")
                return
            tag = rel[idx + 1:]
            name = rel[:idx]
            mpath = self._manifest_path(name, tag)
            if not os.path.exists(mpath):
                self.send_error(404, "Manifest not found")
                return
            with open(mpath) as f:
                manifest = json.load(f)
            config_digest = manifest.get("config", {}).get("digest", "")
            if not config_digest:
                self.send_error(404, "Config blob not found")
                return
            config_path = os.path.join(
                MODELS_DIR, "blobs", config_digest.replace(":", "-")
            )
            if not os.path.exists(config_path):
                self.send_error(404, "Config blob not found")
                return
            with open(config_path) as f:
                config = json.load(f)
            self._send_json({"config": config})
            return

        self.send_error(404, "Not found")

    def log_message(self, format, *args):
        sys.stderr.write("[blob_server] %s\n" % (format % args))


def run_server(host="127.0.0.1", port=0, models_dir=None):
    global MODELS_DIR
    MODELS_DIR = models_dir or _find_models_dir()
    server = HTTPServer((host, port), Handler)
    addr = server.server_address
    print(f"Blob server listening on {host}:{addr[1]}", file=sys.stderr)
    print(f"Models dir: {MODELS_DIR}", file=sys.stderr)
    sys.stderr.flush()
    print(addr[1], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ollama blob HTTP server")
    parser.add_argument("--port", type=int, default=0, help="Port (0 = random)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
