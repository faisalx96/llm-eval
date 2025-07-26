# LLM Evaluation Framework Project Instructions

## Project Overview
We are building an automated LLM/agent evaluation framework that uses Langfuse as its backbone. The framework should be simple, generalized, and production-ready.

## Key Project Guidelines

### 1. Always Update Documentation
- **IMPORTANT**: Always update `REQUIREMENTS.md` when requirements change or evolve
- Keep `LANGFUSE_GUIDE.md` updated with new findings about Langfuse usage
- Document all design decisions and trade-offs

### 2. Code Quality Standards
- **Keep repository professional**: Never add comments or explanations from conversations
- All code should be production-ready without conversational context
- Comments should explain code purpose, not development discussions

### 3. Core Principles
- **Simplicity first**: Users should only provide task, dataset reference, and metrics
- **Langfuse-centric**: All evaluation infrastructure built on Langfuse
- **Production-ready**: Focus on working solution, not perfection

### 4. Technical Constraints
- Datasets MUST be read from Langfuse (no local files)
- ALL evaluation traces MUST be logged to Langfuse
- Assume users' agents already have Langfuse tracing (but handle cases where they don't)

### 5. Development Approach
- Start with core functionality, iterate based on feedback
- Prioritize developer experience (clear APIs, good error messages)
- Test with real-world scenarios (LangChain, LangGraph, raw functions)

### 6. Architecture Notes
- Framework shape: Python library (not just templates)
- Support async operations for performance
- Auto-detect task types when possible

## Commands to Run
When changes are made, ensure to run:
- `pip install -e .` (after creating setup.py)
- Tests: TBD based on testing framework chosen
- Linting: TBD based on linting setup


## Resources
- Langfuse Docs: https://langfuse.com/docs
- Focus on: Datasets, Evaluations, Scoring, and Tracing APIs

## Project Documentation
- `REQUIREMENTS.md` - Core project requirements and constraints
- `LANGFUSE_GUIDE.md` - Comprehensive Langfuse integration patterns
- `METRICS_GUIDE.md` - Common evaluation metrics and implementations
- `ERROR_HANDLING_GUIDE.md` - Error scenarios and recovery strategies

## Important Notes
- All datasets MUST be stored in Langfuse (no local files)
- Framework should auto-detect and wrap non-traced tasks
- Prioritize simplicity - users provide only: task, dataset name, metrics
- Support both sync and async evaluation patterns
- Handle errors gracefully with partial results