# LLM Evaluation Framework Requirements

## Overview
An automated LLM/agent evaluation framework built on top of Langfuse, designed to be simple, generalized, and production-ready.

## Core Requirements

### 1. Simplicity
- **Minimal user work**: Users only provide task, dataset reference, and metrics
- **Easy to use API**: Simple, declarative interface
- **Developer friendly**: Clear error messages, good defaults

### 2. Generalization
- Support any LLM task evaluation:
  - Prompts
  - Functions
  - Agents
  - Full applications
- Framework agnostic: Works with LangChain, LangGraph, OpenAI, etc.

### 3. Langfuse Integration (CORE)
- **Langfuse as backbone**: All evaluation infrastructure built on Langfuse
- **Assumptions**:
  - Users' agents already have Langfuse tracing enabled
  - Some tasks might not have tracing (we need to handle this)
- **Requirements**:
  - Log ALL evaluation traces to Langfuse
  - Read ALL datasets from Langfuse (no local files for now)
  - Utilize Langfuse's evaluation features fully

### 4. User Inputs
Users provide only:
1. **Task**: The LLM function/agent/chain to evaluate
2. **Dataset**: Reference to dataset in Langfuse
3. **Metrics**: List of metrics to apply

## Technical Requirements

### Framework Design
- Python library (not just templates)
- Async support for parallel evaluation
- Retry mechanisms for failed evaluations
- Progress tracking and reporting

### Integration Requirements
- Auto-detect task types (function, chain, agent)
- Seamless integration with existing Langfuse traces
- Add tracing to tasks that don't have it

### Production Readiness
- Error handling and recovery
- Performance optimization (parallel execution)
- Observability (all runs tracked in Langfuse)
- No focus on perfection - prioritize "good and working"

## Out of Scope (for now)
- Local dataset files (only Langfuse datasets)
- Complex UI (CLI/library only)
- Custom storage backends (only Langfuse)

## Success Criteria
1. User can evaluate any LLM task with 3-5 lines of code
2. All evaluation data visible in Langfuse
3. Works with major LLM frameworks out of the box
4. Clear documentation and examples
5. Simple, friendly user guide that makes evaluation accessible to everyone

## Documentation Requirements
- **User Guide**: Simple, friendly guide showing how to use the framework
- **API Reference**: Technical documentation for advanced users
- **Examples**: Jupyter notebooks with real-world scenarios
- **Quick Start**: Get users running in under 5 minutes

---
**Note**: This document should be updated as requirements evolve throughout the project.