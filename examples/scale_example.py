import asyncio
from typing import Dict, Any
from llm_eval.core.evaluator import Evaluator

def response_length_check(output, expected):
    return 1.0 if len(str(output)) > 0 else 0.0

# 1. Define your tasks (or import them)
async def task_1(question: str, trace: Any = None, model_name: str = "gpt-4o-mini") -> str:
    """Simulate Task 1"""
    await asyncio.sleep(0.5)
    return f"Task 1 result for {question} using {model_name}"

async def task_2(question: str, trace: Any = None, model_name: str = "gpt-4o-mini") -> str:
    """Simulate Task 2"""
    await asyncio.sleep(2)
    return f"Task 2 result for {question} using {model_name}"

# ... define other tasks ...

def main():
    # 2. Define the list of models you want to run against
    models = [
        "gpt-4o",
        "llama-3.1",
        "gemini-pro"
    ]

    # 3. Define the configurations for each task
    # You can specify different datasets, metrics, or configs for each task
    runs_config = [
        {
            "name": "Task 1 Analysis",
            "task": task_1,
            "dataset": "saudi-qa-verification-v1", # Replace with your dataset
            "metrics": ["exact_match"],
            "models": models, # Pass the list of 6 models here
            "config": {"max_concurrency": 5}
        },
        {
            "name": "Task 2 Summary",
            "task": task_2,
            "dataset": "saudi-qa-verification-v1",
            "metrics": [response_length_check],
            "models": models,
            "config": {"max_concurrency": 5}
        },
        # ... add configs for Task 3, 4, 5 ...
    ]

    # 4. Run everything in parallel
    # Evaluator.run_parallel will expand the 'models' list into individual runs
    # Total runs = (Tasks) * (Models)
    print(f"Starting {len(runs_config) * len(models)} evaluations...")
    
    results = Evaluator.run_parallel(
        runs=runs_config,
        show_tui=True,
        auto_save=True
    )

    print("All evaluations complete!")

if __name__ == "__main__":
    # Mock metric for the example to run without imports if needed
    main()
