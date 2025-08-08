"""Base adapter interface and auto-detection logic."""

import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from langfuse import Langfuse


class TaskAdapter(ABC):
    """Base class for task adapters."""

    def __init__(self, task: Any, client: Langfuse):
        self.task = task
        self.client = client

    @abstractmethod
    async def arun(self, input_data: Any, trace: Any) -> Any:
        """Run the task asynchronously with tracing."""
        pass

    def run(self, input_data: Any, trace: Any) -> Any:
        """Run the task synchronously."""
        return asyncio.run(self.arun(input_data, trace))


class FunctionAdapter(TaskAdapter):
    """Adapter for regular Python functions."""

    async def arun(self, input_data: Any, trace: Any) -> Any:
        """Run function with proper tracing."""
        # Update trace with input
        trace.update(input=input_data)

        try:
            # Check if function is async
            if inspect.iscoroutinefunction(self.task):
                output = await self.task(input_data)
            else:
                # Run sync function in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(None, self.task, input_data)

            # Update trace with output
            trace.update(output=output)
            return output
        except Exception as e:
            # Update trace with error
            trace.update(output={"error": str(e)})
            raise


class LangChainAdapter(TaskAdapter):
    """Adapter for LangChain chains and agents."""

    async def arun(self, input_data: Any, trace: Any) -> Any:
        """Run LangChain component with Langfuse callback."""
        # Update trace with input
        trace.update(input=input_data)

        try:
            # Prepare input
            if isinstance(input_data, dict):
                chain_input = input_data
            else:
                # Try to determine input key
                if hasattr(self.task, "input_keys") and self.task.input_keys:
                    chain_input = {self.task.input_keys[0]: input_data}
                else:
                    chain_input = {"input": input_data}

            # Run chain/agent
            if hasattr(self.task, "ainvoke"):
                # Async chain
                output = await self.task.ainvoke(chain_input)
            elif hasattr(self.task, "invoke"):
                # Sync chain - run in thread pool
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(
                    None, lambda: self.task.invoke(chain_input)
                )
            else:
                raise ValueError(
                    "LangChain object must have 'invoke' or 'ainvoke' method"
                )

            # Extract output
            if isinstance(output, dict):
                # Try to get the main output
                if "output" in output:
                    final_output = output["output"]
                elif hasattr(self.task, "output_keys") and self.task.output_keys:
                    final_output = output.get(self.task.output_keys[0], output)
                else:
                    final_output = output
            else:
                final_output = output

            # Update trace with output
            trace.update(output=final_output)
            return final_output
        except Exception as e:
            # Update trace with error
            trace.update(output={"error": str(e)})
            raise


class OpenAIAdapter(TaskAdapter):
    """Adapter for OpenAI client calls."""

    async def arun(self, input_data: Any, trace: Any) -> Any:
        """Run OpenAI API call with tracing."""
        # Update trace with input
        trace.update(input=input_data)

        try:
            # Assume task is a configured completion function
            if inspect.iscoroutinefunction(self.task):
                output = await self.task(input_data)
            else:
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(None, self.task, input_data)

            # Update trace with output
            trace.update(output=output)
            return output
        except Exception as e:
            # Update trace with error
            trace.update(output={"error": str(e)})
            raise


def auto_detect_task(task: Any, client: Langfuse) -> TaskAdapter:
    """
    Auto-detect task type and return appropriate adapter.

    Args:
        task: The task to evaluate
        client: Langfuse client

    Returns:
        Appropriate TaskAdapter instance
    """
    # Check for LangChain
    if hasattr(task, "invoke") or hasattr(task, "ainvoke"):
        return LangChainAdapter(task, client)

    # Check for OpenAI-like interface
    if hasattr(task, "create") or hasattr(task, "acreate"):
        return OpenAIAdapter(task, client)

    # Check if it's a callable
    if callable(task):
        return FunctionAdapter(task, client)

    # Unknown type
    raise ValueError(
        f"Cannot auto-detect task type for {type(task)}. "
        "Task must be a callable, LangChain chain/agent, or OpenAI client."
    )
