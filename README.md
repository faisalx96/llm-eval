# LLM-Eval: UI-First Evaluation Platform

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Transform from code-based to UI-first LLM evaluation! Built on [Langfuse](https://langfuse.com) with a powerful web dashboard for managing and analyzing evaluation runs.

## 🚀 Quick Start

### 1. Install
```bash
pip install -e .
```

### 2. Basic Evaluation (Memory Only)
```python
from llm_eval import Evaluator

evaluator = Evaluator(
    task=your_llm_function,
    dataset="your-langfuse-dataset",  
    metrics=["exact_match", "f1_score"]
)

results = evaluator.run()
```

### 3. UI-First Evaluation (NEW!)
```python
evaluator = Evaluator(
    task=your_llm_function,
    dataset="your-langfuse-dataset",
    metrics=["exact_match", "f1_score"],
    config={"project_id": "my-project"}  # ← This enables UI storage!
)

results = evaluator.run()
```

### 4. Launch Dashboard
```bash
# Terminal 1: Start API
python -m llm_eval.api.main

# Terminal 2: Start Frontend  
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