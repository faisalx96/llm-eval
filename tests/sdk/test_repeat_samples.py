"""Tests for repeat runs (samples=k): reducers, execution, checkpoint, accessors."""

import csv
import math

import pytest

from qym import Evaluator, InMemoryDataset, analyze_group_runs
from qym.core.reducers import (
    estimate_pass_at,
    estimate_pass_hat,
    group_stats,
    mean_ci,
    unbiased_pass_at_k,
    unbiased_pass_hat_k,
)


def _dataset(n=5):
    return InMemoryDataset(
        [
            {
                "id": f"q{i}",
                "input": f"question {i}",
                "expected_output": f"question {i}",
            }
            for i in range(n)
        ]
    )


def _local_config(tmp_path, **overrides):
    cfg = {
        "checkpoint_enabled": False,
        "live_mode": "local",
        "output_dir": str(tmp_path),
        "max_concurrency": 1,
        # Short names keep checkpoint paths well below Windows MAX_PATH —
        # lambda tasks inside test classes otherwise produce huge path parts.
        "task_name": "t",
        "run_name": "r",
    }
    cfg.update(overrides)
    return cfg


# ── reducers: formulas ───────────────────────────────────────────────


class TestReducerFormulas:
    def test_unbiased_pass_at_k_edges(self):
        assert unbiased_pass_at_k(8, 6, 3) == 1.0  # n-c < k -> certain
        assert unbiased_pass_at_k(8, 0, 3) == 0.0  # nothing correct
        # exact combinatorial value: 1 - C(5,3)/C(8,3)
        expected = 1 - math.comb(5, 3) / math.comb(8, 3)
        assert abs(unbiased_pass_at_k(8, 3, 3) - expected) < 1e-12

    def test_unbiased_pass_at_k_equals_any_at_k_eq_n(self):
        # at k == n the estimator degenerates to "any pass passed"
        assert unbiased_pass_at_k(3, 1, 3) == 1.0
        assert unbiased_pass_at_k(3, 0, 3) == 0.0

    def test_unbiased_pass_hat_k(self):
        assert unbiased_pass_hat_k(8, 3, 3) == math.comb(3, 3) / math.comb(8, 3)
        assert unbiased_pass_hat_k(8, 2, 3) == 0.0  # c < k
        assert unbiased_pass_hat_k(3, 3, 3) == 1.0

    def test_k_validation(self):
        with pytest.raises(ValueError):
            unbiased_pass_at_k(3, 1, 4)
        with pytest.raises(ValueError):
            unbiased_pass_hat_k(3, 1, 0)

    def test_group_stats_matches_hand_computation(self):
        gs = group_stats(
            {"a": [1.0, 0.0, 1.0], "b": [1.0, 1.0, 1.0], "c": [0.0, 0.0, 0.0]},
            threshold=0.8,
        )
        assert gs["k"] == 3
        assert gs["pass_at_k"] == pytest.approx(2 / 3)
        assert gs["pass_hat_k"] == pytest.approx(1 / 3)
        assert gs["avg_at_k"] == pytest.approx(5 / 9)
        assert gs["max_at_k"] == pytest.approx(2 / 3)
        # a: (2*2/3)-1 = 1/3, b: 1, c: 1 -> mean 7/9
        assert gs["consistency"] == pytest.approx(7 / 9)
        # a: 2/3, b: 1 -> mean 5/6 (items with at least one pass)
        assert gs["reliability"] == pytest.approx(5 / 6)

    def test_estimators_over_items(self):
        items = {"a": [1.0, 1.0, 0.0, 0.0], "b": [1.0, 0.0, 0.0, 0.0]}
        expected = (
            unbiased_pass_at_k(4, 2, 2) + unbiased_pass_at_k(4, 1, 2)
        ) / 2
        assert estimate_pass_at(items, 2) == pytest.approx(expected)
        expected_hat = (
            unbiased_pass_hat_k(4, 2, 2) + unbiased_pass_hat_k(4, 1, 2)
        ) / 2
        assert estimate_pass_hat(items, 2) == pytest.approx(expected_hat)

    def test_mean_ci(self):
        flat = mean_ci([0.5] * 10)
        assert flat == {"mean": 0.5, "ci_low": 0.5, "ci_high": 0.5}
        spread = mean_ci([0.0, 1.0] * 20)
        assert spread["ci_low"] < 0.5 < spread["ci_high"]
        # deterministic for a fixed seed
        assert mean_ci([0.0, 1.0] * 20) == spread


