"""Test data management utilities."""

import json
import random
from pathlib import Path
from typing import Dict, List, Any, Optional


class TestDataManager:
    """Manages test datasets for consistent evaluation testing."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize with data directory."""
        self.data_dir = data_dir or Path(__file__).parent
        self.datasets_file = self.data_dir / "sample_datasets.json"
    
    def get_dataset(self, name: str) -> Dict[str, Any]:
        """Get a dataset by name."""
        with open(self.datasets_file) as f:
            datasets = json.load(f)
        
        if name not in datasets:
            raise ValueError(f"Dataset '{name}' not found. Available: {list(datasets.keys())}")
        
        return datasets[name]
    
    def get_dataset_items(self, name: str) -> List[Dict[str, Any]]:
        """Get items from a dataset."""
        dataset = self.get_dataset(name)
        return dataset["items"]
    
    def create_performance_dataset(self, size: int = 100) -> List[Dict[str, Any]]:
        """Create a large dataset for performance testing."""
        items = []
        
        templates = [
            "What is the result of {a} + {b}?",
            "Who is the author of {book}?",
            "What is the capital of {country}?",
            "How do you calculate {concept}?",
            "When did {event} happen?"
        ]
        
        sample_data = {
            'a': [1, 5, 10, 25, 100],
            'b': [2, 7, 15, 30, 200],
            'book': ['1984', 'To Kill a Mockingbird', 'Pride and Prejudice', 'The Great Gatsby'],
            'country': ['France', 'Germany', 'Japan', 'Brazil', 'Australia'],
            'concept': ['area of a circle', 'compound interest', 'velocity', 'probability'],
            'event': ['World War I', 'the Renaissance', 'the Industrial Revolution', 'the Moon landing']
        }
        
        for i in range(size):
            template = random.choice(templates)
            
            # Fill template with random data
            item_data = {}
            for key in sample_data:
                if f'{{{key}}}' in template:
                    item_data[key] = random.choice(sample_data[key])
            
            input_text = template.format(**item_data)
            
            # Generate expected output based on template
            if "result of" in template and "+" in template:
                expected = str(item_data['a'] + item_data['b'])
            elif "capital of" in template:
                capitals = {
                    'France': 'Paris',
                    'Germany': 'Berlin', 
                    'Japan': 'Tokyo',
                    'Brazil': 'Brasília',
                    'Australia': 'Canberra'
                }
                expected = capitals.get(item_data.get('country', ''), 'Unknown')
            else:
                expected = f"Answer for: {input_text}"
            
            items.append({
                "id": f"perf_item_{i}",
                "input": input_text,
                "expected_output": expected,
                "metadata": {
                    "template": template,
                    "generated": True,
                    "index": i
                }
            })
        
        return items
    
    def create_error_prone_dataset(self, size: int = 20, error_rate: float = 0.3) -> List[Dict[str, Any]]:
        """Create a dataset designed to trigger various error conditions."""
        items = []
        
        error_inputs = [
            "",  # Empty input
            None,  # None input
            " " * 1000,  # Very long whitespace
            "🚀" * 100,  # Unicode characters
            "\\n\\t\\r",  # Escape characters
            '{"invalid": json}',  # Invalid JSON-like
            "SELECT * FROM users; DROP TABLE users;",  # SQL injection-like
            "<script>alert('xss')</script>",  # XSS-like
        ]
        
        normal_inputs = [
            "What is machine learning?",
            "Explain quantum computing",
            "How does photosynthesis work?",
            "What are the benefits of exercise?",
            "Describe the water cycle"
        ]
        
        for i in range(size):
            if random.random() < error_rate:
                input_text = random.choice(error_inputs)
                expected = "Error handling test"
            else:
                input_text = random.choice(normal_inputs)
                expected = f"Normal response to: {input_text}"
            
            items.append({
                "id": f"error_item_{i}",
                "input": input_text,
                "expected_output": expected,
                "metadata": {
                    "is_error_test": random.random() < error_rate,
                    "index": i
                }
            })
        
        return items
    
    def create_multilingual_dataset(self, size: int = 15) -> List[Dict[str, Any]]:
        """Create a dataset with multilingual inputs."""
        multilingual_data = [
            {"input": "Bonjour, comment allez-vous?", "expected": "Hello, how are you?", "lang": "fr"},
            {"input": "Hola, ¿cómo estás?", "expected": "Hello, how are you?", "lang": "es"},
            {"input": "Hallo, wie geht es dir?", "expected": "Hello, how are you?", "lang": "de"},
            {"input": "こんにちは、元気ですか？", "expected": "Hello, how are you?", "lang": "ja"},
            {"input": "Привет, как дела?", "expected": "Hello, how are you?", "lang": "ru"},
            {"input": "你好，你好吗？", "expected": "Hello, how are you?", "lang": "zh"},
            {"input": "Ciao, come stai?", "expected": "Hello, how are you?", "lang": "it"},
            {"input": "Olá, como você está?", "expected": "Hello, how are you?", "lang": "pt"},
            {"input": "안녕하세요, 어떻게 지내세요?", "expected": "Hello, how are you?", "lang": "ko"},
            {"input": "مرحبا، كيف حالك؟", "expected": "Hello, how are you?", "lang": "ar"},
        ]
        
        items = []
        for i in range(min(size, len(multilingual_data))):
            data = multilingual_data[i]
            items.append({
                "id": f"multi_item_{i}",
                "input": data["input"],
                "expected_output": data["expected"],
                "metadata": {
                    "language": data["lang"],
                    "type": "translation"
                }
            })
        
        return items
    
    def save_dataset(self, name: str, items: List[Dict[str, Any]], description: str = ""):
        """Save a new dataset to the datasets file."""
        with open(self.datasets_file) as f:
            datasets = json.load(f)
        
        datasets[name] = {
            "description": description,
            "items": items
        }
        
        with open(self.datasets_file, 'w') as f:
            json.dump(datasets, f, indent=2, ensure_ascii=False)
    
    def list_datasets(self) -> List[str]:
        """List all available datasets."""
        with open(self.datasets_file) as f:
            datasets = json.load(f)
        
        return list(datasets.keys())
    
    def get_dataset_info(self, name: str) -> Dict[str, Any]:
        """Get information about a dataset."""
        dataset = self.get_dataset(name)
        items = dataset["items"]
        
        return {
            "name": name,
            "description": dataset.get("description", ""),
            "size": len(items),
            "has_metadata": any("metadata" in item for item in items),
            "categories": list(set(
                item.get("metadata", {}).get("category")
                for item in items
                if item.get("metadata", {}).get("category")
            )),
            "sample_item": items[0] if items else None
        }


# Global instance for easy access
test_data_manager = TestDataManager()


def get_test_dataset(name: str) -> List[Dict[str, Any]]:
    """Convenience function to get test dataset items."""
    return test_data_manager.get_dataset_items(name)


def create_test_performance_data(size: int = 100) -> List[Dict[str, Any]]:
    """Convenience function to create performance test data."""
    return test_data_manager.create_performance_dataset(size)


def create_test_error_data(size: int = 20, error_rate: float = 0.3) -> List[Dict[str, Any]]:
    """Convenience function to create error-prone test data."""
    return test_data_manager.create_error_prone_dataset(size, error_rate)