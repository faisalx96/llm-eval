"""
Database performance testing for LLM-Eval with 1000+ evaluation runs

This script tests database performance under heavy load conditions:
- Creating and storing 1000+ evaluation runs
- Complex query performance with large datasets
- Concurrent read/write operations
- Index effectiveness and query optimization
- Memory usage and connection pooling
- Data consistency under concurrent access

Usage:
    python database_performance_test.py --runs=1000 --concurrent=20 --duration=600
"""

import asyncio
import time
import statistics
import argparse
import logging
import psutil
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import sqlite3
import threading
from contextlib import contextmanager

from utils.data_generator import test_data_generator
from config import DATABASE_URL, LOAD_TEST_CONFIG

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class DatabaseMetrics:
    """Metrics collection for database performance testing"""
    query_times: Dict[str, List[float]] = field(default_factory=lambda: {
        'insert': [],
        'select_single': [],
        'select_paginated': [],
        'select_filtered': [],
        'update': [],
        'delete': [],
        'complex_join': [],
        'aggregate': [],
        'search': []
    })
    
    operations_count: Dict[str, int] = field(default_factory=lambda: {
        'insert': 0,
        'select_single': 0,
        'select_paginated': 0,
        'select_filtered': 0,
        'update': 0,
        'delete': 0,
        'complex_join': 0,
        'aggregate': 0,
        'search': 0,
        'errors': 0
    })
    
    concurrent_operations: int = 0
    peak_concurrent_operations: int = 0
    connection_pool_stats: Dict[str, int] = field(default_factory=dict)
    memory_usage: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    def record_query(self, operation: str, duration_ms: float, success: bool = True):
        """Record a query operation with timing"""
        if success:
            self.query_times[operation].append(duration_ms)
            self.operations_count[operation] += 1
        else:
            self.operations_count['errors'] += 1
            self.errors.append(f"{operation} failed at {datetime.now().isoformat()}")
    
    def start_concurrent_operation(self):
        """Track concurrent operation start"""
        self.concurrent_operations += 1
        self.peak_concurrent_operations = max(
            self.peak_concurrent_operations, 
            self.concurrent_operations
        )
    
    def end_concurrent_operation(self):
        """Track concurrent operation end"""
        self.concurrent_operations = max(0, self.concurrent_operations - 1)
    
    def get_summary(self) -> Dict[str, Any]:
        """Generate comprehensive performance summary"""
        total_time = (self.end_time or time.time()) - (self.start_time or time.time())
        
        summary = {
            'test_duration_seconds': total_time,
            'total_operations': sum(self.operations_count.values()) - self.operations_count['errors'],
            'operations_per_second': (sum(self.operations_count.values()) - self.operations_count['errors']) / max(1, total_time),
            'errors': {
                'count': self.operations_count['errors'],
                'rate': self.operations_count['errors'] / max(1, sum(self.operations_count.values())) * 100,
                'recent': self.errors[-10:]
            },
            'concurrency': {
                'peak_concurrent_operations': self.peak_concurrent_operations
            },
            'query_performance': {}
        }
        
        # Calculate statistics for each operation type
        for operation, times in self.query_times.items():
            if times:
                summary['query_performance'][operation] = {
                    'count': len(times),
                    'avg_ms': statistics.mean(times),
                    'min_ms': min(times),
                    'max_ms': max(times),
                    'p50_ms': statistics.median(times),
                    'p95_ms': statistics.quantiles(times, n=20)[18] if len(times) > 20 else max(times),
                    'p99_ms': statistics.quantiles(times, n=100)[98] if len(times) > 100 else max(times)
                }
        
        return summary

class DatabaseConnectionManager:
    """Manages database connections with connection pooling simulation"""
    
    def __init__(self, db_path: str, max_connections: int = 20):
        self.db_path = db_path
        self.max_connections = max_connections
        self.active_connections = 0
        self.connection_lock = threading.Lock()
    
    @contextmanager
    def get_connection(self):
        """Get a database connection with connection limiting"""
        with self.connection_lock:
            if self.active_connections >= self.max_connections:
                raise Exception("Connection pool exhausted")
            self.active_connections += 1
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row  # Enable dict-like access
            yield conn
        finally:
            if conn:
                conn.close()
            with self.connection_lock:
                self.active_connections -= 1

