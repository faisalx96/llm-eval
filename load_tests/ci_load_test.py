#!/usr/bin/env python3
"""
Automated load testing for CI/CD pipeline

This script runs a subset of load tests suitable for CI environments:
- Reduced test duration and load to fit CI time constraints
- Automated pass/fail determination based on performance targets
- Structured output for CI system integration
- Exit codes for pipeline decision making

Returns:
    0: All tests passed and performance targets met
    1: One or more tests failed or performance targets missed
    2: Test execution error (setup, configuration, etc.)

Usage:
    python ci_load_test.py [--quick] [--api-only] [--skip-db]
"""

import subprocess
import json
import sys
import os
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import configuration
from config import LOAD_TEST_CONFIG

class CILoadTester:
    """CI-optimized load testing orchestrator"""
    
    def __init__(self, quick_mode: bool = False, api_only: bool = False, skip_db: bool = False):
        self.quick_mode = quick_mode
        self.api_only = api_only
        self.skip_db = skip_db
        self.results_dir = f"ci_results_{int(time.time())}"
        self.results: Dict[str, Dict] = {}
        
        # CI-optimized test parameters
        if quick_mode:
            self.config = {
                'api': {'users': 10, 'spawn_rate': 2, 'duration': '1m'},
                'websocket': {'clients': 15, 'duration': 60},
                'database': {'runs': 50, 'concurrent': 5, 'duration': 120}
            }
        else:
            self.config = {
                'api': {'users': 25, 'spawn_rate': 5, 'duration': '2m'},
                'websocket': {'clients': 30, 'duration': 180},
                'database': {'runs': 200, 'concurrent': 10, 'duration': 300}
            }
        
        # Create results directory
        Path(self.results_dir).mkdir(exist_ok=True)
    
    def check_prerequisites(self) -> bool:
        """Check that all required tools and services are available"""
        print("🔍 Checking prerequisites...")
        
        # Check required Python packages
        required_packages = ['locust', 'websocket-client', 'psutil']
        missing_packages = []
        
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
            except ImportError:
                missing_packages.append(package)
        
        if missing_packages:
            print(f"❌ Missing required packages: {', '.join(missing_packages)}")
            print("Run: pip install " + " ".join(missing_packages))
            return False
        
        # Check API availability
        api_host = os.getenv('LOAD_TEST_API_URL', 'http://localhost:8000')
        
        try:
            import requests
            response = requests.get(f"{api_host}/health", timeout=10)
            if response.status_code == 200:
                print(f"✅ API available at {api_host}")
            else:
                print(f"❌ API health check failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Cannot reach API at {api_host}: {e}")
            return False
        
        # Check required files
        required_files = ['locustfile.py', 'websocket_load_test.py', 'database_performance_test.py']
        for file in required_files:
            if not Path(file).exists():
                print(f"❌ Required file missing: {file}")
                return False
        
        print("✅ All prerequisites met")
        return True
    
    def run_api_load_test(self) -> Tuple[bool, Dict]:
        """Run API load test with CI-appropriate parameters"""
        print(f"🚀 Starting API load test ({self.config['api']['duration']}, {self.config['api']['users']} users)...")
        
        api_host = os.getenv('LOAD_TEST_API_URL', 'http://localhost:8000')
        output_prefix = f"{self.results_dir}/ci_api_test"
        
        cmd = [
            'locust', '-f', 'locustfile.py',
            '--host', api_host,
            '--users', str(self.config['api']['users']),
            '--spawn-rate', str(self.config['api']['spawn_rate']),
            '--run-time', self.config['api']['duration'],
            '--headless',
            '--csv', output_prefix,
            '--html', f"{output_prefix}.html",
            '--loglevel', 'WARNING'  # Reduce noise in CI
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                # Parse results from CSV files
                stats = self._parse_locust_stats(f"{output_prefix}_stats.csv")
                
                # Check performance targets
                target_p95 = LOAD_TEST_CONFIG['targets']['api_response_time_p95']
                passed = self._check_api_targets(stats, target_p95)
                
                test_result = {
                    'status': 'PASSED' if passed else 'FAILED',
                    'stats': stats,
                    'target_p95_ms': target_p95,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
                if passed:
                    print("✅ API load test PASSED")
                else:
                    print("❌ API load test FAILED - performance targets not met")
                
                return passed, test_result
            
            else:
                print(f"❌ API load test execution failed: {result.stderr}")
                return False, {
                    'status': 'EXECUTION_FAILED',
                    'error': result.stderr,
                    'stdout': result.stdout
                }
        
        except subprocess.TimeoutExpired:
            print("❌ API load test timed out")
            return False, {'status': 'TIMEOUT'}
        except Exception as e:
            print(f"❌ API load test error: {e}")
            return False, {'status': 'ERROR', 'error': str(e)}
    
    def run_websocket_test(self) -> Tuple[bool, Dict]:
        """Run WebSocket load test"""
        print(f"🔗 Starting WebSocket test ({self.config['websocket']['duration']}s, {self.config['websocket']['clients']} clients)...")
        
        ws_host = os.getenv('LOAD_TEST_WS_URL', 'ws://localhost:8000/ws')
        
        cmd = [
            'python', 'websocket_load_test.py',
            '--clients', str(self.config['websocket']['clients']),
            '--duration', str(self.config['websocket']['duration']),
            '--host', ws_host
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                # Parse WebSocket results from JSON output files
                ws_results = self._parse_websocket_results()
                
                # Check performance targets
                target_latency = LOAD_TEST_CONFIG['targets']['websocket_latency']
                passed = ws_results.get('message_latencies_ms', {}).get('p95', 999) <= target_latency
                
                test_result = {
                    'status': 'PASSED' if passed else 'FAILED',
                    'results': ws_results,
                    'target_latency_ms': target_latency,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
                if passed:
                    print("✅ WebSocket test PASSED")
                else:
                    print("❌ WebSocket test FAILED - latency targets not met")
                
                return passed, test_result
            
            else:
                print(f"❌ WebSocket test execution failed: {result.stderr}")
                return False, {
                    'status': 'EXECUTION_FAILED',
                    'error': result.stderr,
                    'stdout': result.stdout
                }
        
        except subprocess.TimeoutExpired:
            print("❌ WebSocket test timed out")
            return False, {'status': 'TIMEOUT'}
        except Exception as e:
            print(f"❌ WebSocket test error: {e}")
            return False, {'status': 'ERROR', 'error': str(e)}
    
    def run_database_test(self) -> Tuple[bool, Dict]:
        """Run database performance test"""
        if self.skip_db:
            print("⏭️  Skipping database test as requested")
            return True, {'status': 'SKIPPED'}
        
        print(f"🗄️  Starting database test ({self.config['database']['duration']}s, {self.config['database']['runs']} runs)...")
        
        db_path = f"{self.results_dir}/ci_test.db"
        
        cmd = [
            'python', 'database_performance_test.py',
            '--runs', str(self.config['database']['runs']),
            '--concurrent', str(self.config['database']['concurrent']),
            '--duration', str(self.config['database']['duration']),
            '--db-path', db_path,
            '--clean'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            
            if result.returncode == 0:
                # Parse database results
                db_results = self._parse_database_results(result.stdout)
                
                # Check performance targets
                target_query_time = LOAD_TEST_CONFIG['targets']['database_query_time']
                passed = self._check_database_targets(db_results, target_query_time)
                
                test_result = {
                    'status': 'PASSED' if passed else 'FAILED',
                    'results': db_results,
                    'target_query_time_ms': target_query_time,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
                if passed:
                    print("✅ Database test PASSED")
                else:
                    print("❌ Database test FAILED - query performance targets not met")
                
                return passed, test_result
            
            else:
                print(f"❌ Database test execution failed: {result.stderr}")
                return False, {
                    'status': 'EXECUTION_FAILED',
                    'error': result.stderr,
                    'stdout': result.stdout
                }
        
        except subprocess.TimeoutExpired:
            print("❌ Database test timed out")
            return False, {'status': 'TIMEOUT'}
        except Exception as e:
            print(f"❌ Database test error: {e}")
            return False, {'status': 'ERROR', 'error': str(e)}
    
    def _parse_locust_stats(self, csv_file: str) -> Dict:
        """Parse Locust statistics from CSV file"""
        stats = {}
        
        try:
            with open(csv_file, 'r') as f:
                lines = f.readlines()
                if len(lines) > 1:  # Skip header
                    for line in lines[1:]:
                        parts = line.strip().split(',')
                        if len(parts) >= 10:
                            name = parts[0]
                            stats[name] = {
                                'requests': int(parts[1]),
                                'failures': int(parts[2]),
                                'avg_response_time': float(parts[3]),
                                'min_response_time': float(parts[4]),
                                'max_response_time': float(parts[5]),
                                'median_response_time': float(parts[6]),
                                'requests_per_second': float(parts[9]) if parts[9] else 0
                            }
        except Exception as e:
            print(f"Warning: Could not parse Locust stats: {e}")
        
        return stats
    
    def _parse_websocket_results(self) -> Dict:
        """Parse WebSocket test results from JSON files"""
        # Look for WebSocket results JSON files
        json_files = list(Path('.').glob('websocket_load_test_results_*.json'))
        
        if json_files:
            # Use the most recent file
            latest_file = max(json_files, key=os.path.getctime)
            try:
                with open(latest_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not parse WebSocket results: {e}")
        
        return {}
    
    def _parse_database_results(self, stdout: str) -> Dict:
        """Parse database test results from stdout"""
        results = {}
        
        # Look for JSON results files
        json_files = list(Path('.').glob('database_performance_results_*.json'))
        
        if json_files:
            # Use the most recent file
            latest_file = max(json_files, key=os.path.getctime)
            try:
                with open(latest_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not parse database results: {e}")
        
        return {}
    
    def _check_api_targets(self, stats: Dict, target_p95: int) -> bool:
        """Check if API performance targets are met"""
        if not stats:
            return False
        
        # Check each operation's performance
        for operation, data in stats.items():
            if operation.startswith('Aggregated'):
                continue
            
            # Use max_response_time as proxy for p95 (Locust doesn't export p95 in CSV)
            if data.get('max_response_time', 999999) > target_p95 * 2:  # Allow 2x target for max
                print(f"  ❌ {operation}: max response time {data['max_response_time']}ms > {target_p95 * 2}ms")
                return False
            
            # Check failure rate
            requests = data.get('requests', 0)
            failures = data.get('failures', 0)
            if requests > 0 and (failures / requests) > 0.01:  # 1% error threshold
                print(f"  ❌ {operation}: failure rate {failures/requests*100:.1f}% > 1%")
                return False
        
        return True
    
    def _check_database_targets(self, results: Dict, target_query_time: int) -> bool:
        """Check if database performance targets are met"""
        query_performance = results.get('query_performance', {})
        
        if not query_performance:
            return False
        
        for operation, stats in query_performance.items():
            p95_time = stats.get('p95_ms', 999999)
            if p95_time > target_query_time:
                print(f"  ❌ {operation}: p95 {p95_time:.1f}ms > {target_query_time}ms")
                return False
        
        return True
    
    def generate_ci_report(self) -> None:
        """Generate CI-friendly test report"""
        timestamp = datetime.now().isoformat()
        
        report = {
            'timestamp': timestamp,
            'test_mode': 'quick' if self.quick_mode else 'standard',
            'configuration': self.config,
            'results': self.results,
            'overall_status': 'PASSED' if all(
                result.get('status') in ['PASSED', 'SKIPPED'] 
                for result in self.results.values()
            ) else 'FAILED'
        }
        
        # Save JSON report
        report_file = f"{self.results_dir}/ci_test_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📊 CI test report saved: {report_file}")
        
        # Print summary
        print(f"\n📋 CI Load Test Summary")
        print(f"{'='*50}")
        print(f"Overall Status: {report['overall_status']}")
        print(f"Test Mode: {report['test_mode']}")
        print(f"Timestamp: {timestamp}")
        
        for test_name, result in self.results.items():
            status = result.get('status', 'UNKNOWN')
            print(f"  {test_name}: {status}")
        
        if report['overall_status'] == 'FAILED':
            print(f"\n❌ Some tests failed. Check detailed logs in {self.results_dir}/")
        else:
            print(f"\n✅ All tests passed successfully!")
    
    def run_all_tests(self) -> int:
        """Run all configured tests and return exit code"""
        print("🚀 Starting CI Load Testing Suite")
        print(f"Mode: {'Quick' if self.quick_mode else 'Standard'}")
        print(f"API Only: {self.api_only}")
        print(f"Skip DB: {self.skip_db}")
        print("")
        
        if not self.check_prerequisites():
            print("❌ Prerequisites not met")
            return 2
        
        all_passed = True
        
        # Run API load test
        try:
            api_passed, api_result = self.run_api_load_test()
            self.results['api_load_test'] = api_result
            all_passed = all_passed and api_passed
        except Exception as e:
            print(f"❌ API test error: {e}")
            self.results['api_load_test'] = {'status': 'ERROR', 'error': str(e)}
            all_passed = False
        
        if not self.api_only:
            # Run WebSocket test
            try:
                ws_passed, ws_result = self.run_websocket_test()
                self.results['websocket_test'] = ws_result
                all_passed = all_passed and ws_passed
            except Exception as e:
                print(f"❌ WebSocket test error: {e}")
                self.results['websocket_test'] = {'status': 'ERROR', 'error': str(e)}
                all_passed = False
            
            # Run database test
            try:
                db_passed, db_result = self.run_database_test()
                self.results['database_test'] = db_result
                if db_result.get('status') != 'SKIPPED':
                    all_passed = all_passed and db_passed
            except Exception as e:
                print(f"❌ Database test error: {e}")
                self.results['database_test'] = {'status': 'ERROR', 'error': str(e)}
                all_passed = False
        
        # Generate report
        self.generate_ci_report()
        
        return 0 if all_passed else 1

def main():
    parser = argparse.ArgumentParser(
        description='CI Load Testing for LLM-Eval',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0: All tests passed and performance targets met
  1: One or more tests failed or performance targets missed
  2: Test execution error (setup, configuration, etc.)

Environment Variables:
  LOAD_TEST_API_URL: API server URL (default: http://localhost:8000)
  LOAD_TEST_WS_URL: WebSocket URL (default: ws://localhost:8000/ws)
        """
    )
    
    parser.add_argument('--quick', action='store_true', 
                       help='Run quick tests with reduced load (faster, less comprehensive)')
    parser.add_argument('--api-only', action='store_true',
                       help='Run only API load tests (skip WebSocket and database)')
    parser.add_argument('--skip-db', action='store_true',
                       help='Skip database performance tests')
    
    args = parser.parse_args()
    
    tester = CILoadTester(
        quick_mode=args.quick,
        api_only=args.api_only,
        skip_db=args.skip_db
    )
    
    try:
        return tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        return 2
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        return 2

if __name__ == '__main__':
    sys.exit(main())