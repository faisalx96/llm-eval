from typing import Any, Callable, Dict, List, Optional, Union, Sequence
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime

class EvaluatorConfig(BaseModel):
    """Configuration for a single evaluation run."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_name: Optional[str] = None
    task_name: Optional[str] = None  # #15: Override the auto-derived task name
    max_concurrency: int = Field(default=10, ge=1)
    max_metric_concurrency: int = Field(default=1, ge=1)
    timeout: Optional[float] = Field(default=300, gt=0)
    # Hard wall-clock cap per metric call. A metric that hangs beyond this budget
    # is cancelled with asyncio.wait_for and recorded as score=0 with a "timeout"
    # label — so one misbehaving metric (e.g. an LLM judge that never returns)
    # cannot hold an entire item hostage. 60s comfortably covers a healthy LLM
    # judge (~5-30s typical, ~60s long-reasoning tail) while still catching a
    # hung upstream within ~1 minute per item. Override for slow custom metrics;
    # set to None to disable.
    metric_timeout: Optional[float] = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    should_stop: Optional[Callable[[], bool]] = Field(default=None, exclude=True)
    git_branch: Optional[str] = None   # Override auto-detected git branch
    git_commit: Optional[str] = None   # Override auto-detected git commit hash
    model: Optional[str] = None
    model_full: Optional[str] = None  # Full provider-prefixed ID (e.g. qwen/qwen3.5-397b-a17b) for API calls
    models: Optional[List[str]] = None
    force_model_override: bool = False  # Replace hardcoded OpenAI chat completion model at the SDK boundary
    
    # Langfuse credentials (optional overrides)
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: Optional[str] = None
    langfuse_project_id: Optional[str] = None
    
    # UI settings
    ui_port: int = 0
    cli_invocation: Optional[str] = None
    
    # Output settings
    output_dir: str = "qym_results"
    checkpoint_enabled: bool = True
    checkpoint_format: str = "csv"
    checkpoint_flush_each_item: bool = True
    checkpoint_fsync: bool = False
    resume_from: Optional[str] = None
    resume_rerun_errors: bool = False
    interrupt_grace_seconds: float = 2.0

    # OpenTelemetry auto-instrumentation (optional)
    otel_enabled: bool = True  # auto-enable if instrumentors installed; no-op if not

    # Phoenix tracing (optional, for dual export alongside Langfuse)
    phoenix_enabled: bool = False
    phoenix_endpoint: Optional[str] = None  # e.g. "http://localhost:6006/v1/traces"

    # Platform integration (deployed web app)
    platform_url: Optional[str] = None
    platform_api_key: Optional[str] = None
    platform_timeout: float = Field(default=5.0, gt=0)
    # Default policy: stream to platform. Users may explicitly opt out via live_mode="local".
    live_mode: str = "platform"  # local|platform|auto

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
