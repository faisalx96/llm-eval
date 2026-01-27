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
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from importlib.resources import files as pkg_files
except Exception:
    pkg_files = None

from ..core.run_discovery import RunDiscovery
from ..confluence.client import (
    MockConfluenceClient,
    RealConfluenceClient,
    PublishRequest,
    AggregatePublishRequest,
    AggregateMetricResult,
    RunMetricDetail,
    get_git_info,
)

DEFAULT_RESULTS_DIR = "qym_results"
DEFAULT_CONFLUENCE_DIR = "confluence_mock"
PUBLISHED_RUNS_FILE = ".published_runs.json"

# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE CONFIGURATION (for airgapped/internal deployments)
# ══════════════════════════════════════════════════════════════════════════════
# Set these values to pre-configure Confluence for all users in your organization.
# Users won't need to set environment variables if these are configured.
# Environment variables take precedence if set.
#
# To configure: replace None with your values, e.g.:
#   CONFLUENCE_DEFAULT_URL = "https://confluence.mycompany.com"
#   CONFLUENCE_DEFAULT_SPACE = "EVAL"
#   CONFLUENCE_DEFAULT_TOKEN = "your-service-account-PAT"
#
CONFLUENCE_DEFAULT_URL: Optional[str] = None      # e.g., "https://confluence.company.com"
CONFLUENCE_DEFAULT_SPACE: Optional[str] = None    # e.g., "LLMEVAL"
CONFLUENCE_DEFAULT_TOKEN: Optional[str] = None    # Service account PAT (recommended)
CONFLUENCE_DEFAULT_USERNAME: Optional[str] = None # Only needed for basic auth, not PAT
# ══════════════════════════════════════════════════════════════════════════════


def load_published_runs(results_dir: str) -> set:
    """Load set of published run IDs from local file."""
    filepath = os.path.join(results_dir, PUBLISHED_RUNS_FILE)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("run_ids", []))
        except Exception:
            pass
    return set()


def save_published_runs(results_dir: str, run_ids: set) -> None:
    """Save set of published run IDs to local file."""
    filepath = os.path.join(results_dir, PUBLISHED_RUNS_FILE)
    os.makedirs(results_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"run_ids": sorted(run_ids)}, f, indent=2)


# Cache for auto-detected Langfuse project ID
_langfuse_project_id_cache: Optional[str] = None


def get_langfuse_project_id() -> str:
    """Get Langfuse project ID (from env or auto-detect from API)."""
    global _langfuse_project_id_cache

    # Check env var first
    project_id = os.environ.get("LANGFUSE_PROJECT_ID", "")
    if project_id:
        return project_id

    # Return cached value if available
    if _langfuse_project_id_cache is not None:
        return _langfuse_project_id_cache

    # Try to auto-detect from Langfuse API
    try:
        from langfuse import Langfuse
        client = Langfuse()

        # Try private method first (cached, no extra API call)
        if hasattr(client, '_get_project_id'):
            _langfuse_project_id_cache = client._get_project_id() or ""
        # Fallback to public API
        elif hasattr(client, 'api') and hasattr(client.api, 'projects'):
            result = client.api.projects.get()
            if result.data:
                _langfuse_project_id_cache = result.data[0].id
            else:
                _langfuse_project_id_cache = ""
        else:
            _langfuse_project_id_cache = ""
    except Exception:
        _langfuse_project_id_cache = ""

    return _langfuse_project_id_cache


