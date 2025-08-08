# LLM-Eval: Local UI-First Evaluation Platform

[![CI/CD Pipeline](https://github.com/faisalx96/llm-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/faisalx96/llm-eval/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**🏠 A local, privacy-first LLM evaluation tool with a beautiful UI. No cloud, no servers - runs entirely on your machine.**

Transform from code-based to UI-first LLM evaluation! Built on [Langfuse](https://langfuse.com) with a powerful web dashboard for managing and analyzing evaluation runs locally.

## 🚀 Quick Start (One Command!)

```bash
# Install
pip install llm-eval

# Start everything with one command!
llm-eval start

# Open http://localhost:3000 - That's it!
```

### What happens:
1. Checks for Docker (offers to help install if missing)
2. Creates .env file from template (if needed)
3. Starts API and Frontend in Docker containers
4. Opens your browser to the UI

### Other commands:
```bash
llm-eval status  # Check if services are running
llm-eval stop    # Stop all services
llm-eval --help  # See all available commands
```

### Basic Evaluation Example
```python
from llm_eval import Evaluator

evaluator = Evaluator(
    task=your_llm_function,
    dataset="your-langfuse-dataset",  
    metrics=["exact_match", "f1_score"]
)

results = evaluator.run()
```

### UI-First Evaluation (Saves to Local Database)
```python
evaluator = Evaluator(
    task=your_llm_function,
    dataset="your-langfuse-dataset",
    metrics=["exact_match", "f1_score"],
    config={"project_id": "my-project"}  # ← This enables UI storage!
)

results = evaluator.run()
```

### Access the Dashboard
```bash
# Everything runs locally at:
http://localhost:3000   # Frontend UI
http://localhost:8000   # API (if needed)
python -m llm_eval.api.main

# Terminal 2: Start Frontend (localhost:3000)  
cd frontend && npm run dev

# Visit: http://localhost:3000
```

## ✨ What You Get

**Just add `config={'project_id': 'your-project'}` and unlock:**

- 🗄️ **Database Storage** - Results automatically saved
- 🖥️ **Web Dashboard** - Browse and manage runs  
- 🔍 **Run Comparison** - Side-by-side analysis
- 📊 **Visualizations** - Charts and reports
- 🔄 **Real-time Updates** - Live progress tracking
- 📤 **Export Tools** - Excel, CSV, JSON formats

## 📋 Requirements

**Environment Variables:**
```bash
LANGFUSE_SECRET_KEY="your_secret_key"
LANGFUSE_PUBLIC_KEY="your_public_key" 
LANGFUSE_HOST="https://cloud.langfuse.com"
```

**Dependencies:**
```bash
# Core functionality
pip install langfuse deepeval rich

# Visualization features
pip install plotly openpyxl pandas

# Web dashboard
cd frontend && npm install
```

## 📚 Documentation

- **[Quick Start Guide](docs/USER_GUIDE.md)** - Get started in 5 minutes
- **[Developer Guide](docs/DEVELOPER_GUIDE.md)** - Technical implementation details
- **[API Reference](docs/API_REFERENCE.md)** - REST API documentation
- **[Deployment Guide](docs/DEPLOYMENT_GUIDE.md)** - Production deployment
- **[Testing Guide](docs/TESTING_GUIDE.md)** - Testing strategy and examples
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions
- **[Project Roadmap](docs/ROADMAP.md)** - Development plan and milestones

## 🛠️ Development

```bash
# Setup
pip install -e .
pip install -e ".[dev]"

# Run tests
pytest tests/

# Start development servers
python -m llm_eval.api.main          # API server
cd frontend && npm run dev            # Frontend dev server
```

## 🎯 Architecture

```
LLM-Eval Platform
├── Core Library (Python)           # Evaluation engine
├── REST API (FastAPI)             # Run management
├── Web Dashboard (Next.js)        # UI-first interface  
├── Database (SQLite/PostgreSQL)   # Run storage
└── Langfuse Integration           # Dataset & tracing
```

## 📈 Roadmap

- **Sprint 1** ✅ - Template system, smart search, Excel reports
- **Sprint 2** ✅ - Web dashboard, database storage, run comparison  
- **Sprint 3** 🚧 - UI-driven evaluation, advanced analytics
- **Sprint 4** 📋 - A/B testing, CI/CD integration, collaboration

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open pull request

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

**Transform your LLM evaluation workflow from code-heavy to UI-first!** 🚀