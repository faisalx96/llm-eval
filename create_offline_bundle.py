#!/usr/bin/env python3
"""
Create offline installation bundle for air-gapped environments.

This script downloads all necessary packages for installing llm-eval
in environments without internet access.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import argparse


def run_command(cmd, check=True):
    """Run a shell command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if check and result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    
    return result


def create_minimal_bundle(output_dir):
    """Create minimal bundle with core dependencies only."""
    print("📦 Creating minimal air-gapped bundle...")
    print("   (Core dependencies only, no DeepEval)")
    
    packages_dir = Path(output_dir) / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    
    # Core dependencies only
    core_packages = [
        "langfuse>=2.0.0",
        "pydantic>=2.0.0", 
        "rich>=13.0.0",
        "aiohttp>=3.8.0",
        "python-dotenv>=0.19.0",
        "nest_asyncio>=1.5.0",
    ]
    
    # Build and download llm-eval locally if setup.py exists
    if Path("setup.py").exists():
        print("   Building local llm-eval package...")
        run_command(["pip", "wheel", ".", "--wheel-dir", str(packages_dir), "--no-deps"])
    else:
        # Try downloading from PyPI
        run_command([
            "pip", "download", "llm-eval",
            "--dest", str(packages_dir),
            "--no-deps"
        ])
    
    # Download core dependencies
    for package in core_packages:
        run_command([
            "pip", "download", package,
            "--dest", str(packages_dir)
        ])
    
    return packages_dir


def create_full_bundle(output_dir):
    """Create full bundle with all optional dependencies."""
    print("📦 Creating full air-gapped bundle...")
    print("   (All dependencies including DeepEval)")
    
    packages_dir = Path(output_dir) / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    
    # Build and download llm-eval locally if setup.py exists
    if Path("setup.py").exists():
        print("   Building local llm-eval package...")
        run_command(["pip", "wheel", ".", "--wheel-dir", str(packages_dir), "--no-deps"])
        
        # Download dependencies for [all] extras (but not the main package)
        run_command([
            "pip", "download", ".[all]",
            "--dest", str(packages_dir)
        ])
    else:
        # Download everything from PyPI
        run_command([
            "pip", "download", "llm-eval[all]",
            "--dest", str(packages_dir)
        ])
    
    return packages_dir


def create_install_script(output_dir, minimal=True):
    """Create installation script for the bundle."""
    install_script = Path(output_dir) / "install.sh"
    
    script_content = f"""#!/bin/bash
# LLM-Eval Offline Installation Script
# Generated for {'minimal' if minimal else 'full'} installation

set -e

echo "🔒 Installing llm-eval for air-gapped environment..."

# Check if pip is available
if ! command -v pip &> /dev/null; then
    echo "❌ pip is not installed. Please install Python and pip first."
    exit 1
fi

# Install packages
echo "📦 Installing packages..."
pip install ./packages/*.whl \\
    --find-links ./packages \\
    --no-index \\
    --force-reinstall \\
    --no-deps

echo "✅ Installation complete!"

# Verify installation
echo "🔍 Verifying installation..."
if python -c "import llm_eval; print('✅ llm_eval imported successfully')" 2>/dev/null; then
    echo "✅ llm-eval is working correctly!"
    
    # Show available metrics
    echo ""
    echo "📊 Available metrics:"
    python -c "from llm_eval.metrics import list_available_metrics; list_available_metrics()"
    
else
    echo "❌ Installation verification failed"
    exit 1
fi

echo ""
echo "🎉 Air-gapped installation successful!"
echo "💡 You can now use llm-eval with built-in metrics."
echo "📖 See AIR_GAPPED_GUIDE.md for usage examples."
"""
    
    with open(install_script, "w") as f:
        f.write(script_content)
    
    # Make executable
    os.chmod(install_script, 0o755)
    
    return install_script


