from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FrontendHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        if self.path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    frontend_root = Path(__file__).resolve().parent
    root = frontend_root / "dist"
    if not (root / "index.html").is_file():
        raise SystemExit("React frontend build is missing. Run `npm run build` first.")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 5173),
        lambda *args, **kwargs: FrontendHandler(*args, directory=str(root), **kwargs),
    )
    print("Frontend running at http://127.0.0.1:5173")
    server.serve_forever()
