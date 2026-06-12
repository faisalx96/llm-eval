from __future__ import annotations

from pathlib import Path
from typing import Iterable

from fastapi import Request
from fastapi.responses import FileResponse, Response


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


def _looks_like_asset_path(raw_path: str) -> bool:
    suffix = Path(raw_path.strip("/")).suffix.lower()
    return bool(suffix) and suffix not in {".html", ".htm"}


def _is_unsafe_request_path(raw_path: str) -> bool:
    if "\\" in raw_path or "\x00" in raw_path:
        return True
    if raw_path.startswith("/"):
        return True
    candidate = Path(raw_path.strip("/"))
    if candidate.is_absolute() or candidate.drive:
        return True
    return any(part == ".." for part in candidate.parts)


def _contained(candidate: Path, root: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _candidate_paths(raw_path: str, root_path: str = "", *, include_spa_fallback: bool = True) -> Iterable[Path]:
    if _is_unsafe_request_path(raw_path):
        return
    docs_root = _docs_root(root_path)
    for candidate in _unchecked_candidate_paths(docs_root, raw_path, include_spa_fallback=include_spa_fallback):
        if _contained(candidate, docs_root):
            yield candidate


def _unchecked_candidate_paths(docs_root: Path, raw_path: str, *, include_spa_fallback: bool = True) -> Iterable[Path]:
    if not raw_path or raw_path == ".":
        yield docs_root / "index.html"
        return

    cleaned = raw_path.strip("/")
    parts = Path(cleaned).parts
    if "assets" in parts:
        asset_index = parts.index("assets")
        yield (docs_root / Path(*parts[asset_index:])).resolve()

    target = (docs_root / cleaned).resolve()
    if not _contained(target, docs_root):
        if include_spa_fallback:
            yield docs_root / "index.html"
        return

    if target.is_dir():
        yield target / "index.html"
    yield target
    yield target / "index.html"
    if _looks_like_asset_path(cleaned):
        yield docs_root / Path(cleaned).name
    if include_spa_fallback:
        yield docs_root / "index.html"


def docs_file_response(request: Request, raw_path: str = "") -> FileResponse | Response:
    root_path = request.scope.get("root_path", "")
    docs_root = _docs_root(root_path)
    if _is_unsafe_request_path(raw_path):
        return Response(status_code=404)
    is_asset_request = _looks_like_asset_path(raw_path)
    for candidate in _candidate_paths(raw_path, root_path, include_spa_fallback=not is_asset_request):
        if candidate.exists() and candidate.is_file():
            media_type = None
            if candidate.suffix == ".html":
                media_type = "text/html; charset=utf-8"
            response = FileResponse(str(candidate), media_type=media_type)
            unversioned_portal_asset = candidate.name in {"portal.css", "portal.js", "portal-data.json", "index.html"}
            response.headers["Cache-Control"] = "no-store" if candidate.suffix == ".html" or unversioned_portal_asset else "public, max-age=3600"
            response.headers["X-QYM-Docs-Root"] = request.scope.get("root_path", "")
            return response
    if is_asset_request:
        return Response(status_code=404)
    return FileResponse(str(docs_root / "index.html"), media_type="text/html; charset=utf-8")
