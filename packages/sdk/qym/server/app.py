import json
import os
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from importlib.resources import files as pkg_files  # py3.9+
except Exception:  # pragma: no cover
    pkg_files = None  # type: ignore


@dataclass
class RunState:
    run_info: Dict[str, Any] = field(default_factory=dict)
    snapshot: Dict[str, Any] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def set_run_info(self, info: Dict[str, Any]) -> None:
        with self.lock:
            self.run_info = dict(info)

    def set_snapshot(self, snap: Dict[str, Any]) -> None:
        with self.lock:
            self.snapshot = dict(snap)

    def get_run_info(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.run_info)

    def get_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.snapshot)


class _SSEClient:
    def __init__(self, handler: BaseHTTPRequestHandler):
        self.handler = handler
        self.lock = threading.Lock()
        self.active = True

    def send(self, event: str, data: Dict[str, Any]) -> bool:
        try:
            body = json.dumps(data, ensure_ascii=False)
        except Exception:
            body = '{}'
        payload = f"event: {event}\n" f"data: {body}\n\n"
        try:
            with self.lock:
                self.handler.wfile.write(payload.encode('utf-8'))
                self.handler.wfile.flush()
            return True
        except Exception:
            self.active = False
            return False


class UIServer:
    """Lightweight local UI server serving static assets and SSE/API endpoints."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.clients: List[_SSEClient] = []
        self.clients_lock = threading.Lock()
        self.run_state = RunState()
        self._stop = threading.Event()

        # Resolve static directory from package resources or filesystem
        self.static_dir = self._resolve_static_dir()

    def _resolve_static_dir(self) -> str:
        # Environment override first (useful in dev)
        env_dir = os.getenv('LLM_EVAL_STATIC_DIR')
        if env_dir and os.path.isdir(env_dir):
            return env_dir
        # Prefer local filesystem next (so changes in repo take effect in dev)
        here = os.path.dirname(os.path.dirname(__file__))
        fallback = os.path.join(here, '_static', 'ui')
        if os.path.isdir(fallback):
            return fallback
        # Finally fall back to installed package resources
        if pkg_files is not None:
            try:
                p = pkg_files('qym').joinpath('_static/ui')
                return str(p)
            except Exception:
                pass
        # Last resort: return computed fallback (may not exist)
        return fallback

    def start(self) -> Tuple[str, int]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # quiet
                return

            def _set_headers(self, status=200, content_type='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path
                # API endpoints
                if path == '/api/run':
                    data = server.run_state.get_run_info()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                    return
                if path == '/api/snapshot':
                    data = server.run_state.get_snapshot()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                    return
                if path == '/api/rows/stream':
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'keep-alive')
                    self.end_headers()
                    client = _SSEClient(self)
                    with server.clients_lock:
                        server.clients.append(client)
                    # Send initial snapshot if available
                    snap = server.run_state.get_snapshot()
                    if snap:
                        client.send('snapshot', snap)
                    # Keep alive loop
                    try:
                        while not server._stop.is_set() and client.active:
                            try:
                                # heartbeat every 15s
                                self.wfile.write(b":keep-alive\n\n")
                                self.wfile.flush()
                            except Exception:
                                break
                            time.sleep(15)
                    finally:
                        with server.clients_lock:
                            if client in server.clients:
                                server.clients.remove(client)
                    return

                # Serve UI static files at /ui/ path (for compatibility with dashboard)
                if path.startswith('/ui/'):
                    rel_path = path[4:]  # Remove '/ui/'
                    abspath = os.path.abspath(os.path.join(server.static_dir, rel_path))
                    if abspath.startswith(os.path.abspath(server.static_dir)) and os.path.exists(abspath) and not os.path.isdir(abspath):
                        try:
                            ctype = 'text/plain; charset=utf-8'
                            if abspath.endswith('.html'):
                                ctype = 'text/html; charset=utf-8'
                            elif abspath.endswith('.js'):
                                ctype = 'application/javascript; charset=utf-8'
                            elif abspath.endswith('.css'):
                                ctype = 'text/css; charset=utf-8'
                            elif abspath.endswith('.png'):
                                ctype = 'image/png'
                            elif abspath.endswith('.svg'):
                                ctype = 'image/svg+xml'
                            elif abspath.endswith(('.jpg', '.jpeg')):
                                ctype = 'image/jpeg'
                            with open(abspath, 'rb') as f:
                                data = f.read()
                            self._set_headers(HTTPStatus.OK, ctype)
                            self.wfile.write(data)
                            return
                        except Exception:
                            pass
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{}')
                    return

                # Static files
                # Map / -> index.html; otherwise serve files under static_dir
                fs_path = 'index.html' if path in ('/', '/index.html') else path.lstrip('/')
                abspath = os.path.abspath(os.path.join(server.static_dir, fs_path))
                # Prevent path traversal
                if not abspath.startswith(os.path.abspath(server.static_dir)):
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{}')
                    return
                if not os.path.exists(abspath) or os.path.isdir(abspath):
                    abspath = os.path.join(server.static_dir, 'index.html')
                try:
                    # Guess content-type
                    ctype = 'text/plain; charset=utf-8'
                    if abspath.endswith('.html'):
                        ctype = 'text/html; charset=utf-8'
                    elif abspath.endswith('.js'):
                        ctype = 'application/javascript; charset=utf-8'
                    elif abspath.endswith('.css'):
                        ctype = 'text/css; charset=utf-8'
                    elif abspath.endswith('.png'):
                        ctype = 'image/png'
                    elif abspath.endswith('.svg'):
                        ctype = 'image/svg+xml'
                    elif abspath.endswith(('.jpg', '.jpeg')):
                        ctype = 'image/jpeg'
                    with open(abspath, 'rb') as f:
                        data = f.read()
                    self._set_headers(HTTPStatus.OK, ctype)
                    self.wfile.write(data)
                except Exception:
                    self._set_headers(HTTPStatus.NOT_FOUND)
                    self.wfile.write(b'{}')

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='qym-ui', daemon=True)
        self.thread.start()
        return self.host, self.port

    def stop(self) -> None:
        self._stop.set()
        with self.clients_lock:
            # Signal clients by sending a final event; ignore errors
            for c in list(self.clients):
                try:
                    c.send('done', {'ok': True})
                except Exception:
                    pass
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

    def broadcast_snapshot(self) -> None:
        snap = self.run_state.get_snapshot()
        if not snap:
            return
        dead: List[_SSEClient] = []
        with self.clients_lock:
            for c in self.clients:
                ok = c.send('snapshot', snap)
                if not ok:
                    dead.append(c)
            for c in dead:
                if c in self.clients:
                    self.clients.remove(c)

