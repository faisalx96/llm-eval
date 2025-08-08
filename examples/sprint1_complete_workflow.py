"""
Complete Sprint 1 Workflow Example - All Features Integration

This example demonstrates how to use all Sprint 1 features together:
- Template System for instant setup
- Smart Search for result analysis  
- Visualization System for executive reporting
- Excel Export for professional deliverables

Use this as a reference for implementing comprehensive evaluation workflows
that leverage the full power of LLM-Eval v0.3.0.
"""

import os
import sys
import time
import random
from typing import Dict, List

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
# Load environment variables (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("💡 Note: python-dotenv not installed (optional for environment variables)")

# Import all Sprint 1 features with error handling
print("🔄 Loading LLM-Eval Sprint 1 features...")

try:
    from llm_eval import (
        Evaluator, 
        get_template, 
        recommend_template, 
        print_available_templates
    )
    from llm_eval.core.search import SearchEngine
    print("✅ Core LLM-Eval modules loaded successfully")
except ImportError as e:
    print(f"❌ Failed to load core LLM-Eval modules: {e}")
    print("💡 Install requirements: pip install langfuse deepeval rich")
    print("   Or install from source: pip install -e .")
    exit(1)

try:
    from llm_eval.visualizations import ChartGenerator, ExcelChartExporter
    from llm_eval.visualizations.utils import create_evaluation_report, quick_chart
    print("✅ Visualization modules loaded successfully")
    VISUALIZATIONS_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Visualization modules not available: {e}")
    print("💡 Install visualization dependencies: pip install plotly openpyxl pandas")
    VISUALIZATIONS_AVAILABLE = False


def demo_qa_system(question: str) -> str:
    """
    Demo Q&A system that simulates different response patterns.
    This represents your actual LLM application.
    """
    question_lower = question.lower()
    
    # Simulate processing time (realistic for LLM calls)
    processing_time = random.uniform(0.5, 3.0)
    time.sleep(processing_time)
    
    # Simulate occasional failures (5% rate)
    if random.random() < 0.05:
        raise Exception("API timeout or model overload")
    
    # Generate responses with varying quality levels
    if "capital of france" in question_lower:
        quality_level = random.choice(["high", "medium", "low"])
        if quality_level == "high":
            return "Paris is the capital and largest city of France, located in the north-central part of the country."
        elif quality_level == "medium":
            return "Paris is the capital of France."
        else:
            return "France's capital is Paris."
    
    elif "python" in question_lower and "programming" in question_lower:
        quality_level = random.choice(["high", "medium", "low"])
        if quality_level == "high":
            return "Python is a high-level, interpreted programming language known for its simplicity, readability, and extensive ecosystem of libraries."
        elif quality_level == "medium":
            return "Python is a programming language that's easy to learn and widely used."
        else:
            return "Python is a programming language."
    
    elif "machine learning" in question_lower:
        quality_level = random.choice(["high", "medium"])
        if quality_level == "high":
            return "Machine learning is a subset of artificial intelligence that enables computers to learn and improve from experience without being explicitly programmed."
        else:
            return "Machine learning is part of AI that helps computers learn from data."
    
    elif "hello" in question_lower or "hi" in question_lower:
        return "Hello! I'm an AI assistant ready to help answer your questions."
    
    else:
        # For unknown questions, simulate varying response quality
        quality_level = random.choice(["high", "medium", "low", "very_low"])
        if quality_level == "high":
            return "That's an interesting question. While I don't have specific information about that topic, I'd be happy to help with related questions."
        elif quality_level == "medium":
            return "I'm not sure about that specific question, but I can help with other topics."
        elif quality_level == "low":
            return "I don't know about that."
        else:
            return "Hmm..."


