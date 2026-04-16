from __future__ import annotations

from pathlib import Path
from typing import Iterable

from fastapi import Request
from fastapi.responses import FileResponse


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def docs_build_dir() -> Path:
    return _repo_root() / "docs_portal" / "build"


def docs_static_dir() -> Path:
    return Path(__file__).resolve().parent / "_static" / "docs"


def _docs_root(root_path: str = "") -> Path:
    build_dir = docs_build_dir()
    if (build_dir / "index.html").exists():
        return build_dir
    return docs_static_dir()


def docs_available() -> bool:
    return (_docs_root() / "index.html").exists()


def _candidate_paths(raw_path: str, root_path: str = "") -> Iterable[Path]:
    docs_root = _docs_root(root_path)
    if not raw_path or raw_path == ".":
        yield docs_root / "index.html"
        return

    cleaned = raw_path.strip("/")
    target = (docs_root / cleaned).resolve()
    if docs_root.resolve() not in target.parents and target != docs_root.resolve():
        yield docs_root / "index.html"
        return

    if target.is_dir():
        yield target / "index.html"
    yield target
    yield target / "index.html"
    yield docs_root / "index.html"


def docs_file_response(request: Request, raw_path: str = "") -> FileResponse:
    root_path = request.scope.get("root_path", "")
    docs_root = _docs_root(root_path)
    for candidate in _candidate_paths(raw_path, root_path):
        if candidate.exists() and candidate.is_file():
            media_type = None
            if candidate.suffix == ".html":
                media_type = "text/html; charset=utf-8"
            response = FileResponse(str(candidate), media_type=media_type)
            response.headers["Cache-Control"] = "no-store" if candidate.suffix == ".html" else "public, max-age=3600"
            response.headers["X-QYM-Docs-Root"] = request.scope.get("root_path", "")
            return response
    return FileResponse(str(docs_root / "index.html"), media_type="text/html; charset=utf-8")
