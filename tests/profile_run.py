"""Simple script for profiling/benchmarking."""

from dotenv import load_dotenv
load_dotenv()

from qym import Evaluator
import time


def simple_task(input_data, model=None):
    """Simulated task with 100ms latency."""
    time.sleep(6)
    q = input_data.get('question', str(input_data)) if isinstance(input_data, dict) else str(input_data)
    return f"Response: {q[:50]}"


def length_check(output, expected):
    return 1.0 if len(str(output)) > 0 else 0.0


if __name__ == "__main__":
    print("=" * 50)
    print("BENCHMARK: Concurrency Performance Test")
    print("=" * 50)

    # Phase 1: Setup (not timed)
    print("\n[1/3] Loading dataset and initializing evaluator...")
    setup_start = time.perf_counter()

    evaluator = Evaluator(
        task=simple_task,
        dataset="saudi-qa-verification-large",  # 100 items
        metrics=[length_check, "exact_match"],
        config={
            "max_concurrency": 10,
            "run_name": "profile-test",
        }
    )

    # Force dataset to load now
    num_items = len(evaluator.dataset.get_items())
    setup_time = time.perf_counter() - setup_start
    print(f"      Setup complete: {num_items} items loaded in {setup_time:.2f}s")

    # Phase 2: Evaluation (timed)
    print("\n[2/3] Running evaluation...")
    eval_start = time.perf_counter()

    result = evaluator.run(show_progress=False, show_table=False, auto_save=False)

    eval_time = time.perf_counter() - eval_start

    # Phase 3: Results
    print("\n[3/3] Results:")
    throughput = result.total_items / eval_time
    theoretical_min = (result.total_items / 10) * 6  # items / concurrency * latency
    overhead_pct = ((eval_time - theoretical_min) / theoretical_min * 100)

    print(f"\n{'='*50}")
    print(f"BENCHMARK RESULTS")
    print(f"{'='*50}")
    print(f"Items:             {result.total_items}")
    print(f"Success rate:      {result.success_rate:.1%}")
    print(f"")
    print(f"Setup time:        {setup_time:.2f}s  (dataset loading, not counted)")
    print(f"Evaluation time:   {eval_time:.2f}s  <-- THIS IS THE KEY METRIC")
    print(f"")
    print(f"Throughput:        {throughput:.1f} items/s")
    print(f"Theoretical min:   {theoretical_min:.2f}s  ({num_items} items / 10 concurrency × 6s)")
    print(f"Overhead:          {overhead_pct:.1f}%")
    print(f"")
    print(f"Efficiency:        {(theoretical_min / eval_time * 100):.1f}%  (theoretical / actual)")
    print(f"{'='*50}")
