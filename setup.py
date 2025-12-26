from setuptools import setup, find_packages
import re

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("llm_eval/__init__.py", "r", encoding="utf-8") as f:
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M)
    if version_match:
        version = version_match.group(1)
    else:
        raise RuntimeError("Unable to find version string in llm_eval/__init__.py")

setup(
    name="llm-eval",
    version=version,
    author="Faisal Bin Hussein",
    author_email="faisalx96@yahoo.com",
    description="Simple, automated LLM evaluation framework built on Langfuse",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/faisalx96/llm-eval",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "llm_eval": [
            "_static/ui/*",
            "_static/dashboard/*",
        ],
    },
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
        "pydantic-settings>=2.0.0",
        "rich>=13.0.0",  # For nice progress bars
        "python-dotenv>=0.19.0",  # For environment variables
        "openpyxl>=3.0.0",  # For Excel export
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=22.0.0",
            "isort>=5.10.0",
            "mypy>=1.0.0",
            "jupyter>=1.0.0",
        ],
        "deepeval": ["deepeval>=0.20.0"],  # For advanced evaluation metrics
        "langchain": ["langchain>=0.1.0"],
        "langgraph": ["langgraph>=0.0.40", "langchain>=0.1.0", "openai>=1.0.0", "tavily-python>=0.3.0"],
        "openai": ["openai>=1.0.0"],
        "platform": [
            "fastapi>=0.110.0",
            "uvicorn>=0.30.0",
            "sqlalchemy>=2.0.0",
            "alembic>=1.13.0",
            "psycopg2-binary>=2.9.0",
            "python-multipart>=0.0.9",
            "httpx>=0.27.0",
        ],
        "all": ["deepeval>=0.20.0", "langchain>=0.1.0", "openai>=1.0.0"],
    },
    entry_points={
        "console_scripts": [
            "llm-eval=llm_eval.cli:main",
            "llm-eval-platform=llm_eval_platform.cli:main",
        ],
    },
)
