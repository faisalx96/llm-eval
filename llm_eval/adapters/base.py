"""Base adapter interface and auto-detection logic."""

import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import Any, Optional, Callable, Dict, Tuple, List
from langfuse import Langfuse


class TaskAdapter(ABC):
    """Base class for task adapters."""
    
    def __init__(self, task: Any, client: Langfuse):
        self.task = task
        self.client = client
    
    @abstractmethod
    async def arun(self, input_data: Any, trace: Any, *, model_name: Optional[str] = None) -> Any:
        """Run the task asynchronously with tracing."""
        pass
    
    def run(self, input_data: Any, trace: Any, *, model_name: Optional[str] = None) -> Any:
        """Run the task synchronously."""
        return asyncio.run(self.arun(input_data, trace, model_name=model_name))


class FunctionAdapter(TaskAdapter):
    """Adapter for regular Python functions with smart argument resolution."""

    def __init__(self, task: Any, client: Langfuse):
        super().__init__(task, client)
        self._is_async = inspect.iscoroutinefunction(self.task)
        self.sig = inspect.signature(self.task)
        
        # Analyze parameters
        self._model_param: Optional[str] = None
        self._trace_id_param: Optional[str] = None
        self._params = {}
        self._accepts_kwargs = False

        for name, param in self.sig.parameters.items():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                self._accepts_kwargs = True
                continue

            if name in ("model", "model_name"):
                self._model_param = name
            elif name == "trace_id":
                self._trace_id_param = name
            else:
                self._params[name] = param

    def _resolve_args(self, input_data: Any, model_name: Optional[str], trace_id: Optional[str] = None) -> Tuple[Tuple, Dict[str, Any]]:
        """
        Resolve arguments for the function call based on input data and signature.
        Returns (args, kwargs).
        """
        kwargs: Dict[str, Any] = {}
        args: List[Any] = []

        # 1. Handle Model Argument
        if self._model_param:
            kwargs[self._model_param] = model_name
        elif self._accepts_kwargs and model_name:
            kwargs["model"] = model_name

        # 2. Handle trace_id Argument
        if self._trace_id_param:
            kwargs[self._trace_id_param] = trace_id
        elif self._accepts_kwargs and trace_id:
            kwargs["trace_id"] = trace_id

        # 3. Handle Input Data
        # Case A: Input is a dictionary
        if isinstance(input_data, dict):
            # Check if we should unpack:
            # - If any parameter name matches a key in input_data
            # - OR if we have multiple parameters (excluding model)
            # - OR if we have NO parameters (maybe just **kwargs)
            
            matches_key = any(param in input_data for param in self._params)
            has_multiple_params = len(self._params) > 1
            
            if matches_key or has_multiple_params or self._accepts_kwargs:
                # Strategy: Unpack dictionary
                # Pass matched keys as kwargs
                for key, value in input_data.items():
                    if key in self._params or self._accepts_kwargs:
                        kwargs[key] = value
                
                # Check for missing required parameters
                # If we have a single param that didn't match, and it has no default, 
                # maybe it was meant to receive the whole dict? 
                # (Only if we didn't match ANY keys and have exactly one param)
                if not matches_key and len(self._params) == 1:
                    param_name = next(iter(self._params))
                    # If we haven't filled it yet
                    if param_name not in kwargs:
                         # Fallback: Pass entire dict to this single parameter
                         kwargs[param_name] = input_data
            else:
                # Single parameter, no key match, no kwargs support -> Pass whole dict
                if len(self._params) == 1:
                    param_name = next(iter(self._params))
                    kwargs[param_name] = input_data
                elif len(self._params) == 0:
                    # No params, maybe just side effects? 
                    pass
        
        # Case B: Input is not a dictionary (str, int, etc.)
        else:
            # If we have exactly one parameter, pass it there
            if len(self._params) == 1:
                param_name = next(iter(self._params))
                kwargs[param_name] = input_data
            # If we have multiple, we can't really guess, but maybe the first one?
            # Let's stick to positional for the first param if it's not a dict
            elif len(self._params) > 1:
                # This is ambiguous. Let's try passing as first positional arg
                # But our _params dict is unordered in older python? No, ordered in 3.7+
                # We'll just append to args
                args.append(input_data)
            else:
                # No params
                pass

        return tuple(args), kwargs

    async def arun(self, input_data: Any, trace: Any, *, model_name: Optional[str] = None) -> Any:
        """Run function with proper tracing."""
        # Update trace with input
        trace.update(input=input_data)

        # Extract trace_id from trace object if user's function needs it
        trace_id: Optional[str] = None
        if self._trace_id_param or self._accepts_kwargs:
            try:
                if hasattr(trace, 'trace_id'):
                    ti = getattr(trace, 'trace_id')
                    trace_id = str(ti() if callable(ti) else ti)
                elif hasattr(trace, 'id'):
                    trace_id = str(getattr(trace, 'id'))
            except Exception:
                pass

        args, kwargs = self._resolve_args(input_data, model_name, trace_id)

        loop = asyncio.get_event_loop()
        try:
            # Check if function is async
            if self._is_async:
                output = await self.task(*args, **kwargs)
            else:
                # Run sync function in thread pool to avoid blocking
                output = await loop.run_in_executor(None, lambda: self.task(*args, **kwargs))

            # Update trace with output
            trace.update(output=output)
            return output
        except Exception as e:
            # Update trace with error
            trace.update(output={"error": str(e)})
            raise


