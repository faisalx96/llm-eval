from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="llm-eval",
    version="0.3.0",
    author="Faisal Bin Hussein",
    author_email="faisalx96@yahoo.com",
    description="UI-first LLM evaluation platform with powerful comparison and analysis tools, built on Langfuse",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/faisalx96/llm-eval",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.9",
    install_requires=[
        "langfuse>=2.0.0",
        "pydantic>=2.0.0",
        "rich>=13.0.0",  # For nice progress bars
        "aiohttp>=3.8.0",  # For async HTTP
        "python-dotenv>=0.19.0",  # For environment variables
        "nest_asyncio>=1.5.0",  # For Jupyter notebook compatibility
        "openpyxl>=3.0.0",  # For Excel export functionality
        "sqlalchemy>=2.0.0",  # Database ORM
        "click>=8.0.0",  # CLI framework
        "fastapi>=0.104.0",  # REST API framework
        "uvicorn>=0.24.0",  # ASGI server
        "websockets>=12.0",  # WebSocket support
        "requests>=2.28.0",  # HTTP library for CLI
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "pytest-xdist>=3.0.0",
            "pytest-timeout>=2.1.0",
            "pytest-mock>=3.10.0",
            "black>=22.0.0",
            "isort>=5.10.0",
            "mypy>=1.0.0",
            "psutil>=5.9.0",
            "flake8>=6.0.0",
            "bandit>=1.7.5",
            "safety>=2.3.0",
            "coverage>=7.0.0",
            "jupyter>=1.0.0",
            "psutil>=5.9.0",  # For performance monitoring
            "jsonschema>=4.17.0",  # For validation testing
        ],
        "viz": [
            "plotly>=5.0.0",  # Interactive charts
            "pandas>=1.5.0",  # Enhanced data handling
            "numpy>=1.20.0",  # Numerical computations
            "kaleido>=0.2.1",  # Static image export
        ],
        "deepeval": ["deepeval>=0.20.0"],  # For advanced evaluation metrics
        "langchain": ["langchain>=0.1.0"],
        "langgraph": ["langgraph>=0.0.40", "langchain>=0.1.0", "openai>=1.0.0", "tavily-python>=0.3.0"],
        "openai": ["openai>=1.0.0"],
        "postgres": [
            "psycopg2-binary>=2.9.0",  # PostgreSQL adapter
        ],
        "all": [
            "deepeval>=0.20.0", "langchain>=0.1.0", "openai>=1.0.0",
            "plotly>=5.0.0", "pandas>=1.5.0", "numpy>=1.20.0", "kaleido>=0.2.1",
            "psycopg2-binary>=2.9.0"
        ],  # All optional dependencies
    },
    entry_points={
        "console_scripts": [
            "llm-eval=llm_eval.cli:cli_main",
        ],
    },
)
