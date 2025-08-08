"""Langfuse dataset wrapper for evaluation."""

from typing import Any, List, Optional

from langfuse import Langfuse

from ..utils.errors import DatasetNotFoundError


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
        if not hasattr(self._dataset, "items") or not self._dataset.items:
            raise ValueError(
                f"Dataset '{self.name}' is empty. Please add items before evaluation."
            )

    def _get_available_datasets(self) -> List[str]:
        """Get list of available dataset names."""
        try:
            datasets = self.client.get_datasets(limit=10)
            return (
                [d.name for d in datasets.items] if hasattr(datasets, "items") else []
            )
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
        if not hasattr(item, "input") or item.input is None:
            errors.append(f"Item {index}: Missing or null 'input' field")

        # Check input type
        if hasattr(item, "input") and not isinstance(
            item.input, (dict, str, list, int, float, bool)
        ):
            errors.append(f"Item {index}: Invalid input type {type(item.input)}")

        # Check expected_output if present
        if hasattr(item, "expected_output") and item.expected_output is not None:
            if not isinstance(
                item.expected_output, (dict, str, list, int, float, bool)
            ):
                errors.append(
                    f"Item {index}: Invalid expected_output type {type(item.expected_output)}"
                )

        return errors

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
