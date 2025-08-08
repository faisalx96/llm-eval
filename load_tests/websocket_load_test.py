"""
WebSocket load testing for real-time updates in LLM-Eval platform

This script tests WebSocket connections under high concurrent load to validate:
- Connection establishment and teardown
- Message delivery latency
- Connection stability under load
- Memory usage with many concurrent connections
- Message throughput and reliability

Usage:
    python websocket_load_test.py --clients=100 --duration=300 --host=ws://localhost:8000
"""

import asyncio
import json
import time
import statistics
import argparse
import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import websocket
import threading
from concurrent.futures import ThreadPoolExecutor
import ssl

from utils.data_generator import test_data_generator
from config import WEBSOCKET_URL, LOAD_TEST_CONFIG

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class WebSocketMetrics:
    """Metrics collection for WebSocket performance"""
    connection_times: List[float] = field(default_factory=list)
    message_latencies: List[float] = field(default_factory=list)
    messages_sent: int = 0
    messages_received: int = 0
    connections_established: int = 0
    connections_failed: int = 0
    disconnections: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    def add_connection_time(self, time_ms: float):
        self.connection_times.append(time_ms)
        self.connections_established += 1
    
    def add_message_latency(self, latency_ms: float):
        self.message_latencies.append(latency_ms)
    
    def add_error(self, error: str):
        self.errors.append(f"{datetime.now().isoformat()}: {error}")
    
    def get_summary(self) -> Dict[str, Any]:
        total_time = (self.end_time or time.time()) - (self.start_time or time.time())
        
        return {
            'duration_seconds': total_time,
            'connections': {
                'established': self.connections_established,
                'failed': self.connections_failed,
                'success_rate': self.connections_established / max(1, self.connections_established + self.connections_failed) * 100
            },
            'connection_times_ms': {
                'min': min(self.connection_times) if self.connection_times else 0,
                'max': max(self.connection_times) if self.connection_times else 0,
                'avg': statistics.mean(self.connection_times) if self.connection_times else 0,
                'p95': statistics.quantiles(self.connection_times, n=20)[18] if len(self.connection_times) > 20 else 0
            },
            'message_latencies_ms': {
                'min': min(self.message_latencies) if self.message_latencies else 0,
                'max': max(self.message_latencies) if self.message_latencies else 0,
                'avg': statistics.mean(self.message_latencies) if self.message_latencies else 0,
                'p95': statistics.quantiles(self.message_latencies, n=20)[18] if len(self.message_latencies) > 20 else 0
            },
            'messages': {
                'sent': self.messages_sent,
                'received': self.messages_received,
                'delivery_rate': self.messages_received / max(1, self.messages_sent) * 100
            },
            'errors': {
                'count': len(self.errors),
                'recent': self.errors[-5:] if self.errors else []
            }
        }

