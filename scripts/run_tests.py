#!/usr/bin/env python3
"""
Test runner script for the LLM Evaluation Framework.

This script provides a convenient way to run tests with various configurations
and generate reports for CI/CD pipelines.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


def run_command(cmd: List[str], capture_output: bool = False) -> Dict:
    """Run a command and return result information."""
    print(f"Running: {' '.join(cmd)}")

    start_time = time.time()
    try:
        if capture_output:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        else:
            returncode = subprocess.run(cmd, check=False).returncode
            stdout = ""
            stderr = ""

        end_time = time.time()
        duration = end_time - start_time

        success = returncode == 0
        print(
            f"{'✅' if success else '❌'} Command {'succeeded' if success else 'failed'} in {duration:.2f}s"
        )

        return {
            "command": " ".join(cmd),
            "returncode": returncode,
            "success": success,
            "duration": duration,
            "stdout": stdout,
            "stderr": stderr,
        }

    except Exception as e:
        print(f"❌ Command failed with exception: {e}")
        return {
            "command": " ".join(cmd),
            "returncode": -1,
            "success": False,
            "duration": time.time() - start_time,
            "stdout": "",
            "stderr": str(e),
        }


def run_tests(
    test_types: List[str],
    parallel: bool = False,
    coverage: bool = False,
    verbose: bool = False,
    output_file: Optional[str] = None,
) -> Dict:
    """Run specified test types and return results."""

    results = {}
    total_start_time = time.time()

    # Build pytest command
    base_cmd = ["python", "-m", "pytest"]

    if verbose:
        base_cmd.append("-v")
    else:
        base_cmd.append("-q")

    if parallel:
        base_cmd.extend(["-n", "auto"])

    if coverage:
        base_cmd.extend(
            [
                "--cov=llm_eval",
                "--cov-report=html",
                "--cov-report=term-missing",
                "--cov-report=xml",
            ]
        )

    # Add timeout for safety
    base_cmd.extend(["--timeout=300"])

    # Run each test type
    for test_type in test_types:
        print(f"\n{'='*60}")
        print(f"Running {test_type} tests...")
        print(f"{'='*60}")

        cmd = base_cmd.copy()

        if test_type == "unit":
            cmd.extend(["tests/unit/", "-m", "unit"])
        elif test_type == "integration":
            cmd.extend(["tests/integration/", "-m", "integration"])
        elif test_type == "performance":
            cmd.extend(["tests/performance/", "-m", "performance"])
        elif test_type == "all":
            cmd.append("tests/")
        else:
            print(f"❌ Unknown test type: {test_type}")
            results[test_type] = {
                "success": False,
                "error": f"Unknown test type: {test_type}",
            }
            continue

        result = run_command(cmd, capture_output=True)
        results[test_type] = result

    total_duration = time.time() - total_start_time

    # Generate summary
    summary = {
        "timestamp": time.time(),
        "total_duration": total_duration,
        "test_types": test_types,
        "parallel": parallel,
        "coverage": coverage,
        "results": results,
        "overall_success": all(r.get("success", False) for r in results.values()),
    }

    # Save results if output file specified
    if output_file:
        with open(output_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n📊 Test results saved to: {output_file}")

    return summary


def run_quality_checks() -> Dict:
    """Run code quality checks."""
    print(f"\n{'='*60}")
    print("Running Quality Checks...")
    print(f"{'='*60}")

    checks = {}

    # Format check
    print("\n🎨 Checking code formatting...")
    checks["format"] = run_command(
        ["python", "-m", "black", "--check", "llm_eval", "tests"], capture_output=True
    )

    # Import sorting
    print("\n📦 Checking import sorting...")
    checks["imports"] = run_command(
        ["python", "-m", "isort", "--check-only", "llm_eval", "tests"],
        capture_output=True,
    )

    # Linting
    print("\n🔍 Running linting...")
    checks["lint"] = run_command(
        [
            "python",
            "-m",
            "flake8",
            "llm_eval",
            "tests",
            "--count",
            "--show-source",
            "--statistics",
        ],
        capture_output=True,
    )

    # Type checking
    print("\n🔬 Running type checking...")
    checks["types"] = run_command(
        [
            "python",
            "-m",
            "mypy",
            "llm_eval",
            "--ignore-missing-imports",
            "--no-strict-optional",
        ],
        capture_output=True,
    )

    return {
        "timestamp": time.time(),
        "checks": checks,
        "overall_success": all(
            check.get("success", False) for check in checks.values()
        ),
    }


def run_security_checks() -> Dict:
    """Run security checks."""
    print(f"\n{'='*60}")
    print("Running Security Checks...")
    print(f"{'='*60}")

    checks = {}

    # Bandit security check
    print("\n🔒 Running security analysis...")
    checks["bandit"] = run_command(
        [
            "python",
            "-m",
            "bandit",
            "-r",
            "llm_eval",
            "-f",
            "json",
            "-o",
            "bandit-report.json",
        ],
        capture_output=True,
    )

    # Safety check for dependencies
    print("\n🛡️ Checking dependency vulnerabilities...")
    checks["safety"] = run_command(
        ["python", "-m", "safety", "check"], capture_output=True
    )

    return {
        "timestamp": time.time(),
        "checks": checks,
        "overall_success": all(
            check.get("success", False) for check in checks.values()
        ),
    }


def print_summary(results: Dict):
    """Print a summary of test results."""
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    if "results" in results:
        # Test results
        for test_type, result in results["results"].items():
            status = "✅ PASSED" if result.get("success", False) else "❌ FAILED"
            duration = result.get("duration", 0)
            print(f"{test_type.upper():12} {status} ({duration:.2f}s)")

    if "checks" in results:
        # Quality check results
        for check_type, result in results["checks"].items():
            status = "✅ PASSED" if result.get("success", False) else "❌ FAILED"
            duration = result.get("duration", 0)
            print(f"{check_type.upper():12} {status} ({duration:.2f}s)")

    overall_success = results.get("overall_success", False)
    total_duration = results.get("total_duration", 0)

    print(f"\n{'='*60}")
    status = "✅ ALL PASSED" if overall_success else "❌ SOME FAILED"
    print(f"OVERALL: {status} (Total: {total_duration:.2f}s)")
    print(f"{'='*60}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test runner for LLM Evaluation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tests
  python scripts/run_tests.py --all

  # Run unit tests only
  python scripts/run_tests.py --unit

  # Run tests with coverage
  python scripts/run_tests.py --unit --integration --coverage

  # Run quality checks
  python scripts/run_tests.py --quality

  # Run full CI pipeline
  python scripts/run_tests.py --ci
        """,
    )

    # Test type options
    parser.add_argument("--unit", action="store_true", help="Run unit tests")
    parser.add_argument(
        "--integration", action="store_true", help="Run integration tests"
    )
    parser.add_argument(
        "--performance", action="store_true", help="Run performance tests"
    )
    parser.add_argument("--all", action="store_true", help="Run all tests")

    # Quality check options
    parser.add_argument("--quality", action="store_true", help="Run quality checks")
    parser.add_argument("--security", action="store_true", help="Run security checks")

    # Test options
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # Output options
    parser.add_argument("--output", "-o", help="Save results to JSON file")

    # CI option
    parser.add_argument("--ci", action="store_true", help="Run full CI pipeline")

    args = parser.parse_args()

    if args.ci:
        # Full CI pipeline
        args.all = True
        args.quality = True
        args.security = True
        args.coverage = True
        args.parallel = True

    # Determine test types to run
    test_types = []
    if args.unit:
        test_types.append("unit")
    if args.integration:
        test_types.append("integration")
    if args.performance:
        test_types.append("performance")
    if args.all:
        test_types.append("all")

    # If no test types specified but quality/security checks requested, that's ok
    if not test_types and not args.quality and not args.security:
        print("❌ No test types specified. Use --help for options.")
        return 1

    # Run tests
    overall_success = True
    all_results = {}

    if test_types:
        test_results = run_tests(
            test_types=test_types,
            parallel=args.parallel,
            coverage=args.coverage,
            verbose=args.verbose,
            output_file=args.output,
        )
        all_results.update(test_results)
        overall_success &= test_results["overall_success"]

    if args.quality:
        quality_results = run_quality_checks()
        all_results.update(quality_results)
        overall_success &= quality_results["overall_success"]

    if args.security:
        security_results = run_security_checks()
        all_results.update(security_results)
        overall_success &= security_results["overall_success"]

    # Print summary
    print_summary(all_results)

    # Exit with appropriate code
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
