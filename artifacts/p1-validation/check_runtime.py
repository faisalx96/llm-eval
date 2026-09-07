"""Verify packaged changed source/assets against the reviewed worktree."""

import hashlib
import json
from pathlib import Path

import qym
import qym_platform

manifest = json.loads(Path(__file__).with_name("runtime-manifest.json").read_text())
roots = {
    "packages/sdk/qym/": Path(qym.__file__).parent,
    "packages/platform/qym_platform/": Path(qym_platform.__file__).parent,
}
for relative, expected in manifest.items():
    for prefix, root in roots.items():
        if relative.startswith(prefix):
            file = root / relative[len(prefix):]
            assert hashlib.sha256(file.read_bytes()).hexdigest() == expected, relative
            break
print(json.dumps({"packaged_changed_files_verified": len(manifest)}))
