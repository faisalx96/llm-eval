# LLM-Eval Framework Project Instructions

## Project Overview
We are building a **UI-first LLM/agent evaluation platform** targeting **technical developers** who need to streamline and automate the evaluation phase of their LLM and agentic products. The platform uses Langfuse as its backbone and focuses on transitioning developers from code-based evaluation to UI-driven evaluation with powerful comparison and analysis tools.

## Current State (Post-Sprint 2)
✅ **Sprint 1 Complete:**
- Template system for quick evaluation setup
- Workflow automation from setup to reporting  
- Professional visualization and reporting system
- Excel integration with embedded charts
- Search/filtering capabilities
- Rich console UI with progress tracking

✅ **Sprint 2 (80% Complete):**
- Database storage infrastructure (SQLAlchemy)
- REST API server (FastAPI) 
- Web dashboard (Next.js/React)
- WebSocket real-time updates
- Basic run listing and filtering
- Fixed critical bugs (redirect loops, UUID issues)

🎯 **Sprint 2.5 (Active):**
- Production readiness and polish
- Complete test coverage (target: 80%)
- Performance optimization for 1000+ runs
- Documentation and deployment guides
- CI/CD pipeline setup

## Target Users & Vision
**Primary:** Technical developers building LLM applications
**Secondary:** ML engineers, DevOps teams running evaluation pipelines

**Current State → Target State:**
- **FROM**: Developers write code to run evaluations
- **TO**: Developers use UI to configure, run, and analyze evaluations

**Core Use Cases:**
1. **UI-Driven Evaluation**: Configure and run evaluations through web interface
2. **Run Comparison & Analysis**: Compare evaluation runs with detailed diff views
3. **Historical Analysis**: Track performance trends across runs and time
4. **Interactive Debugging**: Drill down into failures and patterns through UI
5. **CI/CD Integration**: Automated evaluation with UI-based result analysis

## Key Project Guidelines

### 1. Developer-First Design
- **API Simplicity**: Users provide only task, dataset reference, and metrics
- **Quick Setup**: From installation to first evaluation in under 5 minutes
- **Clear Feedback**: Rich progress indicators and actionable error messages
- **Integration-Ready**: Works with existing LangChain, LangGraph, and custom setups

### 2. Documentation Standards
- **ROADMAP.md**: Elevated 16-week plan with clear milestones
- **TASK_LIST.md**: 190+ tasks tracked with sprint assignments
- **DEPLOYMENT_GUIDE.md**: Production deployment instructions
- **TESTING_GUIDE.md**: Comprehensive testing strategy
- **DEVELOPER_GUIDE.md**: Technical implementation details
- **TROUBLESHOOTING.md**: Common issues and solutions

### 3. Code Quality Standards
- Production-ready code without conversational artifacts
- Clear error messages that guide developers to solutions
- Async-first design for performance at scale
- Comprehensive logging for debugging evaluation issues
- Test coverage target: 80% minimum

### 4. Technical Architecture
- **Langfuse-Centric**: All evaluation infrastructure built on Langfuse
- **Dataset Requirements**: Must read from Langfuse (no local files)
- **Tracing**: All evaluation traces logged to Langfuse
- **Storage**: SQLAlchemy with PostgreSQL for production
- **API**: FastAPI with WebSocket support
- **Frontend**: Next.js with TypeScript
- **Performance**: Async operations and parallel processing
- **Flexibility**: Support for custom metrics and evaluation patterns

## Sprint Plan Summary

### Sprint 2.5: Polish & Production (2 weeks - ACTIVE)
**Week 1 Focus:**
- [ ] SPRINT25-001: Complete run detail page
- [ ] SPRINT25-002: Finish comparison API
- [ ] SPRINT25-005: Add database indexes
- [ ] SPRINT25-007: Fix WebSocket memory leaks

**Week 2 Focus:**
- [ ] SPRINT25-009: Unit test coverage (80%)
- [ ] SPRINT25-015: Deployment documentation
- [ ] SPRINT25-018: CI/CD pipeline
- [ ] SPRINT25-021: Update README

### Sprint 3: UI-Driven Evaluation (3 weeks)
- Evaluation configuration UI
- Execution control center
- Results analysis suite
- Real-time monitoring

