"""Test task functions for consistent testing."""

import asyncio
import random
import time
from typing import Any, Dict


def echo_task(input_text: str) -> str:
    """Simple echo task that returns input with prefix."""
    return f"Echo: {input_text}"


def uppercase_task(input_text: str) -> str:
    """Task that converts input to uppercase."""
    return str(input_text).upper()


def reverse_task(input_text: str) -> str:
    """Task that reverses the input text."""
    return str(input_text)[::-1]


def sentiment_task(input_text: str) -> str:
    """Mock sentiment analysis task."""
    text = str(input_text).lower()

    positive_words = [
        "love",
        "great",
        "excellent",
        "amazing",
        "wonderful",
        "outstanding",
    ]
    negative_words = ["hate", "terrible", "awful", "bad", "horrible", "waste"]

    positive_count = sum(1 for word in positive_words if word in text)
    negative_count = sum(1 for word in negative_words if word in text)

    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"


def classification_task(input_text: str) -> str:
    """Mock text classification task."""
    text = str(input_text).lower()

    categories = {
        "technology": ["iphone", "camera", "battery", "tech", "computer", "software"],
        "sports": ["game", "team", "player", "win", "score", "basketball", "football"],
        "finance": ["stock", "market", "investor", "money", "price", "financial"],
        "health": ["medical", "treatment", "doctor", "patient", "research", "cancer"],
        "environment": ["climate", "environmental", "green", "pollution", "earth"],
    }

    for category, keywords in categories.items():
        if any(keyword in text for keyword in keywords):
            return category

    return "other"


def qa_task(input_text: str) -> str:
    """Mock question-answering task with predefined answers."""
    text = str(input_text).lower()

    qa_pairs = {
        "capital of france": "Paris",
        "2 + 2": "4",
        "romeo and juliet": "William Shakespeare",
        "chemical formula for water": "H2O",
        "world war ii end": "1945",
    }

    for question_part, answer in qa_pairs.items():
        if question_part in text:
            return answer

    return "I don't know the answer to that question."


def slow_task(input_text: str) -> str:
    """Task that takes some time to complete (for performance testing)."""
    time.sleep(0.1)  # 100ms delay
    return f"Processed: {input_text}"


async def async_task(input_text: str) -> str:
    """Async version of a task."""
    await asyncio.sleep(0.01)  # 10ms delay
    return f"Async result: {input_text}"


def error_task(input_text: str) -> str:
    """Task that always raises an error."""
    raise ValueError(f"Error processing: {input_text}")


def random_task(input_text: str) -> str:
    """Task with random behavior (for testing consistency)."""
    if random.random() < 0.1:  # 10% chance of error
        raise RuntimeError("Random error occurred")

    responses = [
        f"Response A: {input_text}",
        f"Response B: {input_text}",
        f"Response C: {input_text}",
    ]

    return random.choice(responses)


def variable_time_task(input_text: str) -> str:
    """Task with variable execution time."""
    delay = random.uniform(0.01, 0.1)  # 10-100ms
    time.sleep(delay)
    return f"Variable time result: {input_text} (took {delay:.3f}s)"


def memory_intensive_task(input_text: str) -> str:
    """Task that uses more memory (for memory testing)."""
    # Create a large string
    large_data = "x" * 10000  # 10KB string
    processed = f"{large_data}:{input_text}:{large_data}"

    # Return just the input part
    return f"Memory intensive result: {input_text}"


def code_generation_task(input_text: str) -> str:
    """Mock code generation task."""
    text = str(input_text).lower()

    if "factorial" in text:
        return """def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)"""

    elif "reverse" in text and "string" in text:
        return """def reverse_string(s):
    return s[::-1]"""

    elif "prime" in text:
        return """def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True"""

    else:
        return f"# Generated code for: {input_text}\npass"


def summarization_task(input_text: str) -> str:
    """Mock text summarization task."""
    text = str(input_text)

    # Simple extractive summarization - take first and last sentences
    sentences = text.split(".")
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 2:
        return text

    summary = f"{sentences[0]}. {sentences[-1]}."

    # Ensure it's shorter than original
    if len(summary) >= len(text):
        words = text.split()
        if len(words) > 10:
            summary = " ".join(words[:10]) + "..."

    return summary


# Task registry for easy access in tests
TASK_REGISTRY = {
    "echo": echo_task,
    "uppercase": uppercase_task,
    "reverse": reverse_task,
    "sentiment": sentiment_task,
    "classification": classification_task,
    "qa": qa_task,
    "slow": slow_task,
    "async": async_task,
    "error": error_task,
    "random": random_task,
    "variable_time": variable_time_task,
    "memory_intensive": memory_intensive_task,
    "code_generation": code_generation_task,
    "summarization": summarization_task,
}


def get_task(task_name: str):
    """Get a task function by name."""
    if task_name not in TASK_REGISTRY:
        raise ValueError(
            f"Unknown task: {task_name}. Available tasks: {list(TASK_REGISTRY.keys())}"
        )

    return TASK_REGISTRY[task_name]


def list_tasks():
    """List all available test tasks."""
    return list(TASK_REGISTRY.keys())


# Performance testing utilities
class TaskPerformanceMonitor:
    """Monitor task performance for benchmarking."""

    def __init__(self):
        self.execution_times = []
        self.memory_usage = []

    def run_task_with_monitoring(self, task_func, input_data, iterations=10):
        """Run a task multiple times and collect performance metrics."""
        import time

        import psutil

        process = psutil.Process()

        for _ in range(iterations):
            start_memory = process.memory_info().rss / 1024 / 1024  # MB
            start_time = time.time()

            try:
                result = task_func(input_data)
                success = True
            except Exception as e:
                result = str(e)
                success = False

            end_time = time.time()
            end_memory = process.memory_info().rss / 1024 / 1024  # MB

            self.execution_times.append(end_time - start_time)
            self.memory_usage.append(end_memory - start_memory)

        return {
            "avg_time": sum(self.execution_times) / len(self.execution_times),
            "min_time": min(self.execution_times),
            "max_time": max(self.execution_times),
            "avg_memory": sum(self.memory_usage) / len(self.memory_usage),
            "success_rate": success,
            "iterations": iterations,
        }