# ── golden parity: samples=k run == k separate runs + analyze_group_runs ──


PATTERN = {
    "q0": [1, 1, 1],
    "q1": [1, 0, 1],
    "q2": [0, 0, 0],
    "q3": [1, 1, 0],
    "q4": [0, 1, 1],
}


class TestGoldenParity:
    def test_group_stats_matches_analyze_group_runs(self, tmp_path):
        data = _dataset(5)

        def make_task(run_idx):
            def task(q):
                item = q.split()[-1]
                return q if PATTERN[f"q{item}"][run_idx] else "wrong"

            return task

        results = [
            Evaluator(
                task=make_task(i),
                dataset=data,
                metrics=["exact_match"],
                config=_local_config(tmp_path),
            ).run(show_tui=False, auto_save=False)
            for i in range(3)
        ]
        golden = analyze_group_runs(results, metric="exact_match", threshold=0.8)

        counters = {}

        def multi_task(q):
            item = q.split()[-1]
            idx = counters.get(item, 0)
            counters[item] = idx + 1
            return q if PATTERN[f"q{item}"][idx] else "wrong"

        rs = Evaluator(
            task=multi_task,
            dataset=data,
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path),
        ).run(show_tui=False, auto_save=False)
        mine = rs.group_stats()

        for key in (
            "pass_at_k",
            "pass_hat_k",
            "avg_at_k",
            "max_at_k",
            "consistency",
            "reliability",
        ):
            if golden[key] is None:
                assert mine[key] is None
            else:
                assert mine[key] == pytest.approx(golden[key]), key


# ── evaluator: execution semantics ───────────────────────────────────


