"""Dataset wrappers for evaluation."""

from __future__ import annotations

import csv
import json
import os
from urllib import parse, request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from collections import defaultdict

from .item_identity import build_identity_fingerprint
from ..utils.errors import CsvDatasetSchemaError, DatasetNotFoundError


@dataclass(frozen=True)
class CsvDatasetItem:
    """Single dataset item loaded from CSV."""

    id: str
    input: Any
    expected_output: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    dataset_item_pk: Optional[int] = None


class CsvDataset:
    """Load evaluation items from a local CSV file.

    Column mapping is user-configurable so existing CSVs don't need renaming.

    Parsing rules:
    - If a cell starts with '{' or '[', we attempt JSON parsing (dict/list).
    - Otherwise, values are kept as strings to avoid surprising coercions.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        input_col: str = "input",
        expected_col: str | None = "expected_output",
        id_col: str | None = None,
        metadata_cols: Sequence[str] | None = None,
        name: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.input_col = input_col
        self.expected_col = expected_col
        self.id_col = id_col
        self.metadata_cols = list(metadata_cols) if metadata_cols else []
        self.name = name or self.path.name

        self._items: Optional[List[CsvDatasetItem]] = None

        if self.path.suffix.lower() != ".csv":
            raise CsvDatasetSchemaError(
                "Custom dataset must be a .csv file",
                file_path=str(self.path),
            )
        if not self.path.exists():
            raise CsvDatasetSchemaError(
                "CSV file not found",
                file_path=str(self.path),
            )

    @staticmethod
    def _parse_cell(raw: Any, *, file_path: str, row: int, column: str) -> Any:
        """Parse a CSV cell into a Python value with minimal magic."""
        if raw is None:
            return ""
        text = str(raw)
        stripped = text.lstrip()
        if not stripped:
            return ""
        first = stripped[0]
        if first not in ("{", "["):
            return text
        try:
            return json.loads(stripped)
        except Exception as exc:
            raise CsvDatasetSchemaError(
                f"Invalid JSON value: {exc}",
                file_path=file_path,
                row=row,
                column=column,
            ) from exc

    def _load_items(self) -> List[CsvDatasetItem]:
        file_path = str(self.path)
        try:
            with self.path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                if not fieldnames:
                    raise CsvDatasetSchemaError("CSV has no header row", file_path=file_path)

                def _require_col(col: str) -> None:
                    if col not in fieldnames:
                        raise CsvDatasetSchemaError(
                            "Missing required column",
                            file_path=file_path,
                            column=col,
                        )

                _require_col(self.input_col)
                if self.expected_col:
                    _require_col(self.expected_col)
                if self.id_col:
                    _require_col(self.id_col)
                for c in self.metadata_cols:
                    _require_col(c)

                rows = list(reader)
                generated_counts: Dict[str, int] = defaultdict(int)
                items: List[CsvDatasetItem] = []
                # DictReader yields data rows; CSV line numbers are 1-based with header at row=1.
                # So the first data row is row=2.
                for i, row in enumerate(rows):
                    csv_row_num = i + 2

                    if row is None:
                        continue

                    if self.id_col:
                        raw_id = row.get(self.id_col, "")
                        item_id = str(raw_id).strip()
                        if not item_id:
                            raise CsvDatasetSchemaError(
                                "Empty id value",
                                file_path=file_path,
                                row=csv_row_num,
                                column=self.id_col,
                            )
                    raw_input = row.get(self.input_col, "")
                    parsed_input = self._parse_cell(
                        raw_input, file_path=file_path, row=csv_row_num, column=self.input_col
                    )

                    parsed_expected: Any = None
                    if self.expected_col:
                        raw_expected = row.get(self.expected_col, "")
                        parsed_expected = self._parse_cell(
                            raw_expected, file_path=file_path, row=csv_row_num, column=self.expected_col
                        )

                    md: Dict[str, Any] = {}
                    for c in self.metadata_cols:
                        md[c] = self._parse_cell(row.get(c, ""), file_path=file_path, row=csv_row_num, column=c)

                    if not self.id_col:
                        fingerprint = build_identity_fingerprint(
                            input_value=parsed_input,
                            expected_value=parsed_expected,
                            metadata=md,
                        )
                        generated_counts[fingerprint] += 1
                        item_id = f"csv_{fingerprint}__{generated_counts[fingerprint]:04d}"

                    items.append(
                        CsvDatasetItem(
                            id=item_id,
                            input=parsed_input,
                            expected_output=parsed_expected,
                            metadata=md,
                        )
                    )

                return items
        except CsvDatasetSchemaError:
            raise
        except Exception as exc:
            raise CsvDatasetSchemaError(f"Failed to read CSV: {exc}", file_path=file_path) from exc

    def get_items(self) -> List[CsvDatasetItem]:
        if self._items is None:
            self._items = self._load_items()
        return self._items

    @property
    def size(self) -> int:
        return len(self.get_items())

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"CsvDataset(name='{self.name}', path='{self.path}', items={self.size})"


class JsonlDataset:
    """Load evaluation items from a local JSONL file.

    Each line must be an object with `input` and optional `expected_output`,
    `metadata`, `labels`, and `item_id`/`id`.
    """

    def __init__(self, path: str | Path, *, name: str | None = None) -> None:
        self.path = Path(path)
        self.name = name or self.path.name
        self.version: Optional[str] = None
        self.id: Optional[str] = None
        self.dataset_version_id: Optional[str] = None
        self._items: Optional[List[CsvDatasetItem]] = None
        if self.path.suffix.lower() != ".jsonl":
            raise CsvDatasetSchemaError("JSONL dataset must be a .jsonl file", file_path=str(self.path))
        if not self.path.exists():
            raise CsvDatasetSchemaError("JSONL file not found", file_path=str(self.path))

    def get_items(self) -> List[CsvDatasetItem]:
        if self._items is not None:
            return self._items
        items: List[CsvDatasetItem] = []
        counts: Dict[str, int] = defaultdict(int)
        try:
            for idx, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
                text = line.strip()
                if not text:
                    continue
                obj = json.loads(text)
                if not isinstance(obj, dict):
                    raise CsvDatasetSchemaError("JSONL line must be an object", file_path=str(self.path), row=idx)
                input_value = obj.get("input")
                expected = obj.get("expected_output", obj.get("expected"))
                metadata = obj.get("metadata") or {}
                item_id = str(obj.get("item_id") or obj.get("id") or "").strip()
                if not item_id:
                    fingerprint = build_identity_fingerprint(
                        input_value=input_value,
                        expected_value=expected,
                        metadata=metadata,
                    )
                    counts[fingerprint] += 1
                    item_id = f"ds_{fingerprint}__{counts[fingerprint]:04d}"
                items.append(
                    CsvDatasetItem(
                        id=item_id,
                        input=input_value,
                        expected_output=expected,
                        metadata=metadata,
                    )
                )
        except CsvDatasetSchemaError:
            raise
        except Exception as exc:
            raise CsvDatasetSchemaError(f"Failed to read JSONL: {exc}", file_path=str(self.path)) from exc
        self._items = items
        return items

    @property
    def size(self) -> int:
        return len(self.get_items())

    def __len__(self) -> int:
        return self.size


class InMemoryDataset:
    """Small in-memory dataset for generated tests and programmatic evals."""

    def __init__(self, items: Sequence[Dict[str, Any]], *, name: str = "in-memory", version: str | None = None) -> None:
        self.name = name
        self.version = version
        self.id: Optional[str] = None
        self.dataset_version_id: Optional[str] = None
        self._items = [
            CsvDatasetItem(
                id=str(item.get("item_id") or item.get("id") or f"item_{idx}"),
                input=item.get("input"),
                expected_output=item.get("expected_output", item.get("expected")),
                metadata=dict(item.get("metadata") or {}),
            )
            for idx, item in enumerate(items)
        ]

    def get_items(self) -> List[CsvDatasetItem]:
        return list(self._items)

    @property
    def size(self) -> int:
        return len(self._items)

    def __len__(self) -> int:
        return self.size


class QymDataset:
    """Load a versioned dataset from the qym platform."""

    def __init__(
        self,
        dataset_name: str,
        *,
        version: str | None = None,
        alias: str | None = None,
        platform_url: str | None = None,
        api_key: str | None = None,
        project_slug: str | None = None,
    ) -> None:
        self.name = dataset_name
        self.version = version
        self.alias = alias or (None if version else "production")
        self.platform_url = (platform_url or os.getenv("QYM_PLATFORM_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("QYM_API_KEY")
        self.project_slug = project_slug
        self.id: Optional[str] = None
        self.dataset_version_id: Optional[str] = None
        self._version_label: Optional[str] = None
        self._items: Optional[List[CsvDatasetItem]] = None
        if not self.platform_url or not self.api_key:
            raise DatasetNotFoundError(
                f"Dataset '{dataset_name}' is not a local file and qym platform credentials are missing. "
                "Set QYM_PLATFORM_URL and QYM_API_KEY, or pass CsvDataset/JsonlDataset."
            )

    def _fetch_json(self, path: str) -> Dict[str, Any]:
        req = request.Request(
            f"{self.platform_url}{path}",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except Exception as exc:
            raise DatasetNotFoundError(f"Failed to load qym dataset '{self.name}': {exc}") from exc

    def get_items(self) -> List[CsvDatasetItem]:
        if self._items is not None:
            return self._items
        dataset_ref = parse.quote(self.name, safe="")
        version_ref = parse.quote(self.version or self.alias or "production", safe="")
        params: Dict[str, str] = {"limit": "1000"}
        if self.project_slug:
            params["project_slug"] = self.project_slug
        items: List[CsvDatasetItem] = []
        offset = 0
        version_data: Dict[str, Any] = {}
        while True:
            params["offset"] = str(offset)
            path = f"/v1/datasets/{dataset_ref}/versions/{version_ref}/items?{parse.urlencode(params)}"
            data = self._fetch_json(path)
            dataset_data = data.get("dataset") or {}
            version_data = data.get("version") or version_data
            if dataset_data:
                self.id = str(dataset_data.get("id") or "") or self.id
                self.name = str(dataset_data.get("name") or self.name)
            if version_data:
                self.dataset_version_id = str(version_data.get("id") or "") or self.dataset_version_id
                self._version_label = str(version_data.get("version") or "") or self._version_label
            for item in data.get("items") or []:
                items.append(
                    CsvDatasetItem(
                        id=str(item.get("item_id") or item.get("id")),
                        input=item.get("input"),
                        expected_output=item.get("expected_output"),
                        metadata=dict(item.get("metadata") or {}),
                        dataset_item_pk=item.get("id"),
                    )
                )
            next_offset = data.get("next_offset")
            if next_offset is None:
                break
            offset = int(next_offset)
        if version_data and not self.version:
            self.version = self._version_label
        self._items = items
        return items

    @property
    def size(self) -> int:
        return len(self.get_items())

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"QymDataset(name='{self.name}', version='{self.version or self.alias}', items={self.size})"


def resolve_dataset(
    dataset: str,
    *,
    version: str | None = None,
    alias: str | None = None,
    platform_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Resolve a dataset string to a local or qym-platform dataset object."""
    path = Path(dataset).expanduser()
    if path.exists():
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return CsvDataset(path)
        if suffix == ".jsonl":
            return JsonlDataset(path)
        raise CsvDatasetSchemaError("Unsupported dataset file extension", file_path=str(path))
    return QymDataset(
        dataset,
        version=version,
        alias=alias,
        platform_url=platform_url,
        api_key=api_key,
    )
