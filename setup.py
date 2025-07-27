from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="llm-eval",
    version="0.1.0",
    author="Faisal Bin Hussein",
    author_email="faisalx96@yahoo.com",
    description="Simple, automated LLM evaluation framework built on Langfuse",
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
        "all": ["deepeval>=0.20.0", "langchain>=0.1.0", "openai>=1.0.0"],  # All optional dependencies
    },
    entry_points={
        "console_scripts": [
            "llm-eval=llm_eval.cli:main",
        ],
    },
)