class TestSamplesExecution:
    def test_k_passes_run_and_store(self, tmp_path):
        data = _dataset(4)
        calls = {"n": 0}

        def task(q):
            calls["n"] += 1
            return q

        r = Evaluator(
            task=task,
            dataset=data,
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path),
        ).run(show_tui=False, auto_save=False)

        assert calls["n"] == 12  # 4 items x 3 passes
        assert r.samples == 3
        assert r.total_items == 4  # logical items, not passes
        assert all(sorted(v) == [1, 2, 3] for v in r.passes.values())
        # reduced view: every item's mean == 1.0
        assert r.get_metric_stats("exact_match")["mean"] == pytest.approx(1.0)

    def test_samples_kwarg_overrides_config(self, tmp_path):
        ev = Evaluator(
            task=lambda q: q,
            dataset=_dataset(1),
            metrics=["exact_match"],
            samples=4,
            config=_local_config(tmp_path, samples=2),
        )
        assert ev.samples == 4

    def test_samples_kwarg_validation(self, tmp_path):
        with pytest.raises(ValueError):
            Evaluator(
                task=lambda q: q,
                dataset=_dataset(1),
                metrics=["exact_match"],
                samples=0,
                config=_local_config(tmp_path),
            )

    def test_failed_pass_scores_zero(self, tmp_path):
        data = _dataset(2)
        counters = {}

        def task(q):
            item = q.split()[-1]
            idx = counters.get(item, 0)
            counters[item] = idx + 1
            if item == "0" and idx == 1:  # q0 fails its 2nd pass entirely
                raise RuntimeError("boom")
            return q

        r = Evaluator(
            task=task,
            dataset=data,
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path, max_retries=0),
        ).run(show_tui=False, auto_save=False)

        scores = r.item_pass_scores("exact_match")
        assert scores["q0"] == [1.0, 0.0, 1.0]
        assert scores["q1"] == [1.0, 1.0, 1.0]
        # item is NOT an error overall (other passes succeeded)
        assert "q0" in r.results and "q0" not in r.errors
        gs = r.group_stats()
        assert gs["pass_at_k"] == 1.0
        assert gs["pass_hat_k"] == pytest.approx(0.5)

    def test_ci_fields_only_when_sampling(self, tmp_path):
        r1 = Evaluator(
            task=lambda q: q,
            dataset=_dataset(3),
            metrics=["exact_match"],
            config=_local_config(tmp_path),
        ).run(show_tui=False, auto_save=False)
        assert "ci_low" not in r1.get_metric_stats("exact_match")
        assert r1.samples == 1 and not r1.passes

        r3 = Evaluator(
            task=lambda q: q,
            dataset=_dataset(3),
            metrics=["exact_match"],
            samples=2,
            config=_local_config(tmp_path),
        ).run(show_tui=False, auto_save=False)
        stats = r3.get_metric_stats("exact_match")
        assert "ci_low" in stats and "ci_high" in stats

    def test_pass_completed_observer_event(self, tmp_path):
        events = []

        class Obs:
            def on_pass_completed(self, **kwargs):
                events.append(kwargs)

            def __getattr__(self, name):
                return lambda **kwargs: None

        Evaluator(
            task=lambda q: q,
            dataset=_dataset(2),
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path),
            observer=Obs(),
        ).run(show_tui=False, auto_save=False)

        assert [e["pass_number"] for e in events] == [1, 2, 3]
        assert all(e["samples"] == 3 for e in events)
        assert all("exact_match" in e["metrics"] for e in events)

    def test_identical_outputs_warning(self, tmp_path):
        warnings = []

        class Obs:
            def on_warning(self, **kwargs):
                warnings.append(kwargs.get("message", ""))

            def __getattr__(self, name):
                return lambda **kwargs: None

        Evaluator(
            task=lambda q: q,  # deterministic -> identical passes
            dataset=_dataset(2),
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path),
            observer=Obs(),
        ).run(show_tui=False, auto_save=False)

        assert any("deterministic" in w for w in warnings)


# ── accessors ────────────────────────────────────────────────────────


class TestAccessors:
    @pytest.fixture()
    def sampled_result(self, tmp_path):
        counters = {}

        def multi_task(q):
            item = q.split()[-1]
            idx = counters.get(item, 0)
            counters[item] = idx + 1
            return q if PATTERN[f"q{item}"][idx] else "wrong"

        return Evaluator(
            task=multi_task,
            dataset=_dataset(5),
            metrics=["exact_match"],
            samples=3,
            config=_local_config(tmp_path),
        ).run(show_tui=False, auto_save=False)

    def test_pass_at_hand_computed(self, sampled_result):
        # per-item c of n=3: q0:3, q1:2, q2:0, q3:2, q4:2
        expected = (
            unbiased_pass_at_k(3, 3, 2)
            + 3 * unbiased_pass_at_k(3, 2, 2)
            + unbiased_pass_at_k(3, 0, 2)
        ) / 5
        assert sampled_result.pass_at(2) == pytest.approx(expected)

    def test_pass_hat_hand_computed(self, sampled_result):
        expected = (
            unbiased_pass_hat_k(3, 3, 2)
            + 3 * unbiased_pass_hat_k(3, 2, 2)
            + unbiased_pass_hat_k(3, 0, 2)
        ) / 5
        assert sampled_result.pass_hat(2) == pytest.approx(expected)

    def test_k_above_samples_raises(self, sampled_result):
        with pytest.raises(ValueError):
            sampled_result.pass_at(4)
        with pytest.raises(ValueError):
            sampled_result.pass_hat(4)


