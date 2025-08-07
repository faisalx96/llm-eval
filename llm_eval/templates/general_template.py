"""General LLM evaluation template for comprehensive model assessment."""

from .base import EvaluationTemplate, TemplateConfig


class GeneralLLMTemplate(EvaluationTemplate):
    """
    Template for general LLM evaluation across multiple dimensions.
    
    This template is designed for comprehensive evaluation of LLMs across
    safety, reliability, and quality dimensions. It focuses on:
    - Hallucination detection
    - Bias identification
    - Safety and toxicity assessment
    """
    
    def _get_default_config(self) -> TemplateConfig:
        """Get the default configuration for general LLM evaluation."""
        return TemplateConfig(
            name="General LLM Evaluation",
            description="Comprehensive evaluation template for general LLM assessment across safety, bias, and quality dimensions",
            use_cases=[
                "General-purpose chatbots",
                "Content generation systems",
                "AI assistants and agents",
                "Educational AI tutors",
                "Creative writing assistants",
                "Code generation models",
                "Conversational AI systems",
                "Multi-domain AI applications"
            ],
            metrics=[
                "hallucination",
                "bias", 
                "toxicity"
            ],
            sample_data={
                "input": "Tell me about the benefits of renewable energy sources.",
                "expected_output": "Renewable energy sources like solar, wind, and hydroelectric power offer several benefits: they reduce greenhouse gas emissions, provide sustainable long-term energy solutions, create jobs in green technology sectors, reduce dependence on fossil fuel imports, and have increasingly competitive costs. However, they also face challenges like intermittency and storage requirements.",
                "context": "Renewable energy discussion for educational purposes"
            },
            best_practices=[
                "Test across diverse topics and domains to catch bias patterns",
                "Include controversial and sensitive topics to test safety measures",
                "Evaluate both factual accuracy and opinion-based responses",
                "Test with prompts designed to elicit problematic behaviors",
                "Include edge cases and adversarial inputs",
                "Evaluate consistency across similar prompts",
                "Test with different user personas and contexts",
                "Monitor for demographic bias in responses"
            ],
            customization_guide="""
Customize this template for your specific LLM evaluation needs:

1. **For Public-Facing Systems**: Add comprehensive safety and bias checks
2. **For Educational Applications**: Focus on factual accuracy and age-appropriate content
3. **For Creative Applications**: Balance safety with creative freedom
4. **For Professional Use**: Add domain-specific bias and accuracy metrics
5. **For Conversational AI**: Add consistency and coherence metrics

Example customization:
```python
# For customer service chatbot with enhanced safety
general_template = GeneralLLMTemplate()
custom_metrics = general_template.get_metrics() + [
    'answer_relevancy',  # Ensure responses address user queries
    'faithfulness'       # Prevent information fabrication
]

evaluator = Evaluator.from_template(
    general_template,
    task=customer_service_bot,
    dataset="customer-service-test",
    custom_metrics=custom_metrics
)
```

For different deployment contexts:
- **High-risk Applications**: Emphasize safety metrics (toxicity, bias, hallucination)
- **Creative Applications**: Balance safety with flexibility, focus on bias detection
- **Educational Systems**: Add factual accuracy and age-appropriateness checks
- **Enterprise Systems**: Focus on consistency, professionalism, and domain accuracy
            """,
            required_fields=["input"],
            optional_fields=["expected_output", "context", "user_persona", "domain", "risk_level"]
        )
    
    def validate_dataset_item(self, item: dict) -> list:
        """Validate general LLM dataset item with additional checks."""
        errors = super().validate_dataset_item(item)
        
        # General LLM specific validations
        if "input" in item:
            input_text = str(item["input"]).strip()
            if len(input_text) < 10:
                errors.append("Input should be substantial for meaningful evaluation (at least 10 characters)")
        
        # Validate risk level if provided
        if "risk_level" in item:
            risk_level = item["risk_level"]
            valid_levels = ["low", "medium", "high", "critical"]
            if risk_level not in valid_levels:
                errors.append(f"Risk level must be one of: {valid_levels}")
        
        return errors
    
    def recommend_metrics_for_risk_level(self, risk_level: str) -> list:
        """
        Recommend specific metrics based on risk level.
        
        Args:
            risk_level: Risk level (low, medium, high, critical)
            
        Returns:
            List of recommended metric names
        """
        base_metrics = ["hallucination", "bias", "toxicity"]
        
        risk_specific = {
            "low": [],  # Basic metrics are sufficient
            "medium": ["answer_relevancy"],  # Add relevance check
            "high": ["answer_relevancy", "faithfulness"],  # Add accuracy checks
            "critical": ["answer_relevancy", "faithfulness"]  # Maximum scrutiny
        }
        
        additional_metrics = risk_specific.get(risk_level.lower(), [])
        return base_metrics + additional_metrics
    
    def create_safety_focused_config(self,
                                   task: any,
                                   dataset: str,
                                   **kwargs) -> dict:
        """
        Create a configuration focused on safety evaluation.
        
        Args:
            task: The LLM system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for safety evaluation
        """
        # Safety-focused metrics
        safety_metrics = [
            "toxicity",
            "bias",
            "hallucination"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=safety_metrics,
            **kwargs
        )
        
        return config
    
    def create_accuracy_focused_config(self,
                                     task: any,
                                     dataset: str,
                                     **kwargs) -> dict:
        """
        Create a configuration focused on accuracy and reliability.
        
        Args:
            task: The LLM system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for accuracy evaluation
        """
        # Accuracy-focused metrics
        accuracy_metrics = [
            "hallucination",
            "faithfulness",
            "answer_relevancy"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=accuracy_metrics,
            **kwargs
        )
        
        return config
    
    def create_comprehensive_config(self,
                                  task: any,
                                  dataset: str,
                                  **kwargs) -> dict:
        """
        Create a comprehensive configuration covering all evaluation dimensions.
        
        Args:
            task: The LLM system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration for comprehensive LLM evaluation
        """
        # Comprehensive metrics covering safety, accuracy, and quality
        comprehensive_metrics = [
            "hallucination",
            "bias",
            "toxicity", 
            "faithfulness",
            "answer_relevancy"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=comprehensive_metrics,
            **kwargs
        )
        
        return config
    
    def get_safety_evaluation_checklist(self) -> dict:
        """
        Get a checklist for comprehensive safety evaluation.
        
        Returns:
            Dictionary of safety evaluation categories and checks
        """
        return {
            "content_safety": [
                "No harmful or dangerous content generation",
                "Appropriate handling of sensitive topics",
                "No promotion of illegal activities",
                "Child safety considerations"
            ],
            "bias_evaluation": [
                "Gender bias detection",
                "Racial and ethnic bias assessment", 
                "Religious bias evaluation",
                "Socioeconomic bias checks",
                "Geographic and cultural bias testing"
            ],
            "factual_accuracy": [
                "No fabrication of facts or statistics",
                "Accurate representation of historical events",
                "Correct scientific and technical information",
                "Proper attribution of quotes and claims"
            ],
            "ethical_considerations": [
                "Respect for privacy and personal information",
                "No manipulation or deception",
                "Transparency about AI limitations",
                "Fair treatment of all user groups"
            ],
            "robustness": [
                "Consistent behavior across similar inputs",
                "Resistance to adversarial prompts",
                "Graceful handling of edge cases",
                "Appropriate uncertainty expression"
            ]
        }