class DashboardServer:
    """HTTP server for the runs dashboard with auto-close on inactivity."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        results_dir: str = DEFAULT_RESULTS_DIR,
        inactivity_timeout: int = 300,
        confluence_dir: str = DEFAULT_CONFLUENCE_DIR,
    ):
        self.host = host
        self.port = port
        self.discovery = RunDiscovery(results_dir)
        self.inactivity_timeout = inactivity_timeout

        # Initialize Confluence client - use real client if env vars are set
        self.confluence = self._init_confluence_client(confluence_dir)

        # Track published runs locally
        self.published_runs = load_published_runs(results_dir)

        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_activity = time.time()
        self._activity_lock = threading.Lock()

        # Resolve static directories
        self.dashboard_static_dir = self._resolve_dashboard_static_dir()
        self.ui_static_dir = self._resolve_ui_static_dir()

    def _init_confluence_client(self, confluence_dir: str):
        """Initialize Confluence client.
        
        Priority order for configuration:
        1. Environment variables (CONFLUENCE_URL, CONFLUENCE_API_TOKEN, etc.)
        2. Built-in defaults (CONFLUENCE_DEFAULT_* at top of this file)
        3. Mock filesystem client (fallback for development)
        """
        # Get config from env vars first, then fall back to built-in defaults
        confluence_url = os.environ.get("CONFLUENCE_URL") or CONFLUENCE_DEFAULT_URL
        confluence_user = os.environ.get("CONFLUENCE_USERNAME") or CONFLUENCE_DEFAULT_USERNAME
        confluence_token = os.environ.get("CONFLUENCE_API_TOKEN") or CONFLUENCE_DEFAULT_TOKEN
        confluence_space = os.environ.get("CONFLUENCE_SPACE_KEY") or CONFLUENCE_DEFAULT_SPACE
        
        # Username is optional for PAT auth (Server/DC 7.9+)
        if all([confluence_url, confluence_token, confluence_space]):
            auth_type = "Basic Auth" if confluence_user else "PAT (Bearer)"
            print(f"[Confluence] Using real API: {confluence_url} (space: {confluence_space}, auth: {auth_type})")
            return RealConfluenceClient(
                base_url=confluence_url,
                username=confluence_user,  # Can be None for PAT auth
                api_token=confluence_token,
                space_key=confluence_space,
            )
        else:
            print(f"[Confluence] Using mock filesystem: {confluence_dir}")
            return MockConfluenceClient(confluence_dir)

    def _resolve_dashboard_static_dir(self) -> str:
        """Resolve path to dashboard static files."""
        here = os.path.dirname(os.path.dirname(__file__))
        fallback = os.path.join(here, "_static", "dashboard")
        if os.path.isdir(fallback):
            return fallback
        if pkg_files is not None:
            try:
                p = pkg_files("qym").joinpath("_static/dashboard")
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
                p = pkg_files("qym").joinpath("_static/ui")
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
                    elif abspath.endswith(".png"):
                        ctype = "image/png"
                    elif abspath.endswith(".svg"):
                        ctype = "image/svg+xml"
                    elif abspath.endswith((".jpg", ".jpeg")):
                        ctype = "image/jpeg"
                    elif abspath.endswith(".ico"):
                        ctype = "image/x-icon"
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
                    data = index.to_dict()
                    # Rebuild Langfuse URLs dynamically if we have the IDs
                    langfuse_host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
                    langfuse_project_id = get_langfuse_project_id()
                    if langfuse_host and langfuse_project_id:
                        for run in data.get("runs", []):
                            dataset_id = run.get("langfuse_dataset_id")
                            run_id = run.get("langfuse_run_id")
                            if dataset_id and run_id:
                                run["langfuse_url"] = f"{langfuse_host}/project/{langfuse_project_id}/datasets/{dataset_id}/runs/{run_id}"
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(
                        json.dumps(data, ensure_ascii=False).encode("utf-8")
                    )
                    return

                # API: Get single run data
                if path.startswith("/api/runs/"):
                    encoded_path = path[10:]  # Remove '/api/runs/'
                    # Decode URL encoding - may need multiple passes if double-encoded
                    file_path = unquote(encoded_path)
                    while '%' in file_path and file_path != unquote(file_path):
                        file_path = unquote(file_path)
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
                    # Include Langfuse config for trace URLs
                    langfuse_host = os.environ.get("LANGFUSE_HOST", "")
                    langfuse_project_id = get_langfuse_project_id()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(
                        json.dumps({
                            "runs": runs_data,
                            "langfuse_host": langfuse_host,
                            "langfuse_project_id": langfuse_project_id,
                        }, ensure_ascii=False).encode("utf-8")
                    )
                    return

                # API: List Confluence projects
                if path == "/api/confluence/projects":
                    projects = server.confluence.list_projects()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps({
                        "projects": [
                            {"id": p.project_id, "name": p.name, "description": p.description}
                            for p in projects
                        ]
                    }, ensure_ascii=False).encode("utf-8"))
                    return

                # API: List tasks for a project
                if path.startswith("/api/confluence/projects/") and path.endswith("/tasks"):
                    project_name = unquote(path[25:-6])  # Extract project name
                    tasks = server.confluence.list_tasks(project_name)
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps({
                        "tasks": [
                            {"id": t.page_id, "title": t.title}
                            for t in tasks
                        ]
                    }, ensure_ascii=False).encode("utf-8"))
                    return

                # API: List/search Confluence users
                if path == "/api/confluence/users":
                    query = parse_qs(parsed.query)
                    search_query = query.get("q", [""])[0]
                    if search_query:
                        users = server.confluence.search_users(search_query)
                    else:
                        users = server.confluence.list_users()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps({
                        "users": [
                            {"username": u.username, "display_name": u.display_name}
                            for u in users
                        ]
                    }, ensure_ascii=False).encode("utf-8"))
                    return

                # API: Get git info (branch, commit)
                if path == "/api/git/info":
                    git_info = get_git_info()
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps(git_info, ensure_ascii=False).encode("utf-8"))
                    return

                # API: Get published run IDs (from local cache)
                if path == "/api/confluence/published":
                    self._set_headers(HTTPStatus.OK)
                    self.wfile.write(json.dumps({
                        "run_ids": list(server.published_runs)
                    }, ensure_ascii=False).encode("utf-8"))
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

                # Update metric score for a row
                if path == "/api/runs/update_metric":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))

                        file_path = data.get("file_path", "")
                        metric_name = data.get("metric_name", "")
                        row_index = data.get("row_index", None)
                        new_score = data.get("new_score", None)

                        if not file_path or metric_name == "" or row_index is None:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(b'{"error": "Missing required fields"}')
                            return

                        try:
                            row_index = int(row_index)
                        except (ValueError, TypeError):
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(b'{"error": "Invalid row_index"}')
                            return

                        update_result = server.discovery.update_metric_score(
                            file_path=file_path,
                            row_index=row_index,
                            metric_name=metric_name,
                            new_score=new_score,
                        )
                        if update_result.get("error"):
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(
                                json.dumps({"error": update_result["error"]}).encode("utf-8")
                            )
                            return

                        # Refresh run index so aggregate scores update in runs view
                        try:
                            server.discovery.scan(force_refresh=True)
                        except Exception:
                            pass

                        run_data = server.discovery.get_run_data(file_path)
                        if run_data.get("error"):
                            self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                            self.wfile.write(
                                json.dumps({"error": run_data["error"]}).encode("utf-8")
                            )
                            return

                        rows = run_data.get("snapshot", {}).get("rows", [])
                        if row_index < 0 or row_index >= len(rows):
                            self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                            self.wfile.write(b'{"error": "Row index out of range"}')
                            return

                        self._set_headers(HTTPStatus.OK)
                        self.wfile.write(
                            json.dumps(
                                {"ok": True, "row": rows[row_index], "run": run_data.get("run", {})},
                                ensure_ascii=False,
                            ).encode("utf-8")
                        )
                        return
                    except json.JSONDecodeError:
                        self._set_headers(HTTPStatus.BAD_REQUEST)
                        self.wfile.write(b'{"error": "Invalid JSON"}')
                        return
                    except Exception as e:
                        self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                        return

                # API: Publish run to Confluence
                if path == "/api/confluence/publish":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))

                        # Validate required fields
                        required = ["project_name", "task_name", "run_id", "published_by", "description"]
                        missing = [f for f in required if not data.get(f)]
                        if missing:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(json.dumps({
                                "error": f"Missing required fields: {', '.join(missing)}"
                            }).encode("utf-8"))
                            return

                        # Build publish request
                        request = PublishRequest(
                            project_name=data["project_name"],
                            task_name=data["task_name"],
                            run_id=data["run_id"],
                            published_by=data["published_by"],
                            description=data["description"],
                            metrics=data.get("metrics", {}),
                            model=data.get("model", ""),
                            dataset=data.get("dataset", ""),
                            total_items=data.get("total_items", 0),
                            success_count=data.get("success_count", 0),
                            error_count=data.get("error_count", 0),
                            avg_latency_ms=data.get("avg_latency_ms", 0),
                            branch=data.get("branch"),
                            commit=data.get("commit"),
                            trace_url=data.get("trace_url"),
                        )

                        result = server.confluence.publish_run(request)

                        if result.success:
                            # Track published run locally (reload first to respect manual edits)
                            server.published_runs = load_published_runs(server.discovery.results_dir)
                            server.published_runs.add(data["run_id"])
                            save_published_runs(server.discovery.results_dir, server.published_runs)

                            self._set_headers(HTTPStatus.OK)
                            self.wfile.write(json.dumps({
                                "success": True,
                                "page_id": result.page_id,
                                "page_url": result.page_url
                            }).encode("utf-8"))
                        else:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(json.dumps({
                                "success": False,
                                "error": result.error
                            }).encode("utf-8"))
                        return
                    except json.JSONDecodeError:
                        self._set_headers(HTTPStatus.BAD_REQUEST)
                        self.wfile.write(b'{"error": "Invalid JSON"}')
                        return
                    except Exception as e:
                        self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                        return

                # API: Publish aggregate runs to Confluence
                if path == "/api/confluence/publish-aggregate":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))

                        # Validate required fields
                        required = ["project_name", "task_name", "run_name", "published_by", "description",
                                    "model", "dataset", "task", "run_details", "metric_results"]
                        missing = [f for f in required if not data.get(f)]
                        if missing:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(json.dumps({
                                "error": f"Missing required fields: {', '.join(missing)}"
                            }).encode("utf-8"))
                            return

                        # Parse run details (per-run metrics)
                        run_details = []
                        for rd_data in data.get("run_details", []):
                            run_details.append(RunMetricDetail(
                                run_id=rd_data["run_id"],
                                langfuse_url=rd_data.get("langfuse_url"),
                                metrics=rd_data.get("metrics", {}),
                                latency_ms=rd_data.get("latency_ms", 0),
                            ))

                        # Parse metric results
                        metric_results = []
                        for mr_data in data["metric_results"]:
                            metric_results.append(AggregateMetricResult(
                                metric_name=mr_data["metric_name"],
                                threshold=mr_data["threshold"],
                                pass_at_k=mr_data["pass_at_k"],
                                pass_k=mr_data["pass_k"],
                                max_at_k=mr_data["max_at_k"],
                                consistency=mr_data["consistency"],
                                reliability=mr_data["reliability"],
                                avg_score=mr_data["avg_score"],
                                min_score=mr_data["min_score"],
                                max_score=mr_data["max_score"],
                                runs_passed=mr_data["runs_passed"],
                                total_runs=mr_data["total_runs"],
                            ))

                        # Build aggregate publish request
                        request = AggregatePublishRequest(
                            project_name=data["project_name"],
                            task_name=data["task_name"],
                            run_name=data["run_name"],
                            published_by=data["published_by"],
                            description=data["description"],
                            model=data["model"],
                            dataset=data["dataset"],
                            task=data["task"],
                            k_runs=len(run_details),
                            run_details=run_details,
                            metric_results=metric_results,
                            total_items_per_run=data.get("total_items_per_run", 0),
                            avg_latency_ms=data.get("avg_latency_ms", 0),
                            branch=data.get("branch"),
                            commit=data.get("commit"),
                        )

                        result = server.confluence.publish_aggregate_run(request)

                        if result.success:
                            # Track published aggregate run locally (reload first to respect manual edits)
                            server.published_runs = load_published_runs(server.discovery.results_dir)
                            # Add individual run IDs from run_details
                            for rd in data.get("run_details", []):
                                if rd.get("run_id"):
                                    server.published_runs.add(rd["run_id"])
                            save_published_runs(server.discovery.results_dir, server.published_runs)

                            self._set_headers(HTTPStatus.OK)
                            self.wfile.write(json.dumps({
                                "success": True,
                                "page_id": result.page_id,
                                "page_url": result.page_url
                            }).encode("utf-8"))
                        else:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(json.dumps({
                                "success": False,
                                "error": result.error
                            }).encode("utf-8"))
                        return
                    except json.JSONDecodeError:
                        self._set_headers(HTTPStatus.BAD_REQUEST)
                        self.wfile.write(b'{"error": "Invalid JSON"}')
                        return
                    except Exception as e:
                        self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                        return

                # API: Create new Confluence project
                if path == "/api/confluence/projects":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))

                        name = data.get("name", "").strip()
                        if not name:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(b'{"error": "Project name is required"}')
                            return

                        project = server.confluence.create_project(
                            name=name,
                            description=data.get("description", ""),
                            owner=data.get("owner", "")
                        )

                        self._set_headers(HTTPStatus.OK)
                        self.wfile.write(json.dumps({
                            "id": project.project_id,
                            "name": project.name
                        }).encode("utf-8"))
                        return
                    except Exception as e:
                        self._set_headers(HTTPStatus.INTERNAL_SERVER_ERROR)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                        return

                # API: Create new task page
                if path.startswith("/api/confluence/projects/") and path.endswith("/tasks"):
                    try:
                        project_name = unquote(path[25:-6])
                        content_length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_length)
                        data = json.loads(body.decode("utf-8"))

                        task_name = data.get("name", "").strip()
                        if not task_name:
                            self._set_headers(HTTPStatus.BAD_REQUEST)
                            self.wfile.write(b'{"error": "Task name is required"}')
                            return

                        task = server.confluence.create_task(project_name, task_name)

                        self._set_headers(HTTPStatus.OK)
                        self.wfile.write(json.dumps({
                            "id": task.page_id,
                            "title": task.title
                        }).encode("utf-8"))
                        return
                    except ValueError as e:
                        self._set_headers(HTTPStatus.NOT_FOUND)
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
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
            target=self.httpd.serve_forever, name="qym-dashboard", daemon=True
        )
        self.thread.start()

        # Start inactivity monitor
        self._inactivity_thread = threading.Thread(
            target=self._check_inactivity, name="qym-dashboard-monitor", daemon=True
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
