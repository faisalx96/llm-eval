# Installation Guide - LLM-Eval

**LLM-Eval is a LOCAL tool that runs on your machine. No cloud deployment needed.**

## 🚀 Quick Start (2 minutes)

### Option 1: Install from PyPI (Recommended)
```bash
# Install the package
pip install llm-eval

# Start the application
llm-eval start

# Open your browser to http://localhost:3000
```

### Option 2: Install from Source
```bash
# Clone the repository
git clone https://github.com/yourusername/llm-eval.git
cd llm-eval

# Install dependencies
pip install -e .

# Start the application
llm-eval start

# Open your browser to http://localhost:3000
```

## 📋 Prerequisites

- Python 3.9 or higher
- Node.js 18+ (for frontend development only)
- 4GB RAM minimum
- 1GB free disk space

## 🔧 Configuration

### Environment Variables
Create a `.env` file in your project directory:

```env
# Langfuse credentials (required)
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com  # or your instance

# Optional settings
LLM_EVAL_PORT=8000              # API port (default: 8000)
LLM_EVAL_FRONTEND_PORT=3000     # Frontend port (default: 3000)
LLM_EVAL_DB_PATH=~/.llm-eval/data.db  # SQLite database location
```

### Data Storage
All data is stored locally in `~/.llm-eval/`:
- `data.db` - SQLite database with all evaluation runs
- `exports/` - Exported reports and visualizations
- `logs/` - Application logs

## 🎯 Basic Usage

### Start the Application
```bash
# Start with default settings
llm-eval start

# Start API only (no UI)
llm-eval start --api-only

# Start with custom port
llm-eval start --port 8080
```

### Run an Evaluation
```python
from llm_eval import Evaluator

# Define your LLM task
def my_llm_task(input_text):
    # Your LLM logic here
    return "response"

# Run evaluation
evaluator = Evaluator(
    task=my_llm_task,
    dataset="your-langfuse-dataset",
    metrics=["accuracy", "latency"]
)

results = await evaluator.run()
```

### Access the UI
Open your browser to `http://localhost:3000` to:
- View evaluation history
- Compare runs side-by-side
- Analyze metrics and visualizations
- Export reports

## 🐳 Docker Option (Recommended)

Docker is already integrated into the CLI:

```bash
# Simply run (Docker will be used automatically)
llm-eval start

# Or use docker-compose directly
docker-compose up

# Access at http://localhost:3000
```

## 🛠️ Development Setup

For contributing or customizing:

```bash
# Clone and install in development mode
git clone https://github.com/yourusername/llm-eval.git
cd llm-eval
pip install -e ".[dev]"

# Install frontend dependencies
cd frontend
npm install

# Run in development mode
# Terminal 1: Backend
python -m llm_eval.api.main --reload

# Terminal 2: Frontend
cd frontend && npm run dev
```

## ❓ Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Change the port
llm-eval start --port 8001
```

**Database locked:**
```bash
# Reset the database
rm ~/.llm-eval/data.db
llm-eval init
```

**Langfuse connection error:**
- Verify your credentials in `.env`
- Check network connection
- Ensure Langfuse dataset exists

### Getting Help
- Check logs: `~/.llm-eval/logs/llm-eval.log`
- Run diagnostics: `llm-eval doctor`
- Report issues: GitHub Issues

## 🗂️ File Locations

| File Type | Location | Purpose |
|-----------|----------|---------|
| Database | `~/.llm-eval/data.db` | All evaluation data |
| Config | `~/.llm-eval/.env` | Environment variables |
| Logs | `~/.llm-eval/logs/` | Application logs |
| Exports | `~/.llm-eval/exports/` | Generated reports |

## 🔄 Updating

```bash
# Update to latest version
pip install --upgrade llm-eval

# Check version
llm-eval --version
```

## 🗑️ Uninstalling

```bash
# Remove the package
pip uninstall llm-eval

# Remove data (optional)
rm -rf ~/.llm-eval
```

## 📝 Next Steps

1. Set up your Langfuse account and create datasets
2. Start the application: `llm-eval start`
3. Run your first evaluation
4. Explore the UI at http://localhost:3000

---

**Remember:** Everything runs locally on your machine. No data leaves your computer unless you explicitly export it.