def step1_template_discovery():
    """Step 1: Discover and select the right template"""
    print("🎯 STEP 1: Template Discovery and Selection")
    print("=" * 50)
    
    # Show available templates
    print("Available templates:")
    print_available_templates()
    print()
    
    # Get AI-powered recommendations
    use_cases = [
        "I want to evaluate my customer support chatbot",
        "Need to test Q&A accuracy for my knowledge base system", 
        "Evaluating conversational AI performance"
    ]
    
    print("🤖 Getting AI-powered template recommendations:")
    for use_case in use_cases:
        print(f"\nUse case: '{use_case}'")
        recommendations = recommend_template(use_case)
        
        if recommendations:
            top_rec = recommendations[0]
            print(f"✅ Recommended: {top_rec['name']} (confidence: {top_rec['confidence']:.2f})")
            print(f"   Reason: {top_rec['reason']}")
            print(f"   Metrics: {', '.join(top_rec['metrics'])}")
    
    # Select the Q&A template for our demo
    print(f"\n🎯 Selected template: Q&A Template")
    qa_template = get_template('qa')
    print(f"Template description: {qa_template.config.description}")
    print(f"Included metrics: {', '.join(qa_template.get_metrics())}")
    
    return qa_template


def step2_evaluation_execution(qa_template):
    """Step 2: Execute evaluation using template"""
    print("\n🚀 STEP 2: Template-Based Evaluation Execution")
    print("=" * 50)
    
    # Create evaluator from template
    print("Creating evaluator from Q&A template...")
    try:
        # Try to create evaluator from template
        # Note: from_template method may not be implemented yet, so we'll handle fallback
        try:
            evaluator = Evaluator.from_template(
                qa_template,
                task=demo_qa_system,
                dataset="quickstart-demo"  # Your Langfuse dataset
            )
        except AttributeError:
            # Fallback: create evaluator manually with template metrics
            evaluator = Evaluator(
                task=demo_qa_system,
                dataset="quickstart-demo",
                metrics=qa_template.get_metrics()
            )
        
        print("✅ Evaluator created successfully!")
        print(f"Metrics configured: {', '.join(evaluator.metrics)}")
        
        # Run evaluation with Excel auto-save
        print("\n🔄 Running evaluation with Excel auto-export...")
        results = evaluator.run(
            show_progress=True,
            show_table=False,  # Keep console clean for demo
            auto_save=True,
            save_format="excel"
        )
        
        print(f"\n✅ Evaluation completed!")
        print(f"   Total items: {results.total_items}")
        print(f"   Success rate: {results.success_rate:.1%}")
        timing_stats = results.get_timing_stats()
        print(f"   Average time: {timing_stats['mean']:.2f}s")
        print(f"   Excel report auto-saved")
        
        return results
        
    except Exception as e:
        print(f"⚠️  Evaluation failed: {e}")
        print("💡 Make sure you have a 'quickstart-demo' dataset in Langfuse")
        print("   For demo purposes, creating simulated results...")
        
        # Create simulated results for demo
        return create_simulated_results()


def create_simulated_results():
    """Create simulated results for demonstration when dataset is not available"""
    from llm_eval.core.results import EvaluationResult
    
    # Create results container
    results = EvaluationResult(
        dataset_name="quickstart-demo-simulated",
        run_name="sprint1-demo",
        metrics=["exact_match", "answer_relevancy", "faithfulness", "response_time"]
    )
    
    print("🔄 Generating simulated evaluation results...")
    
    # Generate realistic evaluation data
    sample_questions = [
        "What is the capital of France?",
        "Explain Python programming language",
        "What is machine learning?",
        "Hello, how are you?",
        "Tell me about quantum computing",
        "How does photosynthesis work?",
        "What is the largest planet?",
        "Explain artificial intelligence",
        "What is climate change?",
        "How do computers work?"
    ]
    
    sample_data = sample_questions * 5  # 50 total items
    for i, question in enumerate(sample_data):
        item_id = f"item_{i:03d}"
        
        # Simulate successful evaluations (90% success rate)
        if random.random() < 0.9:
            # Generate correlated scores (better responses have better scores across metrics)
            base_quality = random.uniform(0.3, 0.95)
            noise = random.uniform(-0.1, 0.1)
            
            scores = {
                "exact_match": max(0, min(1, base_quality + random.uniform(-0.2, 0.2))),
                "answer_relevancy": max(0, min(1, base_quality + random.uniform(-0.1, 0.1))),
                "faithfulness": max(0, min(1, base_quality + random.uniform(-0.15, 0.15))),
                "response_time": random.uniform(0.5, 4.0)
            }
            
            # Generate simulated output based on question
            try:
                simulated_output = demo_qa_system(question)
            except:
                simulated_output = "Simulated response for demo purposes"
            
            result = {
                "input": question,
                "output": simulated_output,
                "expected_output": "Expected answer",
                "scores": scores,
                "success": True,
                "time": scores["response_time"]
            }
            
            results.add_result(item_id, result)
        
        else:
            # Simulate failures
            error_messages = [
                "API timeout",
                "Rate limit exceeded", 
                "Model overload",
                "Connection error"
            ]
            results.add_error(item_id, random.choice(error_messages))
    
    results.finish()
    
    # Save Excel report manually since we simulated the data
    excel_path = results.save_excel("sprint1_demo_results.xlsx")
    print(f"✅ Simulated results generated and saved to: {excel_path}")
    
    return results


