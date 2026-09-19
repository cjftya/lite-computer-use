import http.server
import socketserver
import sys
from pathlib import Path

PORT = 8765
DIRECTORY = Path(__file__).resolve().parent / "fixtures"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

def run():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving fixtures from {DIRECTORY} at http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    run()