class WebSocketLoadClient:
    """Individual WebSocket client for load testing"""
    
    def __init__(self, client_id: int, url: str, metrics: WebSocketMetrics):
        self.client_id = client_id
        self.url = url
        self.metrics = metrics
        self.ws: Optional[websocket.WebSocket] = None
        self.connected = False
        self.should_stop = False
        self.sent_messages: Dict[str, float] = {}  # message_id -> timestamp
    
    def connect(self) -> bool:
        """Establish WebSocket connection with timing"""
        start_time = time.time()
        
        try:
            # Configure WebSocket with timeouts
            self.ws = websocket.WebSocket()
            self.ws.settimeout(10)  # 10 second timeout
            
            # Connect to the WebSocket server
            self.ws.connect(self.url)
            
            connection_time = (time.time() - start_time) * 1000  # Convert to ms
            self.metrics.add_connection_time(connection_time)
            self.connected = True
            
            logger.info(f"Client {self.client_id}: Connected in {connection_time:.2f}ms")
            return True
            
        except Exception as e:
            self.metrics.connections_failed += 1
            self.metrics.add_error(f"Client {self.client_id} connection failed: {str(e)}")
            logger.error(f"Client {self.client_id}: Connection failed - {e}")
            return False
    
    def send_message(self, message_type: str = 'run_update') -> bool:
        """Send a test message and track timing"""
        if not self.connected or not self.ws:
            return False
        
        try:
            # Generate realistic message
            run_id = f"load-test-run-{self.client_id}-{int(time.time())}"
            message = test_data_generator.generate_websocket_message(run_id, message_type)
            
            # Add timing information
            message_id = f"{self.client_id}-{len(self.sent_messages)}"
            message['message_id'] = message_id
            
            # Send message and record timestamp
            send_time = time.time()
            self.ws.send(json.dumps(message))
            self.sent_messages[message_id] = send_time
            self.metrics.messages_sent += 1
            
            return True
            
        except Exception as e:
            self.metrics.add_error(f"Client {self.client_id} send failed: {str(e)}")
            return False
    
    def receive_message(self) -> Optional[Dict]:
        """Receive and process message with latency tracking"""
        if not self.connected or not self.ws:
            return None
        
        try:
            # Set a short timeout for non-blocking receive
            self.ws.settimeout(0.1)
            raw_message = self.ws.recv()
            receive_time = time.time()
            
            message = json.loads(raw_message)
            self.metrics.messages_received += 1
            
            # Calculate latency if this is a response to our message
            message_id = message.get('message_id')
            if message_id and message_id in self.sent_messages:
                latency = (receive_time - self.sent_messages[message_id]) * 1000  # ms
                self.metrics.add_message_latency(latency)
                del self.sent_messages[message_id]
            
            return message
            
        except websocket.WebSocketTimeoutException:
            # Expected for non-blocking receive
            return None
        except Exception as e:
            self.metrics.add_error(f"Client {self.client_id} receive failed: {str(e)}")
            return None
    
    def run_test_cycle(self, duration_seconds: int, message_interval: float = 1.0):
        """Run the load test cycle for this client"""
        if not self.connect():
            return
        
        start_time = time.time()
        last_message_time = 0
        
        try:
            while time.time() - start_time < duration_seconds and not self.should_stop:
                current_time = time.time()
                
                # Send message at specified interval
                if current_time - last_message_time >= message_interval:
                    message_type = ['run_update', 'progress', 'completion'][
                        int(current_time) % 3
                    ]
                    self.send_message(message_type)
                    last_message_time = current_time
                
                # Receive any incoming messages
                self.receive_message()
                
                # Small sleep to prevent busy waiting
                time.sleep(0.01)
                
        finally:
            self.disconnect()
    
    def disconnect(self):
        """Clean up WebSocket connection"""
        if self.ws and self.connected:
            try:
                self.ws.close()
                self.metrics.disconnections += 1
                logger.info(f"Client {self.client_id}: Disconnected")
            except Exception as e:
                self.metrics.add_error(f"Client {self.client_id} disconnect failed: {str(e)}")
            finally:
                self.connected = False
                self.ws = None

