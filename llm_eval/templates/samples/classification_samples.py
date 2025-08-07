"""Sample datasets for classification evaluation template."""

from typing import List, Dict, Any


def get_classification_samples() -> List[Dict[str, Any]]:
    """Get sample classification dataset for testing and demonstration."""
    return [
        {
            "input": "I absolutely love this product! It exceeded all my expectations and works perfectly.",
            "expected_output": "positive",
            "classes": ["positive", "negative", "neutral"],
            "confidence": 0.95
        },
        {
            "input": "This is the worst purchase I've ever made. Complete waste of money.",
            "expected_output": "negative", 
            "classes": ["positive", "negative", "neutral"],
            "confidence": 0.98
        },
        {
            "input": "The product is okay, nothing special but it gets the job done.",
            "expected_output": "neutral",
            "classes": ["positive", "negative", "neutral"],
            "confidence": 0.72
        },
        {
            "input": "Can you help me book a flight to New York for next Tuesday?",
            "expected_output": "book_flight",
            "classes": ["book_flight", "check_weather", "get_directions", "make_reservation", "general_info"],
            "confidence": 0.89
        },
        {
            "input": "What's the weather like in Los Angeles today?",
            "expected_output": "check_weather",
            "classes": ["book_flight", "check_weather", "get_directions", "make_reservation", "general_info"],
            "confidence": 0.96
        },
        {
            "input": "How do I get from the airport to downtown?",
            "expected_output": "get_directions",
            "classes": ["book_flight", "check_weather", "get_directions", "make_reservation", "general_info"],
            "confidence": 0.88
        },
        {
            "input": "I need to make a dinner reservation for 4 people at 7 PM.",
            "expected_output": "make_reservation",
            "classes": ["book_flight", "check_weather", "get_directions", "make_reservation", "general_info"],
            "confidence": 0.91
        },
        {
            "input": "Tell me about the history of artificial intelligence.",
            "expected_output": "general_info",
            "classes": ["book_flight", "check_weather", "get_directions", "make_reservation", "general_info"],
            "confidence": 0.83
        }
    ]


def get_sentiment_analysis_samples() -> List[Dict[str, Any]]:
    """Get sample sentiment analysis dataset."""
    return [
        {
            "input": "This movie was absolutely fantastic! The acting was superb and the plot was engaging.",
            "expected_output": "positive",
            "classes": ["positive", "negative", "neutral"]
        },
        {
            "input": "Terrible customer service. I waited on hold for 45 minutes only to be disconnected.",
            "expected_output": "negative",
            "classes": ["positive", "negative", "neutral"]
        },
        {
            "input": "The restaurant was decent. Food was average, service was acceptable.",
            "expected_output": "neutral",
            "classes": ["positive", "negative", "neutral"] 
        },
        {
            "input": "Outstanding quality and fast delivery! Will definitely order again.",
            "expected_output": "positive",
            "classes": ["positive", "negative", "neutral"]
        },
        {
            "input": "Product arrived damaged and return process was complicated.",
            "expected_output": "negative",
            "classes": ["positive", "negative", "neutral"]
        },
        {
            "input": "It's an adequate solution for basic needs.",
            "expected_output": "neutral",
            "classes": ["positive", "negative", "neutral"]
        }
    ]


def get_intent_classification_samples() -> List[Dict[str, Any]]:
    """Get sample intent classification dataset for chatbots."""
    return [
        {
            "input": "I want to cancel my subscription",
            "expected_output": "cancel_subscription",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        },
        {
            "input": "Why was I charged twice this month?",
            "expected_output": "billing_inquiry",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        },
        {
            "input": "The app keeps crashing when I try to log in",
            "expected_output": "technical_support",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        },
        {
            "input": "What features are included in the premium plan?",
            "expected_output": "product_info",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        },
        {
            "input": "I need to update my email address",
            "expected_output": "account_management",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        },
        {
            "input": "How do I upgrade to the pro version?",
            "expected_output": "product_info",
            "classes": ["cancel_subscription", "billing_inquiry", "technical_support", "product_info", "account_management"]
        }
    ]


def get_topic_classification_samples() -> List[Dict[str, Any]]:
    """Get sample topic classification dataset."""
    return [
        {
            "input": "Scientists have discovered a new species of deep-sea fish in the Mariana Trench.",
            "expected_output": "science",
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        },
        {
            "input": "The latest smartphone features an improved camera and longer battery life.",
            "expected_output": "technology", 
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        },
        {
            "input": "The championship game will be played next Sunday at the stadium.",
            "expected_output": "sports",
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        },
        {
            "input": "The senator announced new legislation to address climate change.",
            "expected_output": "politics",
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        },
        {
            "input": "The blockbuster movie broke box office records in its opening weekend.",
            "expected_output": "entertainment",
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        },
        {
            "input": "New research shows that regular exercise can reduce the risk of heart disease.",
            "expected_output": "health",
            "classes": ["science", "technology", "sports", "politics", "entertainment", "health"]
        }
    ]


def get_multilabel_classification_samples() -> List[Dict[str, Any]]:
    """Get sample multi-label classification dataset."""
    return [
        {
            "input": "Urgent: Server outage affecting payment processing system",
            "expected_output": ["urgent", "technical", "payment"],
            "classes": ["urgent", "technical", "payment", "customer_service", "billing", "security"],
            "multi_label": True
        },
        {
            "input": "Customer complaint about billing discrepancy and poor service",
            "expected_output": ["customer_service", "billing"],
            "classes": ["urgent", "technical", "payment", "customer_service", "billing", "security"],
            "multi_label": True
        },
        {
            "input": "Security breach detected in user authentication system - immediate action required",
            "expected_output": ["urgent", "security", "technical"],
            "classes": ["urgent", "technical", "payment", "customer_service", "billing", "security"],
            "multi_label": True
        },
        {
            "input": "Routine maintenance scheduled for this weekend",
            "expected_output": ["technical"],
            "classes": ["urgent", "technical", "payment", "customer_service", "billing", "security"],
            "multi_label": True
        }
    ]