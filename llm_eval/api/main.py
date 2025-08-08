"""FastAPI application for LLM-Eval run management API.

This module provides REST API endpoints for managing evaluation runs,
supporting the UI-first evaluation platform with fast browsing,
filtering, and comparison capabilities.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from ..storage.database import get_database_manager, reset_database_manager
from ..utils.errors import LLMEvalError
from . import websockets
from .endpoints import comparisons, health, runs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown tasks."""
    # Startup
    logger.info("Starting LLM-Eval API server...")

    # Initialize database connection
    try:
        db_manager = get_database_manager()
        health_status = db_manager.health_check()
        if health_status["status"] != "healthy":
            logger.error(f"Database health check failed: {health_status}")
            raise RuntimeError("Database connection failed")
        logger.info("Database connection established successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down LLM-Eval API server...")
    reset_database_manager()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        redirect_slashes=False,  # Disable automatic trailing slash redirects
        title="LLM-Eval Run Management API",
        description=(
            "REST API for managing LLM evaluation runs, results, and comparisons. "
            "Supports the UI-first evaluation platform with efficient browsing, "
            "filtering, and analysis capabilities."
        ),
        version="0.3.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS for frontend integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # Next.js development
            "http://localhost:3001",  # Alternative frontend port
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            # Add production origins as needed
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Security middleware
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "*.localhost"]
    )

    # Include API routers
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])

    app.include_router(
        comparisons.router, prefix="/api/comparisons", tags=["comparisons"]
    )

    app.include_router(health.router, prefix="/api/health", tags=["health"])

    # Include WebSocket routers
    app.include_router(websockets.router, tags=["websockets"])

    # Global exception handlers
    @app.exception_handler(LLMEvalError)
    async def llm_eval_exception_handler(request: Request, exc: LLMEvalError):
        """Handle custom LLM-Eval exceptions."""
        logger.error(f"LLM-Eval error: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "LLM-Eval Error",
                "message": str(exc),
                "type": exc.__class__.__name__,
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle value errors (usually validation issues)."""
        logger.error(f"Value error: {exc}")
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation Error",
                "message": str(exc),
                "type": "ValueError",
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions."""
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "type": "InternalServerError",
            },
        )

    @app.get("/api", response_model=Dict[str, Any])
    async def api_root():
        """API root endpoint with basic information."""
        return {
            "name": "LLM-Eval Run Management API",
            "version": "0.3.0",
            "description": "REST API for evaluation run management",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    return app


# Create the FastAPI app instance
app = create_app()


def run_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Run the FastAPI server with uvicorn."""
    uvicorn.run(
        "llm_eval.api.main:app", host=host, port=port, reload=reload, log_level="info"
    )


if __name__ == "__main__":
    # For development - run with: python -m llm_eval.api.main
    run_server(reload=False)  # Disabled reload to avoid Windows file access issues