def step3_smart_search_analysis(results):
    """Step 3: Analyze results using Smart Search"""
    print("\n🔍 STEP 3: Smart Search Analysis")
    print("=" * 40)
    
    search = SearchEngine()
    
    # Get intelligent search suggestions
    print("💡 Smart search suggestions for your data:")
    suggestions = search.get_suggestions(results)
    for i, suggestion in enumerate(suggestions[:5], 1):
        print(f"   {i}. {suggestion}")
    print()
    
    # Perform various searches to analyze results
    search_queries = [
        ("failures", "Find all failed evaluations"),
        ("high accuracy scores", "Find high-performing items"),
        ("answer_relevancy < 0.5", "Find items with poor relevancy"),
        ("took more than 3 seconds", "Find slow responses"),
        ("exact_match = 1.0", "Find perfect matches"),
        ("answer_relevancy > 0.8 and faithfulness > 0.8", "Find high-quality responses")
    ]
    
    search_results = {}
    
    print("🔍 Executing smart searches:")
    for query, description in search_queries:
        result = search.search(results, query)
        search_results[query] = result
        
        print(f"\nQuery: '{query}'")
        print(f"Description: {description}")
        print(f"Matches found: {result['total_matches']}")
        
        if result['matched_items']:
            print(f"Successful items: {len(result['matched_items'])}")
        if result['matched_errors']:
            print(f"Failed items: {len(result['matched_errors'])}")
        
        # Show parsing info
        if result['query_info']['parsed']:
            print("✅ Query parsed successfully")
        else:
            print("❌ Query could not be parsed")
    
    return search_results


