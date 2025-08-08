"""LLM-Eval REST API package.

This package provides FastAPI-based REST endpoints for managing
evaluation runs, comparisons, and analytics for the UI-first
evaluation platform.
"""

from .main import app, create_app, run_server

__version__ = "0.3.0"
__all__ = ["app", "create_app", "run_server"]