# ── checkpoint + resume ──────────────────────────────────────────────


class TestCheckpointPasses:
    def test_rows_carry_pass_number(self, tmp_path):
        r = Evaluator(
            task=lambda q: q,
            dataset=_dataset(3),
            metrics=["exact_match"],
            samples=2,
            config=_local_config(tmp_path, checkpoint_enabled=True),
        ).run(show_tui=False)
        with open(r.last_saved_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 6
        assert sorted({row["pass_number"] for row in rows}) == ["1", "2"]

    def test_interrupt_and_resume_no_duplicates(self, tmp_path):
        data = _dataset(4)
        ckpt = str(tmp_path / "resume.csv")

        calls = {"n": 0}
        r1 = Evaluator(
            task=lambda q: (calls.__setitem__("n", calls["n"] + 1) or q),
            dataset=data,
            metrics=["exact_match"],
            samples=3,
            config=_local_config(
                tmp_path,
                checkpoint_enabled=True,
                resume_from=ckpt,
                run_name="resume-samples",
                should_stop=lambda: calls["n"] >= 5,
            ),
        ).run(show_tui=False)
        assert r1.interrupted

        calls_b = {"n": 0}
        r2 = Evaluator(
            task=lambda q: (calls_b.__setitem__("n", calls_b["n"] + 1) or q),
            dataset=data,
            metrics=["exact_match"],
            samples=3,
            config=_local_config(
                tmp_path,
                checkpoint_enabled=True,
                resume_from=ckpt,
                run_name="resume-samples",
            ),
        ).run(show_tui=False)

        with open(ckpt, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        pairs = [(row["item_id"], row["pass_number"]) for row in rows]
        assert len(rows) == 12  # 4 items x 3 passes, total
        assert len(set(pairs)) == 12  # no duplicated (item, pass) work
        assert calls["n"] + calls_b["n"] == 12
        assert all(len(v) == 3 for v in r2.passes.values())

    def test_legacy_checkpoint_resumes_as_pass_one(self, tmp_path):
        """A pre-samples CSV (no pass_number column) must resume unchanged."""
        data = _dataset(3)
        ckpt = str(tmp_path / "legacy.csv")

        # simulate an old-format file: run new code, then strip the column
        r = Evaluator(
            task=lambda q: q,
            dataset=data,
            metrics=["exact_match"],
            config=_local_config(
                tmp_path,
                checkpoint_enabled=True,
                resume_from=ckpt,
                run_name="legacy-run",
                should_stop=None,
            ),
        ).run(show_tui=False)
        with open(ckpt, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        fieldnames = [c for c in rows[0].keys() if c != "pass_number"]
        with open(ckpt, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows[:2])  # drop one item -> partial run

        calls = {"n": 0}
        r2 = Evaluator(
            task=lambda q: (calls.__setitem__("n", calls["n"] + 1) or q),
            dataset=data,
            metrics=["exact_match"],
            config=_local_config(
                tmp_path,
                checkpoint_enabled=True,
                resume_from=ckpt,
                run_name="legacy-run",
            ),
        ).run(show_tui=False)
        assert calls["n"] == 1  # only the missing item re-ran
        assert r2.total_items == 3


# ── duplicate-spec warning ───────────────────────────────────────────


class TestDuplicateSpecWarning:
    def test_from_runs_warns_on_duplicates(self, tmp_path, caplog):
        import logging

        from qym.core.multi_runner import MultiModelRunner

        spec = {
            "task": lambda q: q,
            "dataset": _dataset(1),
            "metrics": ["exact_match"],
            "config": _local_config(tmp_path),
        }
        with caplog.at_level(logging.WARNING, logger="qym.core.multi_runner"):
            MultiModelRunner.from_runs([dict(spec), dict(spec), dict(spec)])
        assert any("samples=3" in rec.message for rec in caplog.records)
