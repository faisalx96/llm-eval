"""Sample datasets for Q&A evaluation template."""

from typing import List, Dict, Any


def get_qa_samples() -> List[Dict[str, Any]]:
    """Get sample Q&A dataset for testing and demonstration."""
    return [
        {
            "input": "What is the capital of France?",
            "expected_output": "Paris",
            "context": "France is a country in Western Europe. Its capital and largest city is Paris.",
            "question_type": "factual",
            "difficulty": "easy"
        },
        {
            "input": "How does photosynthesis work?",
            "expected_output": "Photosynthesis is the process by which plants convert light energy, usually from the sun, into chemical energy stored in glucose. Plants use chlorophyll to absorb light, take in carbon dioxide from the air, and water from their roots. The light energy drives chemical reactions that combine CO2 and H2O to produce glucose (C6H12O6) and oxygen as a byproduct.",
            "context": "Photosynthesis is a fundamental biological process that occurs in plants, algae, and some bacteria.",
            "question_type": "analytical",
            "difficulty": "medium"
        },
        {
            "input": "What are the main benefits of renewable energy?",
            "expected_output": "The main benefits of renewable energy include: 1) Environmental benefits - reduced greenhouse gas emissions and air pollution, 2) Economic benefits - job creation and energy independence, 3) Sustainability - inexhaustible energy sources, 4) Health benefits - cleaner air quality, and 5) Technological advancement - driving innovation in energy storage and efficiency.",
            "context": "Renewable energy sources include solar, wind, hydro, geothermal, and biomass energy.",
            "question_type": "subjective",
            "difficulty": "medium"
        },
        {
            "input": "Is the Earth round?",
            "expected_output": "Yes",
            "context": "The Earth is an oblate spheroid, meaning it's roughly spherical but slightly flattened at the poles.",
            "question_type": "yes_no",
            "difficulty": "easy"
        },
        {
            "input": "What is 15% of 240?",
            "expected_output": "36",
            "context": "Mathematical calculation: 15% of 240 = 0.15 × 240 = 36",
            "question_type": "numerical",
            "difficulty": "easy"
        },
        {
            "input": "According to the passage, what was the primary cause of the economic downturn?",
            "expected_output": "According to the passage, the primary cause was the sudden increase in interest rates that led to reduced consumer spending and business investment.",
            "context": "The economic downturn of 2023 was primarily triggered by the central bank's decision to raise interest rates by 3% over six months. This policy change was intended to combat inflation but resulted in reduced consumer spending and a significant decline in business investment. Companies began laying off workers, creating a cycle of reduced economic activity.",
            "question_type": "contextual",
            "difficulty": "hard"
        },
        {
            "input": "Which programming language is best for machine learning?",
            "expected_output": "Python is widely considered the best programming language for machine learning due to its extensive libraries (scikit-learn, TensorFlow, PyTorch), readable syntax, large community, and strong ecosystem. However, the 'best' choice can depend on specific use cases - R is excellent for statistics, Julia for high-performance computing, and JavaScript for web-based ML applications.",
            "context": "Machine learning can be implemented in various programming languages, each with their own strengths.",
            "question_type": "subjective",
            "difficulty": "medium"
        },
        {
            "input": "What year did World War II end?",
            "expected_output": "1945",
            "context": "World War II ended in 1945, with Germany surrendering in May and Japan surrendering in September after the atomic bombings.",
            "question_type": "factual",
            "difficulty": "easy"
        }
    ]


def get_rag_samples() -> List[Dict[str, Any]]:
    """Get sample RAG (Retrieval-Augmented Generation) dataset."""
    return [
        {
            "input": "What are the company's vacation policies?",
            "expected_output": "According to the employee handbook, full-time employees receive 15 days of paid vacation annually, with the option to carry over up to 5 unused days to the next year. Vacation requests must be submitted at least 2 weeks in advance and approved by your direct supervisor.",
            "context": "Employee Handbook Section 4.2: Vacation Policy - Full-time employees are entitled to 15 days of paid vacation per calendar year. Unused vacation days up to a maximum of 5 days may be carried over to the following year. All vacation requests must be submitted through the HR portal at least 14 days prior to the requested dates and require supervisor approval.",
            "question_type": "contextual",
            "difficulty": "medium"
        },
        {
            "input": "How do I reset my password?",
            "expected_output": "To reset your password, go to the login page and click 'Forgot Password'. Enter your email address and you'll receive a reset link within 5 minutes. Click the link in the email and follow the instructions to create a new password. For security, passwords must be at least 8 characters with a mix of letters, numbers, and symbols.",
            "context": "IT Support Documentation: Password Reset Procedure - Users can reset their passwords by clicking the 'Forgot Password' link on the login screen. After entering their registered email address, a password reset link will be sent within 5 minutes. The new password must meet security requirements: minimum 8 characters, containing at least one uppercase letter, one lowercase letter, one number, and one special character.",
            "question_type": "contextual",
            "difficulty": "easy"
        }
    ]


def get_factual_qa_samples() -> List[Dict[str, Any]]:
    """Get sample factual Q&A dataset with definitive answers."""
    return [
        {
            "input": "What is the chemical symbol for gold?",
            "expected_output": "Au",
            "question_type": "factual",
            "difficulty": "easy"
        },
        {
            "input": "How many bones are in the adult human body?",
            "expected_output": "206",
            "question_type": "factual",
            "difficulty": "medium"
        },
        {
            "input": "What is the largest planet in our solar system?",
            "expected_output": "Jupiter",
            "question_type": "factual",
            "difficulty": "easy"
        },
        {
            "input": "In what year was the Declaration of Independence signed?",
            "expected_output": "1776",
            "question_type": "factual",
            "difficulty": "easy"
        },
        {
            "input": "What is the speed of light in a vacuum?",
            "expected_output": "299,792,458 meters per second",
            "question_type": "factual",
            "difficulty": "hard"
        }
    ]