def step4_visualization_dashboard(results):
    """Step 4: Create professional visualizations"""
    print("\n📊 STEP 4: Professional Visualization Creation")
    print("=" * 45)
    
    if not VISUALIZATIONS_AVAILABLE:
        print("⚠️  Visualization features not available - install dependencies to enable")
        return {"dashboard": None, "distributions": [], "timeline": None, "correlations": [], "comparison": None}
    
    # Initialize chart generator
    charts = ChartGenerator(theme="plotly_white")
    
    print("🎨 Creating comprehensive visualization suite...")
    
    # 1. Executive Dashboard
    print("   📈 Creating executive dashboard...")
    dashboard = charts.create_dashboard(results)
    dashboard_path = "sprint1_executive_dashboard.html"
    dashboard.write_html(dashboard_path)
    print(f"   ✅ Dashboard saved: {dashboard_path}")
    
    # 2. Individual metric distributions
    print("   📊 Creating metric distribution charts...")
    distribution_files = []
    for metric in results.metrics:
        if metric != "response_time":  # Skip time-based metrics for distribution
            try:
                dist_chart = charts.create_metric_distribution_chart(results, metric)
                filename = f"sprint1_distribution_{metric}.html"
                dist_chart.write_html(filename)
                distribution_files.append(filename)
                print(f"   ✅ Distribution chart saved: {filename}")
            except Exception as e:
                print(f"   ⚠️  Could not create distribution for {metric}: {e}")
    
    # 3. Performance timeline
    print("   ⏱️  Creating performance timeline...")
    timeline = charts.create_performance_timeline_chart(results)
    timeline_path = "sprint1_performance_timeline.html"
    timeline.write_html(timeline_path)
    print(f"   ✅ Timeline saved: {timeline_path}")
    
    # 4. Metric correlations
    print("   🔗 Creating correlation analysis...")
    quality_metrics = ["exact_match", "answer_relevancy", "faithfulness"]
    correlation_files = []
    
    for i in range(len(quality_metrics)):
        for j in range(i + 1, len(quality_metrics)):
            try:
                corr_chart = charts.create_metric_correlation_chart(
                    results, quality_metrics[i], quality_metrics[j]
                )
                filename = f"sprint1_correlation_{quality_metrics[i]}_{quality_metrics[j]}.html"
                corr_chart.write_html(filename)
                correlation_files.append(filename)
                print(f"   ✅ Correlation chart saved: {filename}")
            except Exception as e:
                print(f"   ⚠️  Could not create correlation chart: {e}")
    
    # 5. Multi-metric comparison
    print("   🎯 Creating multi-metric comparison...")
    try:
        comparison_chart = charts.create_multi_metric_comparison_chart(results, chart_type="radar")
        comparison_path = "sprint1_metric_comparison.html"
        comparison_chart.write_html(comparison_path)
        print(f"   ✅ Comparison chart saved: {comparison_path}")
    except Exception as e:
        print(f"   ⚠️  Could not create comparison chart: {e}")
        comparison_path = None
    
    visualization_files = {
        'dashboard': dashboard_path,
        'distributions': distribution_files,
        'timeline': timeline_path,
        'correlations': correlation_files,
        'comparison': comparison_path
    }
    
    return visualization_files


def step5_comprehensive_reporting(results, search_results, visualization_files):
    """Step 5: Generate comprehensive reports"""
    print("\n📑 STEP 5: Comprehensive Report Generation")
    print("=" * 45)
    
    if not VISUALIZATIONS_AVAILABLE:
        print("⚠️  Advanced reporting requires visualization dependencies")
        print("   Generating basic Excel report...")
        try:
            basic_excel = results.save_excel("sprint1_basic_report.xlsx")
            print(f"✅ Basic Excel report: {basic_excel}")
            return {"excel": basic_excel}, generate_executive_summary(results, search_results)
        except Exception as e:
            print(f"⚠️  Excel export failed: {e}")
            return {}, generate_executive_summary(results, search_results)
    
    # Create comprehensive report with all formats
    print("🔄 Generating multi-format comprehensive reports...")
    
    try:
        # Create reports directory
        os.makedirs("sprint1_reports", exist_ok=True)
        
        # Generate comprehensive reports
        report_files = create_evaluation_report(
            results,
            output_dir="./sprint1_reports",
            formats=["html", "excel"],
            include_charts=["dashboard", "distributions", "timeline", "correlations"]
        )
        
        print("✅ Comprehensive reports generated:")
        for format_type, filepath in report_files.items():
            print(f"   📄 {format_type.upper()}: {filepath}")
            
    except Exception as e:
        print(f"⚠️  Comprehensive report generation failed: {e}")
        print("   Creating manual Excel report instead...")
        
        # Manual Excel export with charts as fallback
        try:
            excel_exporter = ExcelChartExporter()
            excel_path = excel_exporter.create_excel_report(
                results,
                "sprint1_comprehensive_report.xlsx",
                include_raw_data=True,
                include_charts=True
            )
            print(f"   ✅ Manual Excel report: {excel_path}")
            report_files = {"excel": excel_path}
        except ImportError:
            print("   ⚠️  Excel export requires openpyxl: pip install openpyxl")
            report_files = {}
    
    # Generate executive summary
    print("\n📋 Executive Summary Generation:")
    executive_summary = generate_executive_summary(results, search_results)
    
    # Save executive summary
    summary_path = "sprint1_executive_summary.txt"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(executive_summary)
    
    print(f"✅ Executive summary saved: {summary_path}")
    
    return report_files, executive_summary


