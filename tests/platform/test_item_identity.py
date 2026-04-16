from qym_platform.item_identity import build_compare_identity, finalize_compare_alignment


def test_platform_compare_identity_prefers_non_positional_item_id():
    duplicate_counts = {}

    identity = build_compare_identity(
        item_id="case-123",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math"},
        duplicate_counts=duplicate_counts,
    )

    assert identity == {
        "compare_item_id": "case-123",
        "compare_alignment_source": "item_id",
    }


def test_platform_compare_identity_falls_back_to_fingerprint_for_legacy_row_ids():
    duplicate_counts = {}

    identity = build_compare_identity(
        item_id="row_000001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math"},
        duplicate_counts=duplicate_counts,
    )

    assert identity["compare_item_id"].startswith("csv_")
    assert identity["compare_alignment_source"] == "fingerprint"


def test_platform_compare_identity_ignores_trace_stats_in_fingerprint():
    first_identity = build_compare_identity(
        item_id="row_000001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math", "trace_stats": {"total_tokens": 42, "cost_usd": 0.01}},
        duplicate_counts={},
    )

    second_identity = build_compare_identity(
        item_id="row_000001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math", "trace_stats": {"total_tokens": 314, "cost_usd": 0.09}},
        duplicate_counts={},
    )

    assert first_identity["compare_item_id"] == second_identity["compare_item_id"]
    assert first_identity["compare_alignment_source"] == "fingerprint"
    assert second_identity["compare_alignment_source"] == "fingerprint"


def test_platform_compare_identity_ignores_retry_count_in_fingerprint():
    # Regression: retry_count leaking into the fingerprint split BIRD items
    # across runs and inflated the "0 runs" bucket on the compare page.
    without_retry = build_compare_identity(
        item_id="1002",
        input_value={"question": "q", "db_id": "x"},
        expected_value="SELECT 1",
        metadata={"difficulty": "moderate"},
        duplicate_counts={},
    )
    with_retry = build_compare_identity(
        item_id="1002",
        input_value={"question": "q", "db_id": "x"},
        expected_value="SELECT 1",
        metadata={"difficulty": "moderate", "retry_count": 1},
        duplicate_counts={},
    )

    assert without_retry["compare_item_id"] == with_retry["compare_item_id"]
    assert without_retry["compare_alignment_source"] == "fingerprint"


def test_platform_compare_identity_ignores_analysis_error_in_fingerprint():
    clean = build_compare_identity(
        item_id="row_000001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math"},
        duplicate_counts={},
    )
    errored = build_compare_identity(
        item_id="row_000001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math", "analysis_error": "llm timeout"},
        duplicate_counts={},
    )

    assert clean["compare_item_id"] == errored["compare_item_id"]


def test_platform_compare_identity_recomputes_generated_csv_item_ids():
    first_identity = build_compare_identity(
        item_id="csv_9d87abc4a109c976c595__0001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math"},
        duplicate_counts={},
    )

    second_identity = build_compare_identity(
        item_id="csv_912a92090d65db565175__0001",
        input_value="What is 2+2?",
        expected_value="4",
        metadata={"domain": "math"},
        duplicate_counts={},
    )

    assert first_identity["compare_item_id"] == second_identity["compare_item_id"]
    assert first_identity["compare_alignment_source"] == "fingerprint"
    assert second_identity["compare_alignment_source"] == "fingerprint"


def test_platform_finalize_compare_alignment_marks_duplicate_compare_keys_unalignable():
    payload = {
        "run": {"run_name": "legacy-run"},
        "snapshot": {
            "rows": [
                {"compare_item_id": "dup-key"},
                {"compare_item_id": "dup-key"},
            ]
        },
    }

    result = finalize_compare_alignment(payload)

    assert result["run"]["compare_alignment_status"] == "unalignable"
    assert result["run"]["compare_alignment_issues"] == ["duplicate compare_item_id: dup-key"]
