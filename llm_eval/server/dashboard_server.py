"""Dashboard server for viewing historical evaluation runs."""

import json
import os
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

try:
    from importlib.resources import files as pkg_files
except Exception:
    pkg_files = None

from ..core.run_discovery import RunDiscovery

DEFAULT_RESULTS_DIR = "llm-eval_results"


class DashboardServer:
    """HTTP server for the runs dashboard with auto-close on inactivity."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        results_dir: str = DEFAULT_RESULTS_DIR,
        inactivity_timeout: int = 300,
    ):
        self.host = host
        self.port = port
        self.discovery = RunDiscovery(results_dir)
        self.inactivity_timeout = inactivity_timeout

        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_activity = time.time()
        self._activity_lock = threading.Lock()

        # Resolve static directories
        self.dashboard_static_dir = self._resolve_dashboard_static_dir()
        self.ui_static_dir = self._resolve_ui_static_dir()

    def _resolve_dashboard_static_dir(self) -> str:
        """Resolve path to dashboard static files."""
        here = os.path.dirname(os.path.dirname(__file__))
        fallback = os.path.join(here, "_static", "dashboard")
        if os.path.isdir(fallback):
            return fallback
        if pkg_files is not None:
            try:
                p = pkg_files("llm_eval").joinpath("_static/dashboard")
                return str(p)
            except Exception:
                pass
        return fallback

    def _resolve_ui_static_dir(self) -> str:
        """Resolve path to evaluation UI static files."""
        here = os.path.dirname(os.path.dirname(__file__))
        fallback = os.path.join(here, "_static", "ui")
        if os.path.isdir(fallback):
            return fallback
        if pkg_files is not None:
            try:
                p = pkg_files("llm_eval").joinpath("_static/ui")
                return str(p)
            except Exception:
                pass
        return fallback

    def _touch_activity(self) -> None:
        """Update last activity timestamp."""
        with self._activity_lock:
            self._last_activity = time.time()

    def _check_inactivity(self) -> None:
        """Background thread to check for inactivity timeout."""
        while not self._stop.is_set():
            time.sleep(10)  # Check every 10 seconds
            with self._activity_lock:
                elapsed = time.time() - self._last_activity
            if elapsed > self.inactivity_timeout:
                print(f"\nAuto-closing dashboard after {self.inactivity_timeout}s of inactivity")
                self.stop()
                break

    def start(self, auto_open: bool = True) -> Tuple[str, int]:
        """Start the dashboard server."""
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return  # Quiet logging

            def _set_headers(
                self, status=200, content_type="application/json; charset=utf-8"
            ):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

            def _serve_file(self, base_dir: str, rel_path: str) -> bool:
                """Serve a static file from base_dir."""
                abspath = os.path.abspath(os.path.join(base_dir, rel_path))
                # Prevent path traversal
                if not abspath.startswith(os.path.abspath(base_dir)):
                    return False
                if not os.path.exists(abspath) or os.path.isdir(abspath):
                    return False
                try:
                    ctype = "text/plain; charset=utf-8"
                    if abspath.endswith(".html"):
                        ctype = "text/html; charset=utf-8"
                    elif abspath.endswith(".js"):
                        ctype = "application/javascript; charset=utf-8"
                    elif abspath.endswith(".css"):
                        ctype = "text/css; charset=utf-8"
                    elif abspath.endswith(".json"):
                        ctype = "application/json; charset=utf-8"
                    with open(abspath, "rb") as f:
                        data = f.read()
                    self._set_headers(HTTPStatus.OK, ctype)
                    self.wfile.write(data)
                    return True
                except Exception:
                    return False

            def do_GET(self):
                server._touch_activity()
                parsed = urlparse(self.path)
                path = parsed.path

                # API: List all runs
                if path == "/api/runs":
                    index = server.discovery.scan()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(
                        json.dumps(index.to_dict(), ensure_ascii=False).encode("utf-8")
                    )
                    return

                # API: Get single run data
                if path.startswith("/api/runs/"):
                    encoded_path = path[10:]  # Remove '/api/runs/'
                    file_path = unquote(encoded_path)
                    data = server.discovery.get_run_data(file_path)
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(
                        json.dumps(data, ensure_ascii=False).encode("utf-8")
                    )
                    return

                # Serve evaluation UI for historical run
                if path.startswith("/run/"):
                    # Serve the existing evaluation UI index.html
                    if self._serve_file(server.ui_static_dir, "index.html"):
                        return
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{"error": "UI not found"}')
                    return

                # Serve comparison page
                if path == "/compare":
                    if self._serve_file(server.dashboard_static_dir, "compare.html"):
                        return
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{"error": "Compare page not found"}')
                    return

                # API: Get multiple runs for comparison
                if path == "/api/compare":
                    query = parse_qs(parsed.query)
                    files = query.get("files", [])
                    if not files:
                        self._set_headers(HTTPStatus.BAD_REQUEST)
                        self.wfile.write(b'{"error": "No files specified"}')
                        return
                    # files is a list, could be comma-separated or multiple params
                    all_files = []
                    for f in files:
                        all_files.extend(f.split(","))
                    runs_data = []
                    for file_path in all_files:
                        file_path = unquote(file_path.strip())
                        if file_path:
                            data = server.discovery.get_run_data(file_path)
                            if not data.get("error"):
                                runs_data.append(data)
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(
                        json.dumps({"runs": runs_data}, ensure_ascii=False).encode("utf-8")
                    )
                    return

                # Serve evaluation UI static files (CSS, JS)
                if path.startswith("/ui/"):
                    rel_path = path[4:]  # Remove '/ui/'
                    if self._serve_file(server.ui_static_dir, rel_path):
                        return
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{}')
                    return

                # Serve dashboard static files
                if path.startswith("/static/"):
                    rel_path = path[8:]  # Remove '/static/'
                    if self._serve_file(server.dashboard_static_dir, rel_path):
                        return
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{}')
                    return

                # Dashboard home
                if path in ("/", "/index.html"):
                    if self._serve_file(server.dashboard_static_dir, "index.html"):
                        return
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{"error": "Dashboard not found"}')
                    return

                # Fallback to dashboard static
                if self._serve_file(server.dashboard_static_dir, path.lstrip("/")):
                    return

                self._set_headers(HTTPStatus.NOT_FOUND)
                self.wfile.write(b'{}')

            def do_POST(self):
                server._touch_activity()
                parsed = urlparse(self.path)
                path = parsed.path

                # Heartbeat endpoint
                if path == "/api/heartbeat":
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(b'{"ok": true}')
                    return

                # Delete run endpoint
                if path == "/api/runs/delete":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))
                        file_path = data.get("file_path", "")

                        if not file_path:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(b'{"error": "No file_path provided"}')
                            return

                        # Security: Ensure path is within results directory
                        abs_path = os.path.abspath(file_path)
                        results_abs = os.path.abspath(server.discovery.results_dir)
                        if not abs_path.startswith(results_abs):
                            self._set_headers(HTTPStatus.FORBIDDEN)
                            self.wfile.write(b'{"error": "Access denied"}')
                            return

                        if not os.path.exists(abs_path):
                            self._set_headers(HTTPStatus.NOT_FOUND)
                            self.wfile.write(b'{"error": "File not found"}')
                            return

                        # Delete the file
                        os.remove(abs_path)

                        # Try to clean up empty parent directories
                        try:
                            parent = os.path.dirname(abs_path)
                            while parent and parent != results_abs:
                                if os.path.isdir(parent) and not os.listdir(parent):
                                    os.rmdir(parent)
                                    parent = os.path.dirname(parent)
                                else:
                                    break
                        except Exception:
                            pass  # Ignore cleanup errors

                        # Force refresh the cache
                        server.discovery.scan(force_refresh=True)

                        self._set_headers(HTTPStatus.OK)
                        self.wfile.write(b'{"ok": true}')
                        return
                    except json.JSONDecodeError:
                        self._set_headers(HTTPStatus.BAD_REQUEST)
                        self.wfile.write(b'{"error": "Invalid JSON"}')
                        return
                    except Exception as e:
                        self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                        return

                self._set_headers(HTTPStatus.NOT_FOUND)
                self.wfile.write(b'{}')

        # Create server
        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]

        # Start server thread
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, name="llm-eval-dashboard", daemon=True
        )
        self.thread.start()

        # Start inactivity monitor
        self._inactivity_thread = threading.Thread(
            target=self._check_inactivity, name="llm-eval-dashboard-monitor", daemon=True
        )
        self._inactivity_thread.start()

        url = f"http://{self.host}:{self.port}/"
        print(f"Dashboard running at: {url}")

        if auto_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        return self.host, self.port

    def stop(self) -> None:
        """Stop the dashboard server."""
        self._stop.set()
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
        if self.thread:
            try:
                self.thread.join(timeout=2)
            except Exception:
                pass

    def wait(self) -> None:
        """Block until server stops."""
        try:
            while not self._stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down dashboard...")
            self.stop()


def run_dashboard(
    port: int = 8080,
    results_dir: str = DEFAULT_RESULTS_DIR,
    timeout: int = 300,
    auto_open: bool = True,
) -> None:
    """Run the dashboard server (blocking)."""
    server = DashboardServer(
        host="127.0.0.1",
        port=port,
        results_dir=results_dir,
        inactivity_timeout=timeout,
    )
    server.start(auto_open=auto_open)
    server.wait()
