"""
Template System Example - Getting Started in Under 5 Minutes

This example demonstrates how to use the pre-built evaluation templates
to quickly set up LLM evaluation with best practices.
"""

from llm_eval import Evaluator, get_template, recommend_template, print_available_templates


def simple_qa_system(question: str) -> str:
    """A simple Q&A system for demonstration."""
    q = question.lower()
    
    if "capital of france" in q:
        return "Paris"
    elif "largest planet" in q:
        return "Jupiter"
    elif "speed of light" in q:
        return "299,792,458 meters per second"
    elif "photosynthesis" in q:
        return "Photosynthesis is the process by which plants convert light energy into chemical energy using chlorophyll, CO2, and water to produce glucose and oxygen."
    else:
        return "I don't have information about that topic."


def news_summarizer(article: str) -> str:
    """A simple news summarizer for demonstration."""
    # Simulate summarization by taking first few sentences
    sentences = article.split('. ')
    if len(sentences) > 3:
        return '. '.join(sentences[:3]) + '.'
    return article


def sentiment_classifier(text: str) -> str:
    """A simple sentiment classifier for demonstration."""
    text_lower = text.lower()
    
    positive_words = ['love', 'great', 'excellent', 'amazing', 'perfect', 'wonderful']
    negative_words = ['hate', 'terrible', 'awful', 'worst', 'horrible', 'bad']
    
    pos_count = sum(1 for word in positive_words if word in text_lower)
    neg_count = sum(1 for word in negative_words if word in text_lower)
    
    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    else:
        return "neutral"


def main():
    print("🚀 LLM Evaluation Templates - 5 Minute Quickstart")
    print("=" * 55)
    print()
    
    # Step 1: See what templates are available
    print("📋 Step 1: Available Templates")
    print("-" * 30)
    print_available_templates()
    print()
    
    # Step 2: Get template recommendations
    print("🎯 Step 2: Get Template Recommendations")
    print("-" * 40)
    
    descriptions = [
        "I want to evaluate my Q&A chatbot",
        "I need to test my document summarization system", 
        "I'm building a sentiment analysis model"
    ]
    
    for desc in descriptions:
        print(f"\nDescription: '{desc}'")
        recommendations = recommend_template(desc)
        if recommendations:
            top_rec = recommendations[0]
            print(f"✅ Recommended: {top_rec['name']} (confidence: {top_rec['confidence']:.2f})")
            print(f"   Metrics: {', '.join(top_rec['metrics'])}")
    
    print()
    
    # Step 3: Quick Q&A evaluation
    print("🤖 Step 3: Quick Q&A Evaluation")
    print("-" * 32)
    
    # Get Q&A template and create evaluator
    qa_template = get_template('qa')
    print(f"Using template: {qa_template.config.name}")
    print(f"Metrics: {', '.join(qa_template.get_metrics())}")
    
    try:
        evaluator = Evaluator.from_template(
            qa_template,
            task=simple_qa_system,
            dataset="quickstart-demo"  # This dataset should exist in your Langfuse project
        )
        
        print("\n🔄 Running evaluation...")
        results = evaluator.run(show_table=False)
        print("✅ Q&A evaluation complete!")
        
    except Exception as e:
        print(f"⚠️  Demo dataset not found: {e}")
        print("💡 Create a dataset in Langfuse to run the full example")
    
    print()
    
    # Step 4: Template customization
    print("⚙️  Step 4: Template Customization")
    print("-" * 33)
    
    # Get classification template and show customization options
    class_template = get_template('classification')
    print(f"Base template: {class_template.config.name}")
    print(f"Default metrics: {', '.join(class_template.get_metrics())}")
    
    # Example of adding custom metrics
    def confidence_check(output: str) -> float:
        """Custom metric: Award points for confidence expressions."""
        confidence_words = ['definitely', 'certainly', 'clearly', 'obviously']
        return 1.0 if any(word in output.lower() for word in confidence_words) else 0.5
    
    custom_metrics = class_template.get_metrics() + [confidence_check]
    print(f"With custom metric: {len(custom_metrics)} total metrics")
    
    print()
    
    # Step 5: Template information
    print("📖 Step 5: Template Details")
    print("-" * 26)
    
    # Show detailed info for each template type
    template_names = ['qa', 'summarization', 'classification', 'general']
    
    for name in template_names:
        template = get_template(name)
        print(f"\n{template.config.name}:")
        print(f"  Use cases: {len(template.config.use_cases)} scenarios")
        print(f"  Best practices: {len(template.config.best_practices)} guidelines")
        print(f"  Sample data: {'✓' if template.config.sample_data else '✗'}")
    
    print()
    print("🎉 Congratulations! You're ready to use evaluation templates!")
    print()
    print("💡 Next steps:")
    print("   1. Create datasets in Langfuse with your test data")
    print("   2. Use Evaluator.from_template() with your LLM system")
    print("   3. Customize metrics based on your specific needs")
    print("   4. Run evaluations and analyze results")
    print()
    print("📚 For more examples, check out the documentation and other examples!")


if __name__ == "__main__":
    main()