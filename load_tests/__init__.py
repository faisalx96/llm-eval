# Load testing suite for LLM-Eval platform
"""
Load testing suite to validate system performance under high concurrent load.

This package contains comprehensive load tests for:
- API endpoints (CRUD operations on runs)
- WebSocket connections (real-time updates)
- Database performance (1000+ runs)
- Frontend interactions

Performance targets:
- API response time < 500ms (p95) under load
- WebSocket message delivery < 100ms
- Database queries < 200ms
- No memory leaks during extended runs
- System stable with 1000+ stored runs
"""