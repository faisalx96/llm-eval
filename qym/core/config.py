from typing import Any, Callable, Dict, List, Optional, Union, Sequence
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime

class EvaluatorConfig(BaseModel):
    """Configuration for a single evaluation run."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_name: Optional[str] = None
    max_concurrency: int = Field(default=10, ge=1)
    timeout: float = Field(default=30.0, gt=0)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    model: Optional[str] = None
    models: Optional[List[str]] = None
    
    # Langfuse credentials (optional overrides)
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: Optional[str] = None
    langfuse_project_id: Optional[str] = None
    
    # UI settings
    ui_port: int = 0
    # UI settings
    ui_port: int = 0
    cli_invocation: Optional[str] = None
    
    # Output settings
    output_dir: str = "qym_results"

    @field_validator("models", mode="before")
    @classmethod
    def normalize_models(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        if isinstance(v, (list, tuple)):
            return [str(m).strip() for m in v if m]
        return v

class RunSpec(BaseModel):
    """Specification for a multi-model run."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    display_name: Optional[str] = None
    task: Any
    dataset: Union[str, Any]
    metrics: List[Union[str, Callable]]
    config: EvaluatorConfig = Field(default_factory=EvaluatorConfig)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None
    
    # Derived fields for display/logging
    task_file: str = "<unknown>"
    task_function: str = "<unknown>"

    @field_validator("metrics", mode="before")
    @classmethod
    def validate_metrics(cls, v: Any) -> List[Union[str, Callable]]:
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        if isinstance(v, (list, tuple)):
            return list(v)
        raise ValueError("metrics must be a string or list")
