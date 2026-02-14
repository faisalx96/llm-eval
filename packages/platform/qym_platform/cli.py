from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("QYM_PLATFORM_HOST", "0.0.0.0")
    port = int(os.environ.get("QYM_PLATFORM_PORT", "8000"))
    uvicorn.run("qym_platform.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()


