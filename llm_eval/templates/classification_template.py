"""Classification evaluation template for text classification systems."""

from .base import EvaluationTemplate, TemplateConfig


class ClassificationTemplate(EvaluationTemplate):
    """
    Template for evaluating text classification systems.
    
    This template is designed for evaluating LLMs that classify text into
    predefined categories. It focuses on:
    - Exact match accuracy for precise classifications
    - Confidence scoring for model certainty
    - Multi-class and multi-label classification support
    """
    
    def _get_default_config(self) -> TemplateConfig:
        """Get the default configuration for classification evaluation."""
        return TemplateConfig(
            name="Classification Accuracy",
            description="Comprehensive evaluation template for text classification systems",
            use_cases=[
                "Sentiment analysis",
                "Intent classification for chatbots",
                "Document categorization",
                "Spam detection",
                "Content moderation",
                "Topic classification", 
                "Language detection",
                "Emotion recognition",
                "Product categorization"
            ],
            metrics=[
                "exact_match"  # Primary metric for classification accuracy
            ],
            sample_data={
                "input": "I love this product! It exceeded my expectations and works perfectly.",
                "expected_output": "positive",
                "classes": ["positive", "negative", "neutral"]
            },
            best_practices=[
                "Use exact_match for precise category matching",
                "Ensure consistent label formatting (lowercase, no spaces, etc.)",
                "Include confidence scores when model provides them",
                "Test with balanced and imbalanced datasets",
                "Consider macro and micro-averaged metrics for multi-class",
                "Validate against edge cases and ambiguous examples",
                "Use stratified sampling for evaluation datasets"
            ],
            customization_guide="""
Customize this template for your specific classification use case:

1. **For Multi-class Classification**: Add precision, recall, and F1 metrics per class
2. **For Imbalanced Classes**: Focus on precision/recall rather than just accuracy
3. **For Confidence Scoring**: Add custom metrics to evaluate prediction confidence
4. **For Hierarchical Classification**: Consider parent-child category relationships
5. **For Multi-label Classification**: Use separate metrics for each label

Example customization:
```python
# For sentiment analysis with confidence scoring
class_template = ClassificationTemplate()

# Custom confidence metric
def confidence_accuracy(output, expected, confidence_threshold=0.8):
    # Your confidence evaluation logic here
    pass

custom_metrics = class_template.get_metrics() + [confidence_accuracy]
evaluator = Evaluator.from_template(
    class_template,
    task=sentiment_classifier,
    dataset="sentiment-test",
    custom_metrics=custom_metrics
)
```

For different classification types:
- **Binary Classification**: Focus on precision, recall, F1, and AUC
- **Multi-class**: Use macro/micro averages and confusion matrix analysis
- **Multi-label**: Evaluate each label separately and consider label dependencies
            """,
            required_fields=["input", "expected_output"],
            optional_fields=["confidence", "classes", "probability_distribution", "multi_label"]
        )
    
    def validate_dataset_item(self, item: dict) -> list:
        """Validate classification dataset item with additional checks."""
        errors = super().validate_dataset_item(item)
        
        # Classification specific validations
        if "expected_output" in item:
            expected = item["expected_output"]
            
            # Check if it's a valid classification label
            if isinstance(expected, str):
                expected = expected.strip()
                if not expected:
                    errors.append("Expected output cannot be empty for classification")
            elif isinstance(expected, list):
                # Multi-label classification
                if not expected:
                    errors.append("Expected output list cannot be empty for multi-label classification")
                if not all(isinstance(label, str) and label.strip() for label in expected):
                    errors.append("All labels in multi-label classification must be non-empty strings")
            else:
                errors.append("Expected output must be a string (single-label) or list (multi-label)")
        
        # Validate classes if provided
        if "classes" in item:
            classes = item["classes"]
            if not isinstance(classes, list) or not classes:
                errors.append("Classes field must be a non-empty list")
            elif not all(isinstance(cls, str) and cls.strip() for cls in classes):
                errors.append("All class names must be non-empty strings")
        
        # Validate confidence if provided
        if "confidence" in item:
            confidence = item["confidence"]
            if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
                errors.append("Confidence must be a number between 0 and 1")
        
        return errors
    
    def recommend_metrics_for_classification_type(self, classification_type: str, num_classes: int = None) -> list:
        """
        Recommend specific metrics based on classification type.
        
        Args:
            classification_type: Type of classification (binary, multiclass, multilabel)
            num_classes: Number of classes (if known)
            
        Returns:
            List of recommended metric names
        """
        base_metrics = ["exact_match"]
        
        type_specific = {
            "binary": [],  # exact_match is sufficient for binary
            "multiclass": [],  # exact_match covers multi-class accuracy
            "multilabel": [],  # exact_match can handle multi-label if output format is consistent
            "imbalanced": [],  # May want to add precision/recall metrics
            "hierarchical": []  # May want to add custom hierarchical accuracy
        }
        
        additional_metrics = type_specific.get(classification_type.lower(), [])
        return base_metrics + additional_metrics
    
    def create_sentiment_analysis_config(self,
                                       task: any,
                                       dataset: str,
                                       **kwargs) -> dict:
        """
        Create a specialized configuration for sentiment analysis.
        
        Args:
            task: The sentiment analysis system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for sentiment analysis
        """
        # Sentiment analysis metrics
        sentiment_metrics = [
            "exact_match"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=sentiment_metrics,
            **kwargs
        )
        
        return config
    
    def create_intent_classification_config(self,
                                          task: any,
                                          dataset: str,
                                          **kwargs) -> dict:
        """
        Create a specialized configuration for intent classification.
        
        Args:
            task: The intent classification system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for intent classification
        """
        # Intent classification metrics focusing on accuracy
        intent_metrics = [
            "exact_match"
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=intent_metrics,
            **kwargs
        )
        
        return config
    
    def create_multilabel_config(self,
                               task: any,
                               dataset: str,
                               **kwargs) -> dict:
        """
        Create a specialized configuration for multi-label classification.
        
        Args:
            task: The multi-label classification system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration
            
        Returns:
            Configuration optimized for multi-label classification
        """
        # Multi-label classification metrics
        multilabel_metrics = [
            "exact_match"  # Will need custom logic to handle list comparisons
        ]
        
        config = self.create_evaluator_config(
            task=task,
            dataset=dataset,
            custom_metrics=multilabel_metrics,
            **kwargs
        )
        
        return config
    
    def get_classification_report_template(self) -> dict:
        """
        Get a template for classification evaluation reports.
        
        Returns:
            Dictionary template for comprehensive classification evaluation
        """
        return {
            "accuracy": "Overall classification accuracy",
            "precision": "Precision per class and averaged",
            "recall": "Recall per class and averaged", 
            "f1_score": "F1 score per class and averaged",
            "confusion_matrix": "Detailed confusion matrix",
            "classification_report": "Sklearn-style classification report",
            "class_distribution": "Distribution of predicted vs actual classes",
            "confidence_distribution": "Distribution of prediction confidences (if available)",
            "error_analysis": "Common misclassification patterns"
        }