class WebSocketLoadTester:
    """Main WebSocket load testing orchestrator"""
    
    def __init__(self, url: str, num_clients: int, duration: int):
        self.url = url
        self.num_clients = num_clients
        self.duration = duration
        self.metrics = WebSocketMetrics()
        self.clients: List[WebSocketLoadClient] = []
        self.running = False
    
    def run_load_test(self):
        """Execute the WebSocket load test"""
        logger.info(f"Starting WebSocket load test with {self.num_clients} clients for {self.duration}s")
        logger.info(f"Target URL: {self.url}")
        
        self.metrics.start_time = time.time()
        self.running = True
        
        # Start system resource monitoring
        monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
        monitor_thread.start()
        
        # Create clients
        self.clients = [
            WebSocketLoadClient(i, self.url, self.metrics) 
            for i in range(self.num_clients)
        ]
        
        # Run clients in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.num_clients) as executor:
            # Submit all client tasks
            futures = []
            for client in self.clients:
                # Vary message intervals to create realistic load patterns
                message_interval = 0.5 + (client.client_id % 10) * 0.1  # 0.5 to 1.4 seconds
                
                future = executor.submit(
                    client.run_test_cycle,
                    self.duration,
                    message_interval
                )
                futures.append(future)
            
            # Wait for all clients to complete with progress updates
            completed = 0
            while completed < len(futures):
                time.sleep(5)  # Update every 5 seconds
                completed = sum(1 for f in futures if f.done())
                
                # Log progress
                elapsed = time.time() - self.metrics.start_time
                progress = min(100, (elapsed / self.duration) * 100)
                
                logger.info(f"Progress: {progress:.1f}% - {completed}/{len(futures)} clients completed")
                logger.info(f"Active connections: {sum(1 for c in self.clients if c.connected)}")
                logger.info(f"Messages sent/received: {self.metrics.messages_sent}/{self.metrics.messages_received}")
        
        self.running = False
        self.metrics.end_time = time.time()
        
        # Generate and log results
        summary = self.metrics.get_summary()
        self._log_results(summary)
        
        return summary
    
    def _monitor_resources(self):
        """Monitor system resources during the test"""
        process = psutil.Process()
        initial_memory = process.memory_info().rss
        peak_memory = initial_memory
        
        while self.running:
            try:
                current_memory = process.memory_info().rss
                peak_memory = max(peak_memory, current_memory)
                
                cpu_percent = process.cpu_percent()
                memory_mb = current_memory / (1024 * 1024)
                
                # Log resource usage every 30 seconds
                logger.info(f"Resource usage - CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB")
                
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                break
        
        # Log peak memory usage
        peak_memory_mb = peak_memory / (1024 * 1024)
        memory_increase = ((peak_memory - initial_memory) / initial_memory) * 100
        
        logger.info(f"Peak memory usage: {peak_memory_mb:.1f}MB (increase: {memory_increase:.1f}%)")
        
        # Check for memory leaks
        if memory_increase > LOAD_TEST_CONFIG['targets']['memory_leak_threshold'] * 100:
            logger.warning(f"Potential memory leak detected! Memory increased by {memory_increase:.1f}%")
    
    def _log_results(self, summary: Dict[str, Any]):
        """Log detailed test results"""
        logger.info("=== WebSocket Load Test Results ===")
        logger.info(f"Test Duration: {summary['duration_seconds']:.2f} seconds")
        
        # Connection metrics
        conn_metrics = summary['connections']
        logger.info(f"Connections - Success: {conn_metrics['established']}, Failed: {conn_metrics['failed']}")
        logger.info(f"Connection Success Rate: {conn_metrics['success_rate']:.2f}%")
        
        # Connection timing
        conn_times = summary['connection_times_ms']
        logger.info(f"Connection Times - Avg: {conn_times['avg']:.2f}ms, P95: {conn_times['p95']:.2f}ms")
        
        # Message metrics
        msg_metrics = summary['messages']
        logger.info(f"Messages - Sent: {msg_metrics['sent']}, Received: {msg_metrics['received']}")
        logger.info(f"Message Delivery Rate: {msg_metrics['delivery_rate']:.2f}%")
        
        # Latency metrics
        latencies = summary['message_latencies_ms']
        logger.info(f"Message Latencies - Avg: {latencies['avg']:.2f}ms, P95: {latencies['p95']:.2f}ms")
        
        # Performance targets check
        targets = LOAD_TEST_CONFIG['targets']
        
        if latencies['p95'] > targets['websocket_latency']:
            logger.warning(f"WebSocket latency target MISSED: {latencies['p95']:.2f}ms > {targets['websocket_latency']}ms")
        else:
            logger.info(f"WebSocket latency target MET: {latencies['p95']:.2f}ms <= {targets['websocket_latency']}ms")
        
        # Error summary
        error_count = summary['errors']['count']
        if error_count > 0:
            logger.warning(f"Errors encountered: {error_count}")
            for error in summary['errors']['recent']:
                logger.warning(f"  - {error}")
        else:
            logger.info("No errors encountered during test")

def main():
    """Main entry point for WebSocket load testing"""
    parser = argparse.ArgumentParser(description='WebSocket Load Testing for LLM-Eval')
    
    parser.add_argument('--clients', type=int, default=50, help='Number of concurrent WebSocket clients')
    parser.add_argument('--duration', type=int, default=300, help='Test duration in seconds')
    parser.add_argument('--host', type=str, default=WEBSOCKET_URL, help='WebSocket server URL')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate configuration
    if args.clients > 1000:
        logger.warning("Running with > 1000 clients may overwhelm the system")
    
    if args.duration > 3600:
        logger.warning("Running for > 1 hour may consume significant resources")
    
    # Run the load test
    tester = WebSocketLoadTester(args.host, args.clients, args.duration)
    
    try:
        results = tester.run_load_test()
        
        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"websocket_load_test_results_{timestamp}.json"
        
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to {results_file}")
        
        # Exit with error code if critical targets were missed
        latency_p95 = results['message_latencies_ms']['p95']
        delivery_rate = results['messages']['delivery_rate']
        
        if latency_p95 > LOAD_TEST_CONFIG['targets']['websocket_latency'] or delivery_rate < 95:
            logger.error("Critical performance targets not met!")
            return 1
        
        logger.info("All performance targets met successfully!")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return 1

if __name__ == '__main__':
    exit(main())