"""Local web UI server for llm-eval.

Exposes a minimal HTTP server that serves the packaged static UI and
streams live evaluation snapshots over Server-Sent Events (SSE).
"""

from .app import UIServer
from .dashboard_server import DashboardServer, run_dashboard

__all__ = ["UIServer", "DashboardServer", "run_dashboard"]

