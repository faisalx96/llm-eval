"""
Example showing template system usage for quick LLM evaluation setup.
"""

import random
import time
from dotenv import load_dotenv
from llm_eval import Evaluator, get_template, recommend_template, print_available_templates

# Load environment variables from .env file
load_dotenv()


def ai_assistant(question: str) -> str:
    """A simple AI assistant for demonstration."""
    question_lower = question.lower()
    delay = random.randint(1, 10)  # random integer between 1 and 5
    time.sleep(delay)

    if "capital of france" in question_lower:
        return "Paris is the capital and largest city of France."
    elif "python" in question_lower:
        return "Python is a high-level, interpreted programming language known for its simplicity and readability."
    elif "hello" in question_lower or "hi" in question_lower:
        return "Hello! I'm an AI assistant. How can I help you today?"
    else:
        return "I'm not sure about that specific question, but I'd be happy to help with other topics."


def main():
    # Show available templates
    print("📋 Available Evaluation Templates:")
    print("=" * 50)
    print_available_templates()
    print()
    
    # Example 1: Using Q&A template directly
    print("🤖 Example 1: Q&A Evaluation with Template")
    print("-" * 45)
    
    # Get Q&A template
    qa_template = get_template('qa')
    
    # Show template information
    qa_template.print_info()
    
    # Create evaluator using template
    evaluator_qa = Evaluator.from_template(
        qa_template,
        task=ai_assistant,
        dataset="quickstart-demo"
    )
    
    print("Running Q&A evaluation...")
    results_qa = evaluator_qa.run(show_table=True)
    print()
    
    # Example 2: Template recommendation
    print("🎯 Example 2: Template Recommendation")
    print("-" * 40)
    
    description = "I want to evaluate my chatbot that answers user questions"
    recommendations = recommend_template(description)
    
    print(f"For description: '{description}'")
    print("\nRecommended templates:")
    for i, rec in enumerate(recommendations[:3], 1):
        print(f"{i}. {rec['name']} (confidence: {rec['confidence']:.2f})")
        print(f"   Reason: {rec['reason']}")
        print(f"   Metrics: {', '.join(rec['metrics'])}")
        print()
    
    # Example 3: Customizing template metrics
    print("⚙️  Example 3: Customizing Template Metrics")
    print("-" * 45)
    
    # Get classification template and customize it
    class_template = get_template('classification')
    
    # Custom metric for response length
    def response_length_check(output: str) -> float:
        """Custom metric: Check if response is appropriate length."""
        length = len(output)
        if length < 10:
            return 0.0  # Too short
        elif length > 200:
            return 0.5  # Too long
        else:
            return 1.0  # Just right
    
    # Create evaluator with custom metrics
    custom_metrics = class_template.get_metrics() + [response_length_check]
    
    evaluator_custom = Evaluator.from_template(
        class_template,
        task=ai_assistant,
        dataset="quickstart-demo",
        custom_metrics=custom_metrics
    )
    
    print("Running evaluation with custom metrics...")
    results_custom = evaluator_custom.run(show_table=False)
    print()
    
    # Example 4: Different template types
    print("🎨 Example 4: Different Template Types")
    print("-" * 40)
    
    template_names = ['qa', 'summarization', 'classification', 'general']
    
    for template_name in template_names:
        template = get_template(template_name)
        print(f"\n{template.config.name}:")
        print(f"  Description: {template.config.description}")
        print(f"  Metrics: {', '.join(template.get_metrics())}")
        print(f"  Use cases: {len(template.config.use_cases)} defined")
    
    print("\n✅ Template system demonstration complete!")
    print("💡 Use templates to get started quickly with best-practice evaluation patterns!")


if __name__ == "__main__":
    main()