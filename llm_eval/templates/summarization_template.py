"""Summarization evaluation template for text summarization systems."""

from .base import EvaluationTemplate, TemplateConfig


class SummarizationTemplate(EvaluationTemplate):
    """
    Template for evaluating text summarization systems.

    This template is designed for evaluating LLMs that generate summaries
    of longer texts. It focuses on:
    - Faithfulness to the original content
    - Coherence and readability of the summary
    - Relevance of included information
    """

    def _get_default_config(self) -> TemplateConfig:
        """Get the default configuration for summarization evaluation."""
        return TemplateConfig(
            name="Summarization Quality",
            description="Comprehensive evaluation template for text summarization systems",
            use_cases=[
                "Document summarization",
                "News article summarization",
                "Research paper abstracts",
                "Meeting notes summarization",
                "Email summarization",
                "Legal document summarization",
                "Medical report summarization",
            ],
            metrics=[
                "faithfulness",
                "summarization",  # DeepEval's built-in summarization metric
                "answer_relevancy",  # To check if summary covers key points
            ],
            sample_data={
                "input": """
The global climate crisis continues to escalate as temperatures reach record highs worldwide.
Scientists report that 2023 has been the warmest year on record, with average global temperatures
rising 1.2 degrees Celsius above pre-industrial levels. The primary drivers include increased
greenhouse gas emissions from fossil fuel consumption, deforestation, and industrial processes.
Major consequences include rising sea levels, extreme weather events, and ecosystem disruption.
International efforts like the Paris Agreement aim to limit warming to 1.5 degrees, but current
commitments fall short of this target. Urgent action is needed including renewable energy transition,
carbon pricing, and international cooperation.
                """.strip(),
                "expected_output": """
2023 set a new global temperature record, with warming reaching 1.2°C above pre-industrial levels
due to greenhouse gas emissions, deforestation, and industrial activity. This has led to rising
sea levels, extreme weather, and ecosystem damage. While the Paris Agreement targets 1.5°C warming
limit, current commitments are insufficient, requiring urgent renewable energy adoption, carbon
pricing, and international cooperation.
                """.strip(),
            },
            best_practices=[
                "Provide reference summaries for comparison when possible",
                "Use faithfulness to ensure no hallucinated information",
                "Focus on coherence and readability of generated summaries",
                "Consider different summary lengths (extractive vs abstractive)",
                "Evaluate coverage of key information points",
                "Test with various document types and lengths",
                "Include domain-specific terminology evaluation for specialized texts",
            ],
            customization_guide="""
Customize this template for your specific summarization use case:

1. **For News Summarization**: Add bias detection and factual accuracy metrics
2. **For Technical Documents**: Focus on terminology preservation and technical accuracy
3. **For Multi-document Summarization**: Add redundancy detection metrics
4. **For Extractive Summarization**: Emphasize relevance and coverage metrics
5. **For Abstractive Summarization**: Focus on faithfulness and coherence

Example customization:
```python
# For legal document summarization with safety requirements
summ_template = SummarizationTemplate()
custom_metrics = summ_template.get_metrics() + ['bias', 'toxicity']
evaluator = Evaluator.from_template(
    summ_template,
    task=legal_summarizer,
    dataset="legal-docs-test",
    custom_metrics=custom_metrics
)
```

For different summary lengths, consider:
- **Short summaries** (1-2 sentences): Focus on key information extraction
- **Medium summaries** (paragraph): Balance detail and conciseness
- **Long summaries** (multiple paragraphs): Ensure structural coherence
            """,
            required_fields=["input", "expected_output"],
            optional_fields=["source_type", "target_length", "summary_type", "domain"],
        )

    def validate_dataset_item(self, item: dict) -> list:
        """Validate summarization dataset item with additional checks."""
        errors = super().validate_dataset_item(item)

        # Summarization specific validations
        if "input" in item:
            input_text = str(item["input"]).strip()
            if len(input_text.split()) < 50:
                errors.append(
                    "Input text should be substantial enough to summarize (at least 50 words)"
                )

        if "expected_output" in item:
            expected = str(item["expected_output"]).strip()
            input_text = str(item.get("input", "")).strip()

            if len(expected) < 10:
                errors.append(
                    "Expected summary should be meaningful (at least 10 characters)"
                )

            # Check if summary is actually shorter than input (basic sanity check)
            if len(expected.split()) >= len(input_text.split()):
                errors.append("Summary should be shorter than the original text")

        return errors

    def recommend_metrics_for_summary_type(self, summary_type: str) -> list:
        """
        Recommend specific metrics based on summary type.

        Args:
            summary_type: Type of summary (extractive, abstractive, headline, etc.)

        Returns:
            List of recommended metric names
        """
        base_metrics = ["faithfulness", "summarization"]

        type_specific = {
            "extractive": ["answer_relevancy"],  # Focus on key information selection
            "abstractive": [
                "answer_relevancy",
                "hallucination",
            ],  # Check for fabrication
            "headline": ["exact_match"],  # Headlines should be precise
            "bullet_points": ["answer_relevancy"],  # Focus on coverage
            "executive_summary": ["answer_relevancy", "bias"],  # Professional tone
            "technical": ["faithfulness"],  # Accuracy is critical
            "creative": ["answer_relevancy"],  # Allow more flexibility
        }

        additional_metrics = type_specific.get(
            summary_type.lower(), ["answer_relevancy"]
        )
        return base_metrics + additional_metrics

    def create_news_summarization_config(
        self, task: any, dataset: str, **kwargs
    ) -> dict:
        """
        Create a specialized configuration for news summarization.

        Args:
            task: The news summarization system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration

        Returns:
            Configuration optimized for news summarization
        """
        # News-specific metrics emphasizing accuracy and bias detection
        news_metrics = ["faithfulness", "summarization", "bias", "answer_relevancy"]

        config = self.create_evaluator_config(
            task=task, dataset=dataset, custom_metrics=news_metrics, **kwargs
        )

        return config

    def create_technical_summarization_config(
        self, task: any, dataset: str, **kwargs
    ) -> dict:
        """
        Create a specialized configuration for technical document summarization.

        Args:
            task: The technical summarization system to evaluate
            dataset: Dataset name
            **kwargs: Additional configuration

        Returns:
            Configuration optimized for technical summarization
        """
        # Technical summarization metrics emphasizing accuracy and completeness
        technical_metrics = ["faithfulness", "summarization", "answer_relevancy"]

        config = self.create_evaluator_config(
            task=task, dataset=dataset, custom_metrics=technical_metrics, **kwargs
        )

        return config
