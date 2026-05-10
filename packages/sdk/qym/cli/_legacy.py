"""Legacy helper functions moved from the old monolithic cli.py."""

from __future__ import annotations

import copy
import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any, List, Union

from ..core.dataset import CsvDataset
from ..core.evaluator import Evaluator
from ..core.config import RunSpec


def _encode_multipart_formdata(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----qym-" + uuid.uuid4().hex
    crlf = "\r\n"
    lines: list[bytes] = []

    for name, value in (fields or {}).items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for name, fileinfo in (files or {}).items():
        filename, content, content_type = fileinfo
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
        )
        lines.append(f"Content-Type: {content_type}".encode())
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = crlf.encode().join(lines)
    return body, boundary


def load_function_from_file(file_path: str, function_name: str):
    """Load a function from a Python file."""
    spec = importlib.util.spec_from_file_location("user_module", file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise ValueError(f"Function '{function_name}' not found in {file_path}")

    return getattr(module, function_name)


def _load_runs_file(config_path: Path) -> Any:
    text = config_path.read_text(encoding="utf-8")
    suffix = config_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("PyYAML is required to load YAML run configs") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def load_multi_run_specs(config_path: Path) -> List[RunSpec]:
    """Parse a JSON/YAML config file into RunSpec objects."""
    data = _load_runs_file(config_path)
    if not isinstance(data, list):
        raise ValueError("Multi-run config must be a list of run definitions")

    specs: List[RunSpec] = []
    base_dir = config_path.parent

    for idx, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Run #{idx} must be an object")
        try:
            task_file = Path(entry["task_file"])
            task_function = entry["task_function"]
            dataset = entry.get("dataset")
            dataset_csv = entry.get("dataset_csv")
            metrics_value = entry["metrics"]
        except KeyError as exc:
            raise ValueError(f"Run #{idx} is missing required field: {exc}") from exc

        if bool(dataset) == bool(dataset_csv):
            raise ValueError(f"Run #{idx} must set exactly one of 'dataset' or 'dataset_csv'")

        resolved_task_file = task_file if task_file.is_absolute() else (base_dir / task_file).resolve()
        task_callable = load_function_from_file(str(resolved_task_file), task_function)

        if isinstance(metrics_value, str):
            metrics = [m.strip() for m in metrics_value.split(",") if m.strip()]
        elif isinstance(metrics_value, list):
            metrics = [str(m).strip() for m in metrics_value if str(m).strip()]
        else:
            raise ValueError(f"Run #{idx} metrics must be a list or comma-separated string")

        config_template = dict(entry.get("config") or {})
        metadata_template = dict(entry.get("metadata") or {})
        resolved_dataset: Any
        if dataset_csv:
            csv_path = Path(str(dataset_csv))
            resolved_csv = csv_path if csv_path.is_absolute() else (base_dir / csv_path).resolve()
            csv_input_col = entry.get("csv_input_col", "input")
            csv_expected_col = entry.get("csv_expected_col", "expected_output")
            csv_id_col = entry.get("csv_id_col")
            csv_md_cols = entry.get("csv_metadata_cols")
            md_cols: List[str] = []
            if isinstance(csv_md_cols, str):
                md_cols = [c.strip() for c in csv_md_cols.split(",") if c.strip()]
            elif isinstance(csv_md_cols, list):
                md_cols = [str(c).strip() for c in csv_md_cols if str(c).strip()]
            resolved_dataset = CsvDataset(
                resolved_csv,
                input_col=str(csv_input_col),
                expected_col=str(csv_expected_col) if csv_expected_col else None,
                id_col=str(csv_id_col) if csv_id_col else None,
                metadata_cols=md_cols,
            )
        else:
            resolved_dataset = dataset

        model_values = entry.get("models")
        if model_values is None:
            model_values = entry.get("model")
        from ..core.config import EvaluatorConfig
        model_list = EvaluatorConfig.normalize_models(model_values) if model_values is not None else []
        if not model_list:
            model_list = [None]

        output_path = entry.get("output")
        resolved_output_template = None
        if output_path:
            out_path = Path(output_path)
            resolved_output_template = out_path if out_path.is_absolute() else (base_dir / out_path)

        for model_name in model_list:
            config = copy.deepcopy(config_template) if config_template else {}
            config.pop("models", None)
            metadata = dict(metadata_template)
            if model_name:
                metadata.setdefault("model", model_name)
                config["model"] = model_name
            if metadata:
                merged_meta = {**metadata, **dict(config.get("run_metadata") or {})}
                config["run_metadata"] = merged_meta

            base_name = entry.get("name") or config.get("run_name") or task_function
            run_id, display = Evaluator.build_run_identifiers(base_name, model_name)
            config["run_name"] = run_id

            resolved_output = resolved_output_template
            if resolved_output_template and model_name:
                resolved_output = resolved_output_template.with_stem(f"{resolved_output_template.stem}-{model_name}")

            specs.append(
                RunSpec(
                    name=run_id,
                    display_name=display,
                    task=task_callable,
                    dataset=resolved_dataset,
                    metrics=metrics,
                    task_file=str(resolved_task_file),
                    task_function=task_function,
                    config=config,
                    output_path=resolved_output,
                )
            )

    return specs