class LangChainAdapter(TaskAdapter):
    """Adapter for LangChain chains and agents."""
    
    async def arun(self, input_data: Any, trace: Any, *, model_name: Optional[str] = None) -> Any:
        """Run LangChain component with Langfuse callback."""
        # Update trace with input
        trace.update(input=input_data)
        
        try:
            # Prepare input
            if isinstance(input_data, dict):
                chain_input = dict(input_data)
            else:
                # Try to determine input key
                if hasattr(self.task, 'input_keys') and self.task.input_keys:
                    chain_input = {self.task.input_keys[0]: input_data}
                else:
                    chain_input = {"input": input_data}

            if model_name:
                chain_input.setdefault("model", model_name)
                chain_input.setdefault("model_name", model_name)
            
            # Run chain/agent
            if hasattr(self.task, 'ainvoke'):
                # Async chain
                output = await self.task.ainvoke(chain_input)
            elif hasattr(self.task, 'invoke'):
                # Sync chain - run in thread pool
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(
                    None,
                    lambda: self.task.invoke(chain_input)
                )
            else:
                raise ValueError("LangChain object must have 'invoke' or 'ainvoke' method")
            
            # Extract output
            if isinstance(output, dict):
                # Try to get the main output
                if 'output' in output:
                    final_output = output['output']
                elif hasattr(self.task, 'output_keys') and self.task.output_keys:
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
    
    async def arun(self, input_data: Any, trace: Any, *, model_name: Optional[str] = None) -> Any:
        """Run OpenAI API call with tracing."""
        # Update trace with input
        trace.update(input=input_data)

        payload = input_data
        if model_name and isinstance(input_data, dict):
            payload = dict(input_data)
            payload.setdefault("model", model_name)
        
        try:
            # Assume task is a configured completion function
            if inspect.iscoroutinefunction(self.task):
                output = await self.task(payload)
            else:
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(None, self.task, payload)
            
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
    if hasattr(task, 'invoke') or hasattr(task, 'ainvoke'):
        return LangChainAdapter(task, client)
    
    # Check for OpenAI-like interface
    if hasattr(task, 'create') or hasattr(task, 'acreate'):
        return OpenAIAdapter(task, client)
    
    # Check if it's a callable
    if callable(task):
        return FunctionAdapter(task, client)
    
    # Unknown type
    raise ValueError(
        f"Cannot auto-detect task type for {type(task)}. "
        "Task must be a callable, LangChain chain/agent, or OpenAI client."
    )
