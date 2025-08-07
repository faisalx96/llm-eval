"""Template registry and recommendation engine for evaluation templates."""

import re
from typing import Dict, List, Optional, Any, Type
from .base import EvaluationTemplate
from .qa_template import QAEvaluationTemplate
from .summarization_template import SummarizationTemplate
from .classification_template import ClassificationTemplate
from .general_template import GeneralLLMTemplate


# Registry of available templates
TEMPLATE_REGISTRY: Dict[str, Type[EvaluationTemplate]] = {
    'qa': QAEvaluationTemplate,
    'question_answer': QAEvaluationTemplate,
    'question_answering': QAEvaluationTemplate,
    'summarization': SummarizationTemplate,
    'summary': SummarizationTemplate,
    'classification': ClassificationTemplate,
    'classify': ClassificationTemplate,
    'general': GeneralLLMTemplate,
    'general_llm': GeneralLLMTemplate,
    'safety': GeneralLLMTemplate,
}


def get_template(template_name: str) -> EvaluationTemplate:
    """
    Get an evaluation template by name.
    
    Args:
        template_name: Name of the template to retrieve
        
    Returns:
        Instantiated evaluation template
        
    Raises:
        ValueError: If template name is not found
    """
    template_name = template_name.lower().strip()
    
    if template_name not in TEMPLATE_REGISTRY:
        available = list(TEMPLATE_REGISTRY.keys())
        raise ValueError(
            f"Template '{template_name}' not found. "
            f"Available templates: {', '.join(available)}"
        )
    
    template_class = TEMPLATE_REGISTRY[template_name]
    return template_class()


def list_templates() -> Dict[str, Dict[str, Any]]:
    """
    List all available templates with their information.
    
    Returns:
        Dictionary mapping template names to template information
    """
    templates_info = {}
    
    # Get unique template classes (avoid duplicates from aliases)
    unique_classes = {}
    for name, cls in TEMPLATE_REGISTRY.items():
        if cls not in unique_classes.values():
            unique_classes[name] = cls
    
    for name, template_class in unique_classes.items():
        template = template_class()
        config = template.config
        
        templates_info[name] = {
            'name': config.name,
            'description': config.description,
            'use_cases': config.use_cases,
            'metrics': config.metrics,
            'aliases': [k for k, v in TEMPLATE_REGISTRY.items() if v == template_class]
        }
    
    return templates_info


