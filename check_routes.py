#!/usr/bin/env python
"""Check all registered routes in FastAPI app"""

import sys
sys.path.append('.')
from llm_eval.api.main import app

print("=== Registered Routes ===\n")

for route in app.routes:
    if hasattr(route, 'path'):
        methods = getattr(route, 'methods', [])
        if methods:
            print(f"{', '.join(methods):8} {route.path}")
            
print("\n=== Template Related Routes ===\n")
for route in app.routes:
    if hasattr(route, 'path') and 'template' in route.path.lower():
        methods = getattr(route, 'methods', [])
        if methods:
            print(f"{', '.join(methods):8} {route.path}")