class DatabasePerformanceTester:
    """Main database performance testing class"""
    
    def __init__(self, db_path: str, num_runs: int = 1000, concurrent_workers: int = 10):
        self.db_path = db_path
        self.num_runs = num_runs
        self.concurrent_workers = concurrent_workers
        self.metrics = DatabaseMetrics()
        self.connection_manager = DatabaseConnectionManager(db_path)
        self.test_run_ids: List[str] = []
        
        # Setup database schema
        self._setup_database()
    
    def _setup_database(self):
        """Initialize database with required tables and indexes"""
        with self.connection_manager.get_connection() as conn:
            # Create evaluation_runs table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    template_id TEXT,
                    template_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_seconds INTEGER,
                    total_items INTEGER DEFAULT 0,
                    processed_items INTEGER DEFAULT 0,
                    failed_items INTEGER DEFAULT 0,
                    langfuse_session_id TEXT,
                    dataset_name TEXT,
                    metrics_config TEXT,  -- JSON
                    metadata TEXT         -- JSON
                )
            ''')
            
            # Create run_items table for detailed testing
            conn.execute('''
                CREATE TABLE IF NOT EXISTS run_items (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    input_data TEXT NOT NULL,     -- JSON
                    output_data TEXT,            -- JSON
                    expected_output TEXT,        -- JSON
                    scores TEXT,                 -- JSON
                    status TEXT NOT NULL,
                    error_message TEXT,
                    response_time REAL,
                    tokens_used INTEGER,
                    cost REAL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES evaluation_runs (id)
                )
            ''')
            
            # Create performance-critical indexes
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_runs_status ON evaluation_runs(status)',
                'CREATE INDEX IF NOT EXISTS idx_runs_created_at ON evaluation_runs(created_at)',
                'CREATE INDEX IF NOT EXISTS idx_runs_template ON evaluation_runs(template_name)',
                'CREATE INDEX IF NOT EXISTS idx_runs_dataset ON evaluation_runs(dataset_name)',
                'CREATE INDEX IF NOT EXISTS idx_runs_composite ON evaluation_runs(status, created_at, template_name)',
                'CREATE INDEX IF NOT EXISTS idx_items_run_id ON run_items(run_id)',
                'CREATE INDEX IF NOT EXISTS idx_items_status ON run_items(status)',
                'CREATE INDEX IF NOT EXISTS idx_items_scores ON run_items(run_id, status)'
            ]
            
            for index_sql in indexes:
                conn.execute(index_sql)
            
            conn.commit()
            logger.info("Database schema and indexes created/verified")
    
    def _measure_query_time(self, operation: str, query_func):
        """Decorator to measure query execution time"""
        self.metrics.start_concurrent_operation()
        start_time = time.time()
        
        try:
            result = query_func()
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_query(operation, duration_ms, True)
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_query(operation, duration_ms, False)
            logger.error(f"{operation} failed: {e}")
            raise
        finally:
            self.metrics.end_concurrent_operation()
    
    def insert_evaluation_runs(self, batch_size: int = 100) -> List[str]:
        """Insert evaluation runs in batches for performance"""
        logger.info(f"Inserting {self.num_runs} evaluation runs in batches of {batch_size}")
        
        def batch_insert():
            runs_data = test_data_generator.generate_run_batch(self.num_runs)
            inserted_ids = []
            
            with self.connection_manager.get_connection() as conn:
                for i in range(0, len(runs_data), batch_size):
                    batch = runs_data[i:i + batch_size]
                    
                    # Prepare batch insert
                    insert_sql = '''
                        INSERT INTO evaluation_runs (
                            id, name, description, status, template_id, template_name,
                            created_at, updated_at, started_at, completed_at, duration_seconds,
                            total_items, processed_items, failed_items, langfuse_session_id,
                            dataset_name, metrics_config, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                    
                    batch_values = []
                    for run in batch:
                        batch_values.append((
                            run['id'], run['name'], run['description'], run['status'],
                            run['template_id'], run['template_name'],
                            run['created_at'], run['updated_at'], run['started_at'], run['completed_at'],
                            run['duration_seconds'], run['total_items'], run['processed_items'],
                            run['failed_items'], run['langfuse_session_id'], run['dataset_name'],
                            json.dumps(run['metrics_config']), json.dumps(run['metadata'])
                        ))
                        inserted_ids.append(run['id'])
                    
                    conn.executemany(insert_sql, batch_values)
                    conn.commit()
                    
                    logger.info(f"Inserted batch {i // batch_size + 1}/{(len(runs_data) - 1) // batch_size + 1}")
            
            return inserted_ids
        
        run_ids = self._measure_query_time('insert', batch_insert)
        self.test_run_ids = run_ids
        return run_ids
    
    def test_single_select_queries(self, num_queries: int = 100):
        """Test single-record SELECT performance"""
        logger.info(f"Testing {num_queries} single SELECT queries")
        
        for _ in range(num_queries):
            run_id = random.choice(self.test_run_ids)
            
            def single_select():
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.execute(
                        'SELECT * FROM evaluation_runs WHERE id = ?', 
                        (run_id,)
                    )
                    return cursor.fetchone()
            
            self._measure_query_time('select_single', single_select)
    
    def test_paginated_queries(self, num_queries: int = 50):
        """Test paginated LIST queries with different page sizes"""
        logger.info(f"Testing {num_queries} paginated queries")
        
        page_sizes = [10, 20, 50, 100]
        
        for _ in range(num_queries):
            limit = random.choice(page_sizes)
            offset = random.randint(0, max(0, self.num_runs - limit))
            
            def paginated_select():
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.execute(
                        'SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ? OFFSET ?',
                        (limit, offset)
                    )
                    return cursor.fetchall()
            
            self._measure_query_time('select_paginated', paginated_select)
    
    def test_filtered_queries(self, num_queries: int = 100):
        """Test filtered queries with indexes"""
        logger.info(f"Testing {num_queries} filtered queries")
        
        statuses = ['completed', 'failed', 'running', 'pending']
        templates = ['qa_template', 'classification_template', 'summarization_template']
        
        for _ in range(num_queries):
            filter_type = random.choice(['status', 'template', 'date_range', 'composite'])
            
            def filtered_select():
                with self.connection_manager.get_connection() as conn:
                    if filter_type == 'status':
                        status = random.choice(statuses)
                        cursor = conn.execute(
                            'SELECT * FROM evaluation_runs WHERE status = ? ORDER BY created_at DESC LIMIT 50',
                            (status,)
                        )
                    elif filter_type == 'template':
                        template = random.choice(templates)
                        cursor = conn.execute(
                            'SELECT * FROM evaluation_runs WHERE template_name = ? ORDER BY created_at DESC LIMIT 50',
                            (template,)
                        )
                    elif filter_type == 'date_range':
                        start_date = (datetime.now() - timedelta(days=30)).isoformat()
                        cursor = conn.execute(
                            'SELECT * FROM evaluation_runs WHERE created_at > ? ORDER BY created_at DESC LIMIT 50',
                            (start_date,)
                        )
                    else:  # composite
                        status = random.choice(statuses)
                        template = random.choice(templates)
                        cursor = conn.execute(
                            '''SELECT * FROM evaluation_runs 
                               WHERE status = ? AND template_name = ? 
                               ORDER BY created_at DESC LIMIT 20''',
                            (status, template)
                        )
                    
                    return cursor.fetchall()
            
            self._measure_query_time('select_filtered', filtered_select)
    
    def test_update_operations(self, num_updates: int = 200):
        """Test UPDATE performance"""
        logger.info(f"Testing {num_updates} UPDATE operations")
        
        for _ in range(num_updates):
            run_id = random.choice(self.test_run_ids)
            
            def update_run():
                with self.connection_manager.get_connection() as conn:
                    new_status = random.choice(['completed', 'failed'])
                    processed_items = random.randint(50, 500)
                    
                    conn.execute(
                        '''UPDATE evaluation_runs 
                           SET status = ?, processed_items = ?, updated_at = ? 
                           WHERE id = ?''',
                        (new_status, processed_items, datetime.now().isoformat(), run_id)
                    )
                    conn.commit()
            
            self._measure_query_time('update', update_run)
    
    def test_complex_joins(self, num_queries: int = 50):
        """Test complex JOIN operations"""
        logger.info(f"Testing {num_queries} complex JOIN queries")
        
        # First, insert some run items for testing
        self._insert_test_run_items()
        
        for _ in range(num_queries):
            def complex_join():
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.execute('''
                        SELECT 
                            r.id, r.name, r.status, 
                            COUNT(i.id) as item_count,
                            AVG(i.response_time) as avg_response_time,
                            SUM(CASE WHEN i.status = 'failed' THEN 1 ELSE 0 END) as failed_items
                        FROM evaluation_runs r
                        LEFT JOIN run_items i ON r.id = i.run_id
                        WHERE r.status = 'completed'
                        GROUP BY r.id, r.name, r.status
                        HAVING COUNT(i.id) > 0
                        ORDER BY avg_response_time DESC
                        LIMIT 50
                    ''')
                    return cursor.fetchall()
            
            self._measure_query_time('complex_join', complex_join)
    
    def test_aggregate_queries(self, num_queries: int = 30):
        """Test aggregate and analytical queries"""
        logger.info(f"Testing {num_queries} aggregate queries")
        
        for _ in range(num_queries):
            def aggregate_query():
                with self.connection_manager.get_connection() as conn:
                    # Random aggregate query
                    queries = [
                        '''SELECT status, COUNT(*) as count, AVG(duration_seconds) as avg_duration 
                           FROM evaluation_runs GROUP BY status''',
                        '''SELECT template_name, COUNT(*) as runs, 
                           AVG(processed_items) as avg_processed,
                           AVG(failed_items) as avg_failed
                           FROM evaluation_runs WHERE template_name IS NOT NULL
                           GROUP BY template_name''',
                        '''SELECT DATE(created_at) as date, COUNT(*) as daily_runs
                           FROM evaluation_runs 
                           GROUP BY DATE(created_at) 
                           ORDER BY date DESC LIMIT 30''',
                        '''SELECT 
                           COUNT(*) as total_runs,
                           SUM(total_items) as total_items,
                           AVG(duration_seconds) as avg_duration,
                           MAX(processed_items) as max_processed
                           FROM evaluation_runs WHERE status = 'completed' '''
                    ]
                    
                    query = random.choice(queries)
                    cursor = conn.execute(query)
                    return cursor.fetchall()
            
            self._measure_query_time('aggregate', aggregate_query)
    
    def test_search_queries(self, num_queries: int = 50):
        """Test search queries with LIKE operations"""
        logger.info(f"Testing {num_queries} search queries")
        
        search_terms = ['test', 'qa', 'classification', 'load', 'performance', 'run', 'eval']
        
        for _ in range(num_queries):
            search_term = random.choice(search_terms)
            
            def search_query():
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.execute(
                        '''SELECT * FROM evaluation_runs 
                           WHERE name LIKE ? OR description LIKE ?
                           ORDER BY created_at DESC LIMIT 50''',
                        (f'%{search_term}%', f'%{search_term}%')
                    )
                    return cursor.fetchall()
            
            self._measure_query_time('search', search_query)
    
    def _insert_test_run_items(self):
        """Insert test run items for JOIN testing"""
        logger.info("Inserting test run items for JOIN queries")
        
        # Insert items for a subset of runs
        selected_runs = random.sample(self.test_run_ids, min(100, len(self.test_run_ids)))
        
        with self.connection_manager.get_connection() as conn:
            for run_id in selected_runs:
                items = test_data_generator.generate_run_items(run_id, random.randint(10, 50))
                
                insert_sql = '''
                    INSERT INTO run_items (
                        id, run_id, input_data, output_data, scores,
                        status, error_message, response_time, tokens_used,
                        cost, created_at, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                
                for item in items:
                    conn.execute(insert_sql, (
                        item['id'], item['run_id'],
                        json.dumps(item['input_data']),
                        json.dumps(item['output_data']),
                        json.dumps(item['scores']),
                        item['status'], item['error_message'],
                        item['response_time'], item['tokens_used'],
                        item['cost'], item['created_at'], item['processed_at']
                    ))
                
                conn.commit()
    
    def run_concurrent_test(self, duration_seconds: int = 300):
        """Run concurrent operations to test database under load"""
        logger.info(f"Starting concurrent database test for {duration_seconds} seconds with {self.concurrent_workers} workers")
        
        self.metrics.start_time = time.time()
        
        # Start resource monitoring
        monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
        monitor_thread.start()
        
        # Define test operations with weights
        operations = [
            (self.test_single_select_queries, 30, 20),    # (function, weight, batch_size)
            (self.test_paginated_queries, 20, 10),
            (self.test_filtered_queries, 25, 15),
            (self.test_update_operations, 10, 5),
            (self.test_complex_joins, 8, 3),
            (self.test_aggregate_queries, 5, 2),
            (self.test_search_queries, 12, 8)
        ]
        
        with ThreadPoolExecutor(max_workers=self.concurrent_workers) as executor:
            futures = []
            end_time = time.time() + duration_seconds
            
            while time.time() < end_time:
                # Submit random operations based on weights
                operation, weight, batch_size = random.choices(
                    operations, 
                    weights=[op[1] for op in operations]
                )[0]
                
                future = executor.submit(operation, batch_size)
                futures.append(future)
                
                # Limit concurrent futures to prevent memory issues
                if len(futures) > self.concurrent_workers * 2:
                    # Wait for some to complete
                    for completed_future in as_completed(futures[:self.concurrent_workers], timeout=1):
                        futures.remove(completed_future)
                
                # Small delay to control load
                time.sleep(random.uniform(0.1, 0.5))
            
            # Wait for remaining operations to complete
            logger.info("Waiting for remaining operations to complete...")
            for future in as_completed(futures, timeout=30):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Operation failed: {e}")
        
        self.metrics.end_time = time.time()
        logger.info("Concurrent test completed")
    
    def _monitor_resources(self):
        """Monitor system resources during testing"""
        process = psutil.Process()
        initial_memory = process.memory_info().rss
        
        while time.time() < (self.metrics.start_time + 3600):  # Max 1 hour monitoring
            try:
                current_memory = process.memory_info().rss
                memory_mb = current_memory / (1024 * 1024)
                self.metrics.memory_usage.append(memory_mb)
                
                cpu_percent = process.cpu_percent()
                
                logger.info(f"Resource usage - CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB")
                
                time.sleep(30)  # Monitor every 30 seconds
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                break
    
    def run_full_performance_test(self):
        """Execute the complete database performance test suite"""
        logger.info("Starting comprehensive database performance test")
        
        try:
            # Phase 1: Data insertion
            logger.info("=== Phase 1: Data Insertion ===")
            self.insert_evaluation_runs()
            
            # Phase 2: Individual query type testing
            logger.info("=== Phase 2: Query Performance Testing ===")
            self.test_single_select_queries(200)
            self.test_paginated_queries(100)
            self.test_filtered_queries(150)
            self.test_update_operations(100)
            self.test_complex_joins(30)
            self.test_aggregate_queries(20)
            self.test_search_queries(80)
            
            # Phase 3: Concurrent load testing
            logger.info("=== Phase 3: Concurrent Load Testing ===")
            self.run_concurrent_test(600)  # 10 minutes
            
            # Generate and return results
            summary = self.metrics.get_summary()
            self._log_results(summary)
            
            return summary
            
        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            raise
    
    def _log_results(self, summary: Dict[str, Any]):
        """Log comprehensive test results"""
        logger.info("=== Database Performance Test Results ===")
        logger.info(f"Test Duration: {summary['test_duration_seconds']:.2f} seconds")
        logger.info(f"Total Operations: {summary['total_operations']}")
        logger.info(f"Operations/Second: {summary['operations_per_second']:.2f}")
        
        # Error summary
        if summary['errors']['count'] > 0:
            logger.warning(f"Errors: {summary['errors']['count']} ({summary['errors']['rate']:.2f}%)")
        else:
            logger.info("No errors encountered")
        
        # Performance by operation type
        logger.info("\nQuery Performance by Type:")
        target_time = LOAD_TEST_CONFIG['targets']['database_query_time']
        
        for operation, stats in summary['query_performance'].items():
            avg_time = stats['avg_ms']
            p95_time = stats['p95_ms']
            
            status = "✓" if p95_time <= target_time else "✗"
            logger.info(f"{status} {operation}: {stats['count']} ops, "
                       f"avg: {avg_time:.2f}ms, p95: {p95_time:.2f}ms")
            
            if p95_time > target_time:
                logger.warning(f"  Target missed: {p95_time:.2f}ms > {target_time}ms")
        
        # Concurrency stats
        logger.info(f"\nPeak Concurrent Operations: {summary['concurrency']['peak_concurrent_operations']}")

def main():
    """Main entry point for database performance testing"""
    parser = argparse.ArgumentParser(description='Database Performance Testing for LLM-Eval')
    
    parser.add_argument('--runs', type=int, default=1000, help='Number of evaluation runs to create')
    parser.add_argument('--concurrent', type=int, default=20, help='Number of concurrent workers')
    parser.add_argument('--duration', type=int, default=600, help='Concurrent test duration in seconds')
    parser.add_argument('--db-path', type=str, default='load_test.db', help='Database file path')
    parser.add_argument('--clean', action='store_true', help='Clean database before testing')
    
    args = parser.parse_args()
    
    # Clean database if requested
    if args.clean:
        import os
        if os.path.exists(args.db_path):
            os.remove(args.db_path)
            logger.info(f"Cleaned database: {args.db_path}")
    
    # Run the performance test
    tester = DatabasePerformanceTester(args.db_path, args.runs, args.concurrent)
    
    try:
        results = tester.run_full_performance_test()
        
        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"database_performance_results_{timestamp}.json"
        
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to {results_file}")
        
        # Check if targets were met
        target_time = LOAD_TEST_CONFIG['targets']['database_query_time']
        failed_operations = []
        
        for operation, stats in results['query_performance'].items():
            if stats['p95_ms'] > target_time:
                failed_operations.append(f"{operation}: {stats['p95_ms']:.2f}ms")
        
        if failed_operations:
            logger.error("Performance targets not met for:")
            for failure in failed_operations:
                logger.error(f"  - {failure}")
            return 1
        
        logger.info("All performance targets met successfully!")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return 1

if __name__ == '__main__':
    exit(main())