### Sprint 4: Intelligence Layer (3 weeks)
- AI-powered metric recommendations
- Automatic failure categorization
- Advanced metrics (hallucination, bias detection)
- Statistical analysis tools

### Sprint 5: Enterprise Features (4 weeks)
- Authentication & authorization
- Team collaboration
- PostgreSQL optimization
- Kubernetes deployment

### Sprint 6: Platform Ecosystem (4 weeks)
- Plugin architecture
- Integration hub (LangChain, MLflow, etc.)
- Community features
- Developer portal

## Development Principles

### UI-First Philosophy
- **Phase 1**: Code-based evaluation with rich reporting ✅
- **Phase 2**: UI-driven evaluation configuration and execution 🎯
- **Phase 3**: Full platform with comparison, analysis, and collaboration
- **End Goal**: 80% of evaluations run from UI, not code

### Performance Targets
- API response time < 100ms (p95)
- Dashboard load time < 2 seconds
- Support 1000+ concurrent runs
- Handle 10,000+ stored runs per project

### Quality Standards
- 80%+ test coverage
- Zero critical bugs in production
- <1% error rate in production
- All features documented

## Commands to Run
```bash
# Development setup
pip install -e .
pip install -e ".[dev]"

# Run tests
pytest tests/
pytest --cov=llm_eval --cov-report=html

# Start services
python -m llm_eval.api.main          # API server
cd frontend && npm run dev            # Frontend

# Run full evaluation workflow
python examples/sprint1_complete_workflow.py

# Linting and formatting
black llm_eval/
flake8 llm_eval/
mypy llm_eval/
```

## Key Technical Decisions

### Storage Strategy
- **Development**: SQLite for simplicity
- **Production**: PostgreSQL with connection pooling
- **Caching**: Redis for performance
- **File Storage**: S3/GCS for large results

### API Design
- RESTful endpoints for CRUD operations
- WebSocket for real-time updates
- GraphQL planned for Sprint 6
- API versioning from Sprint 2.5

### Frontend Architecture
- Next.js for SSR and performance
- TypeScript for type safety
- Tailwind CSS for styling
- React Query for data fetching
- WebSocket hooks for real-time updates

### Testing Strategy
- Unit tests: 70% of tests
- Integration tests: 25% of tests
- E2E tests: 5% of tests
- Performance tests for critical paths
- Load testing for 1000+ concurrent users

## Success Metrics

### Technical KPIs
- API response time < 100ms
- Test coverage > 80%
- Build time < 5 minutes
- Zero downtime deployments

### User Experience KPIs
- Setup to first eval < 5 minutes
- UI vs code usage: 80/20
- Error rate < 1%
- User satisfaction > 4.5/5

### Business KPIs (Target Q3 2025)
- 1000+ active users
- 10+ enterprise customers
- 500+ GitHub stars
- 10,000+ monthly evaluations

## Current Focus Areas

### Immediate Priorities (Sprint 2.5 Week 1)
1. Complete run detail page implementation
2. Finish comparison API and UI
3. Add database performance indexes
4. Fix WebSocket memory leaks

### Next Week (Sprint 2.5 Week 2)
1. Achieve 80% test coverage
2. Set up CI/CD pipeline
3. Create deployment documentation
4. Performance testing

## Resources & References
- **Langfuse Docs**: https://langfuse.com/docs (Focus: Datasets, Evaluations, Scoring, Tracing)
- **DeepEval Integration**: For advanced metrics and evaluation patterns
- **FastAPI**: https://fastapi.tiangolo.com/
- **Next.js**: https://nextjs.org/docs
- **SQLAlchemy**: https://docs.sqlalchemy.org/

## Important Notes
- All datasets MUST be stored in Langfuse (no local files)
- Framework should auto-detect and wrap non-traced tasks
- Prioritize simplicity - users provide only: task, dataset name, metrics
- Support both sync and async evaluation patterns
- Handle errors gracefully with partial results
- Maintain backward compatibility with Sprint 1 features

## Contact & Support
- **GitHub Issues**: Report bugs and feature requests
- **Documentation**: See /docs folder for detailed guides
- **Examples**: Check /examples for usage patterns

---

**Last Updated**: January 2025  
**Current Version**: v0.2.5 (Sprint 2.5 Active)  
**Next Milestone**: Production Ready (2 weeks)