def create_usage_guide(output_dir, minimal=True):
    """Create a usage guide for the bundle."""
    guide_file = Path(output_dir) / "USAGE.md"
    
    guide_content = f"""# Air-Gapped Installation Usage Guide

## Installation

1. Transfer this entire directory to your air-gapped environment
2. Run the installation script:
   ```bash
   ./install.sh
   ```

## What's Included

This is a **{'minimal' if minimal else 'full'}** installation bundle.

{'### Minimal Bundle' if minimal else '### Full Bundle'}
{'- Core llm-eval functionality' if minimal else '- Complete llm-eval with all features'}
{'- Built-in metrics only (no DeepEval)' if minimal else '- DeepEval metrics included'}
{'- No external API dependencies' if minimal else '- All optional dependencies'}

## Available Metrics

{'### Built-in Metrics (No External APIs)' if minimal else '### All Metrics'}

- `exact_match`: Perfect string matching
- `contains`: Check if output contains expected text  
- `fuzzy_match`: Similarity scoring using sequence matching
- `response_time`: Performance timing
- `token_count`: Token estimation

{'Note: Advanced DeepEval metrics require the full bundle.' if minimal else 'Plus all DeepEval metrics (require API keys for some features).'}

## Quick Start

```python
#!/usr/bin/env python3
import asyncio
from llm_eval.metrics.builtin import exact_match, contains_expected, fuzzy_match

async def my_task(input_data):
    # Your AI/LLM logic here
    question = input_data.get("question", "")
    return f"Answer to: {{question}}"

async def main():
    test_case = {{"question": "What is AI?", "expected": "artificial intelligence"}}
    
    output = await my_task(test_case)
    expected = test_case["expected"]
    
    # Calculate metrics
    exact_score = exact_match(output, expected)
    contains_score = contains_expected(output, expected)
    fuzzy_score = fuzzy_match(output, expected)
    
    print(f"Output: {{output}}")
    print(f"Exact Match: {{exact_score}}")
    print(f"Contains: {{contains_score}}")
    print(f"Fuzzy Match: {{fuzzy_score:.3f}}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Full Example

See the included `air_gapped_example.py` for a complete working example.

## Troubleshooting

1. **Import errors**: Ensure all packages installed correctly
2. **Permission errors**: Run with appropriate permissions
3. **Python version**: Requires Python 3.9 or higher

## Support

- Use built-in metrics for air-gapped environments
- Create custom metrics as needed
- Store test data locally
- Export results for offline analysis
"""
    
    with open(guide_file, "w") as f:
        f.write(guide_content)
    
    return guide_file


def copy_examples(output_dir):
    """Copy relevant examples to the bundle."""
    examples_dir = Path(output_dir) / "examples"
    examples_dir.mkdir(exist_ok=True)
    
    # Copy air-gapped example
    if Path("examples/air_gapped_example.py").exists():
        shutil.copy("examples/air_gapped_example.py", examples_dir)
    
    # Copy air-gapped guide
    if Path("AIR_GAPPED_GUIDE.md").exists():
        shutil.copy("AIR_GAPPED_GUIDE.md", output_dir)


def main():
    parser = argparse.ArgumentParser(description="Create offline installation bundle for llm-eval")
    parser.add_argument("--output", "-o", default="llm-eval-offline", 
                       help="Output directory for the bundle")
    parser.add_argument("--minimal", action="store_true",
                       help="Create minimal bundle (core dependencies only)")
    parser.add_argument("--full", action="store_true", 
                       help="Create full bundle (all dependencies)")
    
    args = parser.parse_args()
    
    if not args.minimal and not args.full:
        print("Please specify --minimal or --full")
        sys.exit(1)
    
    if args.minimal and args.full:
        print("Cannot specify both --minimal and --full")
        sys.exit(1)
    
    output_dir = Path(args.output)
    
    print(f"🔒 Creating air-gapped installation bundle...")
    print(f"   Output directory: {output_dir}")
    print(f"   Bundle type: {'minimal' if args.minimal else 'full'}")
    print()
    
    # Remove existing directory
    if output_dir.exists():
        print(f"Removing existing directory: {output_dir}")
        shutil.rmtree(output_dir)
    
    # Create bundle
    try:
        if args.minimal:
            packages_dir = create_minimal_bundle(output_dir)
        else:
            packages_dir = create_full_bundle(output_dir)
        
        # Create installation script
        install_script = create_install_script(output_dir, minimal=args.minimal)
        
        # Create usage guide
        guide_file = create_usage_guide(output_dir, minimal=args.minimal)
        
        # Copy examples and guides
        copy_examples(output_dir)
        
        # Summary
        package_count = len(list(packages_dir.glob("*.whl")))
        total_size = sum(f.stat().st_size for f in packages_dir.glob("*")) / 1024 / 1024
        
        print()
        print("✅ Bundle created successfully!")
        print(f"   📁 Location: {output_dir.absolute()}")
        print(f"   📦 Packages: {package_count}")
        print(f"   💾 Total size: {total_size:.1f} MB")
        print()
        print("📋 Bundle contents:")
        print(f"   • {install_script.name} - Installation script")
        print(f"   • {guide_file.name} - Usage guide")
        print(f"   • packages/ - Python packages ({package_count} files)")
        if (output_dir / "examples").exists():
            print(f"   • examples/ - Code examples")
        if (output_dir / "AIR_GAPPED_GUIDE.md").exists():
            print(f"   • AIR_GAPPED_GUIDE.md - Comprehensive guide")
        print()
        print("🚀 To install in air-gapped environment:")
        print(f"   1. Transfer '{output_dir}' directory to target system")
        print(f"   2. Run: cd {output_dir} && ./install.sh")
        
    except Exception as e:
        print(f"❌ Error creating bundle: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 