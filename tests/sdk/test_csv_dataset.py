import pytest

from qym.core.dataset import CsvDataset
from qym.utils.errors import CsvDatasetSchemaError


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


def test_csv_dataset_multiple_input_columns_return_dict(tmp_path):
    p = tmp_path / "text2sql.csv"
    p.write_text(
        "id,sql_prompt,sql_context,sql\n"
        "case-1,List users,CREATE TABLE users(id INT),SELECT * FROM users\n",
        encoding="utf-8",
    )

    ds = CsvDataset(
        p,
        input_col=["sql_prompt", "sql_context"],
        expected_col="sql",
        id_col="id",
    )
    item = ds.get_items()[0]

    assert item.input == {
        "sql_prompt": "List users",
        "sql_context": "CREATE TABLE users(id INT)",
    }
    assert item.expected_output == "SELECT * FROM users"
    assert item.id == "case-1"


def test_csv_dataset_rejects_invalid_multiple_input_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("q,a\nhello,world\n", encoding="utf-8")

    with pytest.raises(CsvDatasetSchemaError, match="At least one input column"):
        CsvDataset(p, input_col=[])

    with pytest.raises(CsvDatasetSchemaError, match="Duplicate input column"):
        CsvDataset(p, input_col=["q", "q"])

    with pytest.raises(CsvDatasetSchemaError, match="string or sequence"):
        CsvDataset(p, input_col=123)


def test_csv_dataset_missing_required_column_has_clear_error(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(CsvDatasetSchemaError) as exc:
        CsvDataset(p, input_col="input").get_items()

    # Message should include missing column name
    assert "column=input" in str(exc.value)


def test_csv_dataset_explicit_id_column_preserves_source_ids(tmp_path):
    p = tmp_path / "ids.csv"
    p.write_text(
        "case_id,input,expected_output\n"
        "alpha,What is 2+2?,4\n"
        "beta,What is 3+3?,6\n",
        encoding="utf-8",
    )

    items = CsvDataset(p, id_col="case_id").get_items()

    assert [item.id for item in items] == ["alpha", "beta"]


def test_csv_dataset_generated_ids_are_stable_across_reloads(tmp_path):
    p = tmp_path / "stable.csv"
    p.write_text(
        "input,expected_output,domain\n"
        "What is 2+2?,4,math\n"
        "What is 3+3?,6,math\n",
        encoding="utf-8",
    )

    ids_first = [item.id for item in CsvDataset(p, metadata_cols=["domain"]).get_items()]
    ids_second = [item.id for item in CsvDataset(p, metadata_cols=["domain"]).get_items()]

    assert ids_first == ids_second
    assert all(item_id.startswith("csv_") for item_id in ids_first)


def test_csv_dataset_generated_ids_survive_row_reordering(tmp_path):
    p1 = tmp_path / "ordered.csv"
    p1.write_text(
        "input,expected_output,domain\n"
        "What is 2+2?,4,math\n"
        "Capital of France?,Paris,geography\n",
        encoding="utf-8",
    )
    p2 = tmp_path / "reordered.csv"
    p2.write_text(
        "input,expected_output,domain\n"
        "Capital of France?,Paris,geography\n"
        "What is 2+2?,4,math\n",
        encoding="utf-8",
    )

    items1 = CsvDataset(p1, metadata_cols=["domain"]).get_items()
    items2 = CsvDataset(p2, metadata_cols=["domain"]).get_items()

    ids1 = {item.input: item.id for item in items1}
    ids2 = {item.input: item.id for item in items2}
    assert ids1 == ids2


def test_csv_dataset_generated_ids_disambiguate_duplicates(tmp_path):
    p = tmp_path / "dupes.csv"
    p.write_text(
        "input,expected_output\n"
        "What is 2+2?,4\n"
        "What is 2+2?,4\n",
        encoding="utf-8",
    )

    ids = [item.id for item in CsvDataset(p).get_items()]

    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert ids[0].startswith("csv_")
    assert ids[1].startswith("csv_")
