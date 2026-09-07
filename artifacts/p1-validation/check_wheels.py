"""Verify clean package boundaries and source fidelity, including repeat builds."""

import json
import sys
from pathlib import Path
from zipfile import ZipFile

results = []
for filename in sys.argv[1:]:
    wheel = Path(filename)
    platform = wheel.name.startswith("qym_platform-")
    package = "qym_platform" if platform else "qym"
    source = Path("packages") / ("platform" if platform else "sdk") / package
    expected = {str(path.relative_to(source)): path for path in source.rglob("*.py")}
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        unexpected = [name for name in names if not name.startswith(package + "/") and ".dist-info/" not in name]
        assert not unexpected, (filename, unexpected)
        actual = {name[len(package) + 1:] for name in names if name.startswith(package + "/") and name.endswith(".py")}
        assert actual == set(expected), (filename, actual - set(expected), set(expected) - actual)
        for relative, path in expected.items():
            assert archive.read(package + "/" + relative) == path.read_bytes(), relative
        if platform:
            for asset in ["run_details.js", "dashboard.js", "run.html", "compare.html", "overview.html", "metrics.js"]:
                relative = "_static/dashboard/" + asset
                assert archive.read(package + "/" + relative) == (source / relative).read_bytes(), asset
        results.append({"wheel": wheel.name, "python_files": len(expected), "source_matches": True, "no_stale_or_nested_build_modules": True})
assert len(results) == 2, "Pass the SDK and platform wheels"
print(json.dumps(results, indent=2))