def recommend_template(input_description: str, 
                      sample_data: Optional[Dict[str, Any]] = None,
                      use_case: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Recommend evaluation templates based on input description and context.
    
    Args:
        input_description: Description of the evaluation task or system
        sample_data: Sample input/output data (optional)
        use_case: Specific use case or domain (optional)
        
    Returns:
        List of recommended templates with confidence scores
    """
    recommendations = []
    description_lower = input_description.lower()
    use_case_lower = use_case.lower() if use_case else ""
    
    # Get unique template classes
    unique_classes = {}
    for name, cls in TEMPLATE_REGISTRY.items():
        if cls not in unique_classes.values():
            unique_classes[name] = cls
    
    for name, template_class in unique_classes.items():
        template = template_class()
        confidence = _calculate_template_confidence(
            template, description_lower, use_case_lower, sample_data
        )
        
        if confidence > 0:
            recommendations.append({
                'template_name': name,
                'template_class': template_class,
                'confidence': confidence,
                'name': template.config.name,
                'description': template.config.description,
                'metrics': template.config.metrics,
                'reason': _get_recommendation_reason(template, description_lower, use_case_lower)
            })
    
    # Sort by confidence score
    recommendations.sort(key=lambda x: x['confidence'], reverse=True)
    
    return recommendations


def _calculate_template_confidence(template: EvaluationTemplate,
                                 description: str,
                                 use_case: str,
                                 sample_data: Optional[Dict[str, Any]]) -> float:
    """Calculate confidence score for template recommendation."""
    confidence = 0.0
    
    # Check for keyword matches in description
    confidence += _check_keyword_matches(template, description)
    
    # Check use case matches
    if use_case:
        confidence += _check_use_case_matches(template, use_case)
    
    # Check sample data compatibility
    if sample_data:
        confidence += _check_sample_data_compatibility(template, sample_data)
    
    return min(confidence, 1.0)  # Cap at 1.0


def _check_keyword_matches(template: EvaluationTemplate, description: str) -> float:
    """Check for keyword matches in description."""
    score = 0.0
    
    # Define keywords for each template type
    keywords = {
        'qa': [
            'question', 'answer', 'q&a', 'qa', 'query', 'response', 'ask',
            'rag', 'retrieval', 'knowledge', 'chatbot', 'faq'
        ],
        'summarization': [
            'summary', 'summarize', 'summarization', 'abstract', 'digest',
            'brief', 'overview', 'condensed', 'key points'
        ],
        'classification': [
            'classify', 'classification', 'category', 'categorize', 'label',
            'sentiment', 'intent', 'topic', 'class', 'predict', 'detect'
        ],
        'general': [
            'general', 'safety', 'bias', 'toxicity', 'hallucination',
            'evaluation', 'assessment', 'quality', 'comprehensive'
        ]
    }
    
    # Determine template type
    template_type = 'general'
    if isinstance(template, QAEvaluationTemplate):
        template_type = 'qa'
    elif isinstance(template, SummarizationTemplate):
        template_type = 'summarization'  
    elif isinstance(template, ClassificationTemplate):
        template_type = 'classification'
    
    # Count keyword matches
    relevant_keywords = keywords.get(template_type, [])
    matches = sum(1 for keyword in relevant_keywords if keyword in description)
    
    if matches > 0:
        # Score increases with more matches, but with diminishing returns
        score = min(matches * 0.2, 0.8)
    
    return score


def _check_use_case_matches(template: EvaluationTemplate, use_case: str) -> float:
    """Check if use case matches template use cases."""
    score = 0.0
    
    template_use_cases = [uc.lower() for uc in template.config.use_cases]
    
    # Check for direct matches or substring matches
    for template_use_case in template_use_cases:
        if use_case in template_use_case or template_use_case in use_case:
            score += 0.3
        elif any(word in template_use_case for word in use_case.split()):
            score += 0.1
    
    return min(score, 0.5)  # Cap use case contribution


def _check_sample_data_compatibility(template: EvaluationTemplate, 
                                   sample_data: Dict[str, Any]) -> float:
    """Check if sample data is compatible with template requirements."""
    score = 0.0
    
    # Check required fields
    required_fields = template.get_required_fields()
    present_fields = sum(1 for field in required_fields if field in sample_data)
    
    if present_fields == len(required_fields):
        score += 0.3
    elif present_fields > 0:
        score += 0.1
    
    # Check for template-specific indicators in data
    if isinstance(template, QAEvaluationTemplate):
        if 'input' in sample_data:
            input_text = str(sample_data['input']).lower()
            if '?' in input_text or any(word in input_text for word in ['what', 'how', 'why', 'when', 'where']):
                score += 0.2
    
    elif isinstance(template, SummarizationTemplate):
        if 'input' in sample_data and 'expected_output' in sample_data:
            input_len = len(str(sample_data['input']).split())
            output_len = len(str(sample_data['expected_output']).split())
            if input_len > output_len * 2:  # Input significantly longer than output
                score += 0.2
    
    elif isinstance(template, ClassificationTemplate):
        if 'expected_output' in sample_data:
            expected = sample_data['expected_output']
            if isinstance(expected, str) and len(expected.split()) <= 3:  # Short categorical output
                score += 0.2
            elif 'classes' in sample_data:
                score += 0.2
    
    return min(score, 0.3)  # Cap sample data contribution


def _get_recommendation_reason(template: EvaluationTemplate,
                             description: str,
                             use_case: str) -> str:
    """Generate human-readable reason for recommendation."""
    reasons = []
    
    # Check for strong keyword indicators
    if isinstance(template, QAEvaluationTemplate):
        qa_keywords = ['question', 'answer', 'q&a', 'qa', 'rag', 'chatbot', 'faq']
        matches = [kw for kw in qa_keywords if kw in description]
        if matches:
            reasons.append(f"Keywords suggest Q&A task: {', '.join(matches[:3])}")
    
    elif isinstance(template, SummarizationTemplate):
        sum_keywords = ['summary', 'summarize', 'abstract', 'digest', 'overview']
        matches = [kw for kw in sum_keywords if kw in description]
        if matches:
            reasons.append(f"Keywords suggest summarization task: {', '.join(matches[:3])}")
    
    elif isinstance(template, ClassificationTemplate):
        class_keywords = ['classify', 'classification', 'category', 'sentiment', 'intent']
        matches = [kw for kw in class_keywords if kw in description]
        if matches:
            reasons.append(f"Keywords suggest classification task: {', '.join(matches[:3])}")
    
    # Check use case alignment
    if use_case:
        template_use_cases = template.config.use_cases
        matching_cases = [uc for uc in template_use_cases if use_case.lower() in uc.lower()]
        if matching_cases:
            reasons.append(f"Use case matches: {matching_cases[0]}")
    
    # Default reason if no specific matches
    if not reasons:
        reasons.append("General compatibility with evaluation requirements")
    
    return "; ".join(reasons)


def print_available_templates():
    """Print all available templates in a formatted way."""
    templates_info = list_templates()
    
    print("Available Evaluation Templates")
    print("=" * 50)
    
    for template_name, info in templates_info.items():
        print(f"\n📋 {info['name']} ({template_name})")
        print(f"   {info['description']}")
        print(f"   Metrics: {', '.join(info['metrics'])}")
        print(f"   Use cases: {len(info['use_cases'])} defined")
        if len(info['aliases']) > 1:
            aliases = [a for a in info['aliases'] if a != template_name]
            print(f"   Aliases: {', '.join(aliases)}")
    
    print(f"\nTotal: {len(templates_info)} template types available")
    print("\nUse get_template('template_name') to instantiate a template")
    print("Use recommend_template('description') to get recommendations")