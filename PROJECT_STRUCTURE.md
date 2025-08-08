# Project Structure

```
llm-eval/
│
├── llm_eval/                 # Main Python package
│   ├── __init__.py          # Package initialization
│   ├── cli.py               # Command-line interface
│   ├── core/                # Core evaluation logic
│   │   ├── evaluator.py     # Main evaluator class
│   │   ├── results.py       # Result handling
│   │   ├── dataset.py       # Dataset management
│   │   └── search.py        # Search functionality
│   ├── api/                 # REST API (FastAPI)
│   │   ├── main.py          # API application
│   │   ├── endpoints/       # API endpoints
│   │   └── websockets.py    # WebSocket support
│   ├── storage/             # Database layer
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── repository.py    # Data access layer
│   │   └── migration.py     # Database migrations
│   ├── metrics/             # Evaluation metrics
│   │   ├── builtin.py       # Built-in metrics
│   │   └── deepeval_metrics.py  # DeepEval integration
│   ├── templates/           # Evaluation templates
│   │   ├── qa_template.py   # Q&A template
│   │   └── samples/         # Template examples
│   ├── visualizations/      # Charts and reports
│   │   ├── charts.py        # Plotly visualizations
│   │   └── excel_export.py  # Excel reporting
│   └── utils/               # Utility functions
│
├── frontend/                 # Next.js web dashboard
│   ├── app/                 # App router pages
│   │   ├── dashboard/       # Dashboard views
│   │   ├── runs/           # Run management
│   │   └── compare/        # Comparison views
│   ├── components/          # React components
│   │   ├── ui/             # UI components
│   │   └── layout/         # Layout components
│   ├── hooks/              # Custom React hooks
│   ├── lib/                # Frontend utilities
│   └── types/              # TypeScript definitions
│
├── examples/                # Usage examples
│   ├── basic_usage.py      # Simple evaluation example
│   ├── sprint1_complete_workflow.py  # Full workflow demo
│   ├── ui_dashboard_demo.py         # Dashboard features
│   ├── visualization_demo.py        # Chart examples
│   ├── storage_integration_example.py  # Database usage
│   └── websocket_demo.py           # Real-time updates
│
├── tests/                   # Test suite
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   ├── performance/        # Performance tests
│   └── fixtures/           # Test fixtures
│
├── docs/                    # Documentation
│   ├── README.md           # Main documentation
│   ├── ROADMAP.md          # Development roadmap
│   ├── TASK_LIST.md        # Sprint task tracking
│   ├── API_REFERENCE.md    # API documentation
│   ├── DEPLOYMENT_GUIDE.md # Deployment instructions
│   ├── TESTING_GUIDE.md    # Testing strategy
│   ├── DEVELOPER_GUIDE.md  # Developer documentation
│   ├── USER_GUIDE.md       # User documentation
│   ├── TROUBLESHOOTING.md  # Common issues
│   ├── PRODUCT_USAGE_GUIDE.md  # Product features
│   └── archive/            # Archived documents
│
├── scripts/                 # Utility scripts
│   └── run_tests.py        # Test runner
│
├── .github/                # GitHub configuration
│   └── workflows/          # CI/CD pipelines
│
├── setup.py                # Package installation
├── pytest.ini              # Test configuration
├── Makefile               # Build automation
├── README.md              # Project overview
├── CLAUDE.md              # Project instructions
├── .gitignore             # Git ignore rules
└── .env.example           # Environment template
```

## Directory Purpose

### Core Package (`llm_eval/`)
The main Python package containing all evaluation logic, API server, and utilities.

### Frontend (`frontend/`)
Next.js-based web dashboard for UI-first evaluation experience.

### Examples (`examples/`)
Working examples demonstrating various features and use cases.

### Tests (`tests/`)
Comprehensive test suite with unit, integration, and performance tests.

### Documentation (`docs/`)
All project documentation including guides, references, and roadmap.

### Scripts (`scripts/`)
Utility scripts for development, testing, and deployment.

## Key Files

- **setup.py**: Python package configuration and dependencies
- **pytest.ini**: Test runner configuration
- **Makefile**: Common development tasks
- **CLAUDE.md**: Project guidelines and instructions
- **.gitignore**: Files to exclude from version control
- **.env.example**: Template for environment variables

## Development Workflow

1. **Install dependencies**: `pip install -e .`
2. **Run tests**: `pytest tests/`
3. **Start API**: `python -m llm_eval.api.main`
4. **Start frontend**: `cd frontend && npm run dev`
5. **Run example**: `python examples/basic_usage.py`

## Clean Code Practices

- One module per file
- Clear naming conventions
- Type hints throughout
- Comprehensive docstrings
- Test coverage > 80%
- No duplicate code
- Organized imports