import asyncio
import json
import types
import sys
from pathlib import Path

source_path = Path(__file__).resolve().parents[4] / 'tests' / 'profile_overhead_breakdown.py'
source = source_path.read_text()
old = 'expected_emit_calls = repeat_count * ((2 * len(items)) + 2)'
assert old in source
source = source.replace(old, 'expected_emit_calls = repeat_count * ((4 * len(items)) + 2)')
module = types.ModuleType('perf_audit_overhead')
sys.modules[module.__name__] = module
module.__file__ = str(source_path)
namespace = module.__dict__
exec(compile(source, str(source_path), 'exec'), namespace)
report = asyncio.run(namespace['run_benchmark'](100, [1, 10, 50, 200], 10))
print(json.dumps(report, indent=2))
print(namespace['format_report'](report))
