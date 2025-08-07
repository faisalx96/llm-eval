"""Q&A evaluation template for question-answering systems."""

from .base import EvaluationTemplate, TemplateConfig


class QAEvaluationTemplate(EvaluationTemplate):
    """
    Template for evaluating question-answering systems.
    
    This template is designed for evaluating LLMs that answer questions
    based on provided context or general knowledge. It focuses on:
    - Answer relevance to the question
    - Faithfulness to provided context
    - Exact matching for factual answers
    """
    
    def _get_default_config(self) -> TemplateConfig:
        """Get the default configuration for Q&A evaluation."""
        return TemplateConfig(
            name="Q&A Evaluation",
            description="Comprehensive evaluation template for question-answering systems",
            use_cases=[
                "RAG (Retrieval-Augmented Generation) systems",
                "Knowledge base question answering",
                "Reading comprehension tasks",
                "Factual question answering",
                "Customer support chatbots",
                "Educational Q&A systems"
            ],
            metrics=[
                "answer_relevancy",
                "faithfulness", 
                "exact_match"
            ],
            sample_data={
                "input": "What is the capital of France?",
                "expected_output": "Paris",
                "context": "France is a country in Western Europe. Its capital and largest city is Paris."
            },
            best_practices=[
                "Include context when evaluating RAG systems",
                "Use exact_match for factual questions with definitive answers",
                "Use answer_relevancy to ensure responses address the question",
                "Use faithfulness to prevent hallucinations in context-based answers",
                "Provide clear expected outputs for better evaluation accuracy",
                "Consider multiple acceptable answers for subjective questions"
            ],
            customization_guide="""
Customize this template for your specific Q&A use case:

1. **For RAG Systems**: Ensure your dataset includes 'context' field and focus on faithfulness metrics
2. **For Factual Q&A**: Emphasize exact_match and consider adding multiple correct answers
3. **For Open-ended Questions**: Focus on answer_relevancy and consider removing exact_match
4. **For Multi-turn Conversations**: Add conversation history to the input field
5. **For Domain-specific Q&A**: Add domain-specific metrics or customize scoring thresholds

Example customization:
```python
# For medical Q&A with safety concerns
qa_template = QAEvaluationTemplate()
custom_metrics = qa_template.get_metrics() + ['toxicity', 'bias']
evaluator = Evaluator.from_template(
    qa_template, 
    task=medical_qa_system,
    dataset="medical-qa-test",
    custom_metrics=custom_metrics
)
```
            """,
            required_fields=["input", "expected_output"],
            optional_fields=["context", "question_type", "difficulty", "domain"]
        )
    
    def validate_dataset_item(self, item: dict) -> list:
        """Validate Q&A dataset item with additional checks."""
        errors = super().validate_dataset_item(item)
        
        # Q&A specific validations
        if "input" in item:
            input_text = str(item["input"]).strip()
            if not input_text.endswith("?") and len(input_text.split()) < 3:
                errors.append("Input should be a well-formed question")
        
        if "expected_output" in item:
            expected = str(item["expected_output"]).strip()
            if len(expected) < 1:
                errors.append("Expected output cannot be empty for Q&A evaluation")
        
        return errors
    
    def recommend_metrics_for_question_type(self, question_type: str) -> list:
        """
        Recommend specific metrics based on question type.
        
        Args:
            question_type: Type of question (factual, subjective, analytical, etc.)
            
        Returns:
            List of recommended metric names
        """
        base_metrics = ["answer_relevancy"]
        
        type_specific = {
            "factual": ["exact_match", "faithfulness"],
            "subjective": ["faithfulness"],  # Skip exact_match for subjective questions
            "analytical": ["faithfulness"],
            "multiple_choice": ["exact_match"],
            "yes_no": ["exact_match"],
            "numerical": ["exact_match"],
            "contextual": ["faithfulness", "contextual_relevancy"]
        }
        
        additional_metrics = type_specific.get(question_type.lower(), ["faithfulness"])
        return base_metrics + additional_metrics
    
    def create_rag_config(self,
                         task: any,
                         dataset: str, 
                         **kwargs) -> dict:
        """
        Create a specialized configuration for RAG (Retrieval-Augmented Generation) systems.
        
        Args:
            task: The RAG system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for RAG evaluation
        """
        # RAG-specific metrics emphasizing faithfulness and context relevance
        rag_metrics = [
            "answer_relevancy",
            "faithfulness", 
            "contextual_relevancy",
            "contextual_precision"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=rag_metrics,
            **kwargs
        )
        
        return config
    
    def create_factual_qa_config(self,
                                task: any,
                                dataset: str,
                                **kwargs) -> dict:
        """
        Create a specialized configuration for factual Q&A systems.
        
        Args:
            task: The factual Q&A system to evaluate
            dataset: Dataset name  
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for factual Q&A evaluation
        """
        # Factual Q&A metrics emphasizing accuracy and exactness
        factual_metrics = [
            "exact_match",
            "answer_relevancy",
            "faithfulness"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset, 
            custom_metrics=factual_metrics,
            **kwargs
        )
        
        return config