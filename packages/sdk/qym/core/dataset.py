"""Dataset wrappers for evaluation.

- `LangfuseDataset`: loads datasets from Langfuse
- `CsvDataset`: loads datasets from a local CSV file
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from langfuse import Langfuse

from ..utils.errors import CsvDatasetSchemaError, DatasetNotFoundError


class LangfuseDataset:
    """Wrapper for Langfuse datasets with validation and error handling."""
    
    def __init__(self, client: Langfuse, dataset_name: str):
        """
        Initialize dataset wrapper.
        
        Args:
            client: Langfuse client instance
            dataset_name: Name of the dataset in Langfuse
        """
        self.client = client
        self.name = dataset_name
        self._dataset = None
        self._items = None
        
        # Load dataset
        self._load_dataset()
    
    def _load_dataset(self):
        """Load dataset from Langfuse with error handling."""
        try:
            # Try the correct API method
            self._dataset = self.client.get_dataset(name=self.name)
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                # Try to list available datasets
                available = self._get_available_datasets()
                raise DatasetNotFoundError(
                    f"Dataset '{self.name}' not found. "
                    f"Available datasets: {', '.join(available[:5])}{'...' if len(available) > 5 else ''}"
                )
            raise RuntimeError(f"Failed to load dataset: {e}")
        
        # Validate dataset has items
        if not hasattr(self._dataset, 'items') or not self._dataset.items:
            raise ValueError(f"Dataset '{self.name}' is empty. Please add items before evaluation.")
    
    def _get_available_datasets(self) -> List[str]:
        """Get list of available dataset names."""
        try:
            datasets = self.client.get_datasets(limit=10)
            return [d.name for d in datasets.items] if hasattr(datasets, 'items') else []
        except:
            return []
    
    def get_items(self) -> List[Any]:
        """Get all dataset items."""
        if self._items is None:
            self._items = list(self._dataset.items)
        return self._items
    
    def validate_item(self, item: Any, index: int) -> List[str]:
        """
        Validate a dataset item structure.
        
        Args:
            item: Dataset item to validate
            index: Item index for error messages
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check required fields
        if not hasattr(item, 'input') or item.input is None:
            errors.append(f"Item {index}: Missing or null 'input' field")
        
        # Check input type
        if hasattr(item, 'input') and not isinstance(item.input, (dict, str, list, int, float, bool)):
            errors.append(f"Item {index}: Invalid input type {type(item.input)}")
        
        # Check expected_output if present
        if hasattr(item, 'expected_output') and item.expected_output is not None:
            if not isinstance(item.expected_output, (dict, str, list, int, float, bool)):
                errors.append(f"Item {index}: Invalid expected_output type {type(item.expected_output)}")
        
        return errors
    
    @property
    def id(self) -> Optional[str]:
        """Get the dataset ID from Langfuse."""
        if self._dataset and hasattr(self._dataset, 'id'):
            return self._dataset.id
        return None

    @property
    def size(self) -> int:
        """Get number of items in dataset."""
        items = self.get_items()
        return len(items) if items else 0
    
    def __len__(self) -> int:
        """Get number of items in dataset."""
        return self.size
    
    def __repr__(self) -> str:
        """String representation."""
        return f"LangfuseDataset(name='{self.name}', items={self.size})"


@dataclass(frozen=True)
class CsvDatasetItem:
    """Single dataset item loaded from CSV."""

    id: str
    input: Any
    expected_output: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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

                items: List[CsvDatasetItem] = []
                # DictReader yields data rows; CSV line numbers are 1-based with header at row=1.
                # So the first data row is row=2.
                for i, row in enumerate(reader):
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
                    else:
                        item_id = f"row_{i:06d}"

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

