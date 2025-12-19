import pytest

from llm_eval.core.dataset import CsvDataset
from llm_eval.utils.errors import CsvDatasetSchemaError


def test_csv_dataset_column_mapping_and_metadata(tmp_path):
    p = tmp_path / "qa.csv"
    p.write_text(
        "question,answer,category\n"
        "What is 2+2?,4,math\n",
        encoding="utf-8",
    )

    ds = CsvDataset(
        p,
        input_col="question",
        expected_col="answer",
        metadata_cols=["category"],
    )
    items = ds.get_items()

    assert len(items) == 1
    assert items[0].input == "What is 2+2?"
    assert items[0].expected_output == "4"
    assert items[0].metadata == {"category": "math"}


def test_csv_dataset_json_parsing_only_for_objects_and_arrays(tmp_path):
    p = tmp_path / "mixed.csv"
    p.write_text(
        "q,a,meta\n"
        '42,["x"],{"k":1}\n',
        encoding="utf-8",
    )

    ds = CsvDataset(p, input_col="q", expected_col="a", metadata_cols=["meta"])
    item = ds.get_items()[0]

    # Scalars remain strings (no coercion)
    assert item.input == "42"
    # Arrays/objects parse when cell starts with '[' / '{'
    assert item.expected_output == ["x"]
    assert item.metadata == {"meta": {"k": 1}}


def test_csv_dataset_missing_required_column_has_clear_error(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(CsvDatasetSchemaError) as exc:
        CsvDataset(p, input_col="input").get_items()

    # Message should include missing column name
    assert "column=input" in str(exc.value)


