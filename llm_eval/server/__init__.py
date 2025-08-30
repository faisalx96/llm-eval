"""Local web UI server for llm-eval.

Exposes a minimal HTTP server that serves the packaged static UI and
streams live evaluation snapshots over Server-Sent Events (SSE).
"""

from .app import UIServer

__all__ = ["UIServer"]