def generate_executive_summary(results, search_results) -> str:
    """Generate executive summary combining all analysis"""
    
    # Calculate key metrics
    high_quality_count = search_results.get("answer_relevancy > 0.8 and faithfulness > 0.8", {}).get('total_matches', 0)
    failure_count = search_results.get("failures", {}).get('total_matches', 0)
    slow_response_count = search_results.get("took more than 3 seconds", {}).get('total_matches', 0)
    perfect_match_count = search_results.get("exact_match = 1.0", {}).get('total_matches', 0)
    
    timing_stats = results.get_timing_stats()
    avg_time = timing_stats['mean']
    
    summary = f"""
EXECUTIVE SUMMARY - Q&A System Evaluation
==========================================

EVALUATION OVERVIEW
-------------------
• Dataset: {results.dataset_name}
• Total Evaluations: {results.total_items}
• Success Rate: {results.success_rate:.1%}
• Average Response Time: {avg_time:.2f} seconds
• Evaluation Duration: {results.duration:.1f} seconds

PERFORMANCE HIGHLIGHTS
----------------------
• High-Quality Responses: {high_quality_count} ({high_quality_count/results.total_items*100:.1f}%)
• Perfect Matches: {perfect_match_count} ({perfect_match_count/results.total_items*100:.1f}%)
• System Failures: {failure_count} ({failure_count/results.total_items*100:.1f}%)
• Slow Responses (>3s): {slow_response_count} ({slow_response_count/results.total_items*100:.1f}%)

METRIC SCORES (AVERAGES)
------------------------
"""
    
    # Calculate average scores for each metric
    for metric in results.metrics:
        stats = results.get_metric_stats(metric)
        summary += f"• {metric.replace('_', ' ').title()}: {stats['mean']:.3f}\n"
    
    summary += f"""

KEY INSIGHTS
------------
• The Q&A system demonstrates {'strong' if results.success_rate > 0.9 else 'moderate' if results.success_rate > 0.7 else 'concerning'} reliability with {results.success_rate:.1%} success rate
• Response quality shows {'excellent' if high_quality_count/results.total_items > 0.8 else 'good' if high_quality_count/results.total_items > 0.6 else 'needs improvement'} performance across relevancy and faithfulness metrics
• Performance efficiency is {'excellent' if avg_time < 1.5 else 'good' if avg_time < 3.0 else 'needs optimization'} with average response time of {avg_time:.2f}s

RECOMMENDATIONS
---------------
"""
    
    if results.success_rate < 0.95:
        summary += f"• Address system reliability - {failure_count} failures detected\n"
    
    if avg_time > 3.0:
        summary += f"• Optimize response time - current average of {avg_time:.2f}s exceeds target\n"
    
    if high_quality_count/results.total_items < 0.7:
        summary += "• Improve response quality through better prompt engineering or model tuning\n"
    
    if perfect_match_count/results.total_items < 0.3:
        summary += "• Review exact match criteria - low perfect match rate may indicate data quality issues\n"
    
    summary += f"""
• Continue monitoring with regular evaluations
• Consider A/B testing for system improvements
• Implement automated quality gates based on these metrics

GENERATED BY
------------
LLM-Eval v0.3.0 Sprint 1 Features:
✓ Template-based evaluation setup
✓ Smart search result analysis  
✓ Professional visualization suite
✓ Comprehensive Excel reporting

Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    return summary


def step6_summary_and_next_steps(visualization_files, report_files, executive_summary):
    """Step 6: Provide summary and next steps"""
    print("\n🎉 STEP 6: Summary and Next Steps")
    print("=" * 40)
    
    print("✅ Sprint 1 Complete Workflow Successfully Executed!")
    print("\nFiles Generated:")
    print("================")
    
    # List all generated files
    print("\n📊 Visualizations:")
    if visualization_files['dashboard']:
        print(f"   • Executive Dashboard: {visualization_files['dashboard']}")
    
    if visualization_files['timeline']:
        print(f"   • Performance Timeline: {visualization_files['timeline']}")
    
    if visualization_files['distributions']:
        print(f"   • Distribution Charts: {len(visualization_files['distributions'])} files")
    
    if visualization_files['correlations']:
        print(f"   • Correlation Analysis: {len(visualization_files['correlations'])} files")
    
    if visualization_files['comparison']:
        print(f"   • Metric Comparison: {visualization_files['comparison']}")
    
    print("\n📑 Reports:")
    for format_type, filepath in report_files.items():
        print(f"   • {format_type.upper()} Report: {filepath}")
    
    print(f"\n📋 Executive Summary: sprint1_executive_summary.txt")
    
    print("\n🚀 Next Steps:")
    print("==============")
    print("1. 📈 Open executive dashboard in browser for interactive exploration")
    print("2. 📊 Review Excel reports for detailed analysis and stakeholder sharing")
    print("3. 🔍 Use smart search to investigate specific performance patterns")
    print("4. 🎯 Implement improvements based on insights and re-evaluate")
    print("5. 📅 Schedule regular evaluations using this workflow")
    
    print("\n💡 Sprint 1 Features Demonstrated:")
    print("==================================")
    print("✓ Template System - Instant Q&A evaluation setup")
    print("✓ Smart Search - Natural language result filtering")  
    print("✓ Visualization System - Professional charts and dashboards")
    print("✓ Excel Export - Executive-ready reports with embedded charts")
    print("✓ Comprehensive Workflows - End-to-end evaluation pipeline")
    
    print(f"\n📈 Performance Summary:")
    print(f"✓ Template setup: <1 minute")
    print(f"✓ Evaluation execution: Depends on dataset size")
    print(f"✓ Smart search analysis: <10 seconds")
    print(f"✓ Visualization generation: <30 seconds")
    print(f"✓ Report generation: <1 minute")
    
    # Show executive summary preview
    print(f"\n📋 Executive Summary Preview:")
    print("=" * 30)
    preview_lines = executive_summary.split('\n')[:15]
    for line in preview_lines:
        print(line)
    print("... (see sprint1_executive_summary.txt for complete summary)")


def main():
    """Main workflow orchestrating all Sprint 1 features"""
    print("🚀 LLM-Eval Sprint 1 Complete Workflow Demonstration")
    print("=" * 60)
    print("This demo showcases all Sprint 1 features working together:")
    print("• Template System for instant evaluation setup")
    print("• Smart Search for intelligent result analysis")
    print("• Visualization System for professional reporting")  
    print("• Excel Export for executive deliverables")
    print("=" * 60)
    print()
    
    try:
        # Step 1: Template discovery and selection
        qa_template = step1_template_discovery()
        
        # Step 2: Template-based evaluation execution
        results = step2_evaluation_execution(qa_template)
        
        # Step 3: Smart search analysis
        search_results = step3_smart_search_analysis(results)
        
        # Step 4: Professional visualization creation
        visualization_files = step4_visualization_dashboard(results)
        
        # Step 5: Comprehensive report generation
        report_files, executive_summary = step5_comprehensive_reporting(
            results, search_results, visualization_files
        )
        
        # Step 6: Summary and next steps
        step6_summary_and_next_steps(visualization_files, report_files, executive_summary)
        
        print("\n🎉 WORKFLOW COMPLETED SUCCESSFULLY!")
        print("All Sprint 1 features have been demonstrated and integrated.")
        print("Check the generated files for comprehensive evaluation results.")
        
    except Exception as e:
        print(f"\n❌ Workflow failed with error: {e}")
        import traceback
        traceback.print_exc()
        print("\n💡 Troubleshooting tips:")
        print("• Ensure Langfuse credentials are set in .env file")
        print("• Install visualization dependencies: pip install llm-eval[viz]")
        print("• Create a 'quickstart-demo' dataset in Langfuse for full demo")


if __name__ == "__main__":
    main()