from __future__ import annotations

from fastapi import FastAPI

from qym_platform.app import create_app
from qym_platform.settings import PlatformSettings


def build_app() -> FastAPI:
    settings = PlatformSettings()
    inner = create_app(settings)

    prefix = settings.root_path.rstrip("/")
    if not prefix:
        return inner

    # Mount the real app under the prefix so the ingress path is handled.
    outer = FastAPI()
    outer.mount(prefix, inner)
    return outer


app = build_app()
