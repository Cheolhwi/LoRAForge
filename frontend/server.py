from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    server = ThreadingHTTPServer(("127.0.0.1", 5173), lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(root), **kwargs))
    print("Frontend running at http://127.0.0.1:5173")
    server.serve_forever()
