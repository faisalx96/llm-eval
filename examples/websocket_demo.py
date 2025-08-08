"""
WebSocket Demo - Real-time Evaluation Progress Updates

This script demonstrates how to use the WebSocket endpoints to receive
real-time progress updates during evaluation runs.

Run this script to:
1. Start a mock evaluation with WebSocket progress tracking
2. Connect to WebSocket endpoints to monitor progress
3. See real-time updates as evaluations complete

Usage:
    python examples/websocket_demo.py
"""

import asyncio
import json
import time
from typing import Dict, Any
import websockets
from concurrent.futures import ThreadPoolExecutor

from llm_eval import Evaluator


def simple_llm_task(input_text: str) -> str:
    """
    A simple mock LLM task that takes some time to complete.
    
    Args:
        input_text: The input text to process
        
    Returns:
        A response string
    """
    # Simulate processing time
    time.sleep(0.5)
    
    # Simple response generation
    if "question" in input_text.lower():
        return f"The answer to '{input_text}' is 42."
    elif "hello" in input_text.lower():
        return "Hello! How can I help you today?"
    else:
        return f"I processed your input: {input_text}"


def exact_match_metric(output: str, expected: str) -> bool:
    """Simple exact match metric."""
    return output.strip().lower() == expected.strip().lower()


def length_metric(output: str) -> int:
    """Simple length metric."""
    return len(output)


async def websocket_client_progress(run_id: str):
    """
    Connect to the run progress WebSocket and display updates.
    
    Args:
        run_id: The run ID to monitor
    """
    uri = f"ws://localhost:8000/ws/runs/{run_id}/progress"
    
    print(f"🔌 Connecting to progress WebSocket for run: {run_id}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to progress WebSocket")
            
            while True:
                try:
                    # Receive message
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(message)
                    
                    # Display progress update
                    event_type = data.get("event_type", "unknown")
                    print(f"📡 Progress Update [{event_type}]:")
                    
                    if event_type == "progress":
                        progress_data = data.get("data", {})
                        completed = progress_data.get("completed_items", 0)
                        total = progress_data.get("total_items", 0)
                        success_rate = progress_data.get("success_rate", 0.0)
                        print(f"   Progress: {completed}/{total} items ({success_rate:.1%} success)")
                        
                    elif event_type == "result":
                        result_data = data.get("data", {})
                        item_idx = result_data.get("item_index", "?")
                        execution_time = result_data.get("execution_time", 0)
                        print(f"   Item {item_idx} completed in {execution_time:.2f}s")
                        
                    elif event_type == "error":
                        error_data = data.get("data", {})
                        item_idx = error_data.get("item_index", "?")
                        error_msg = error_data.get("message", "Unknown error")
                        print(f"   ❌ Item {item_idx} failed: {error_msg}")
                        
                    elif event_type == "completed":
                        completion_data = data.get("data", {})
                        total = completion_data.get("total_items", 0)
                        success_rate = completion_data.get("success_rate", 0.0)
                        exec_time = completion_data.get("execution_time", 0.0)
                        print(f"   🎉 Evaluation completed! {total} items, {success_rate:.1%} success, {exec_time:.2f}s total")
                        break
                        
                    elif event_type == "ping":
                        # Send pong response
                        await websocket.send(json.dumps({"type": "pong"}))
                        
                    else:
                        print(f"   Data: {json.dumps(data, indent=2)}")
                        
                except asyncio.TimeoutError:
                    # No message received, continue listening
                    pass
                    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")


async def websocket_client_status():
    """
    Connect to the runs status WebSocket and display updates.
    """
    uri = "ws://localhost:8000/ws/runs/status"
    
    print("🔌 Connecting to status WebSocket")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to status WebSocket")
            
            # Listen for a short time to see status updates
            for _ in range(10):  # Listen for 10 seconds
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(message)
                    
                    event_type = data.get("event_type", "unknown")
                    print(f"📡 Status Update [{event_type}]:")
                    
                    if event_type == "initial_stats":
                        stats = data.get("data", {})
                        print(f"   Current stats: {json.dumps(stats, indent=2)}")
                        
                    elif event_type == "status_update":
                        update_data = data.get("data", {})
                        update_type = update_data.get("type", "unknown")
                        print(f"   Update type: {update_type}")
                        
                    elif event_type == "ping":
                        # Send pong response
                        await websocket.send(json.dumps({"type": "pong"}))
                        
                    else:
                        print(f"   Data: {json.dumps(data, indent=2)}")
                        
                except asyncio.TimeoutError:
                    # No message received, continue listening
                    pass
                    
    except Exception as e:
        print(f"❌ Status WebSocket error: {e}")


async def run_evaluation_with_websocket():
    """
    Run an evaluation with WebSocket progress tracking.
    """
    print("🚀 Starting WebSocket Evaluation Demo")
    print("=" * 50)
    
    # Generate a run ID for this evaluation
    run_id = f"websocket-demo-{int(time.time())}"
    
    # Start WebSocket clients
    progress_task = asyncio.create_task(websocket_client_progress(run_id))
    status_task = asyncio.create_task(websocket_client_status())
    
    # Give WebSocket clients time to connect
    await asyncio.sleep(1)
    
    print(f"📊 Starting evaluation with run_id: {run_id}")
    
    try:
        # Create evaluator with run_id for WebSocket tracking
        evaluator = Evaluator(
            task=simple_llm_task,
            dataset="demo-questions",  # Make sure this dataset exists in Langfuse
            metrics=[exact_match_metric, length_metric],
            config={
                'max_concurrency': 2,
                'timeout': 10.0,
                'run_name': f'websocket-demo-{int(time.time())}'
            },
            run_id=run_id  # Enable WebSocket progress updates
        )
        
        # Run evaluation asynchronously
        print("🔄 Running evaluation...")
        result = await evaluator.arun(show_progress=True, show_table=False)
        
        print("\n📋 Evaluation Summary:")
        result.print_summary()
        
    except Exception as e:
        print(f"❌ Evaluation error: {e}")
        
    # Wait a bit for final WebSocket messages
    await asyncio.sleep(2)
    
    # Cancel WebSocket tasks
    progress_task.cancel()
    status_task.cancel()
    
    try:
        await progress_task
    except asyncio.CancelledError:
        pass
        
    try:
        await status_task
    except asyncio.CancelledError:
        pass
    
    print("\n✅ Demo completed!")


def run_api_server():
    """
    Run the API server in a separate thread.
    """
    import subprocess
    import sys
    
    print("🖥️  Starting API server...")
    
    # Start the API server
    subprocess.run([
        sys.executable, "-m", "llm_eval.api.main"
    ])


async def main():
    """
    Main demo function.
    """
    print("LLM-Eval WebSocket Demo")
    print("=" * 50)
    print()
    print("This demo shows real-time progress updates during evaluation.")
    print("Make sure you have:")
    print("1. Langfuse credentials configured")
    print("2. A dataset named 'demo-questions' in Langfuse")
    print("3. The API server running on localhost:8000")
    print()
    
    response = input("Ready to start? (y/N): ")
    if response.lower() != 'y':
        print("Demo cancelled.")
        return
    
    print("\n" + "=" * 50)
    
    # Check if API server is running
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:8000/api/health') as resp:
                if resp.status == 200:
                    print("✅ API server is running")
                else:
                    print("❌ API server is not responding correctly")
                    return
    except Exception:
        print("❌ API server is not running. Please start it first:")
        print("   python -m llm_eval.api.main")
        return
    
    # Run the evaluation with WebSocket monitoring
    await run_evaluation_with_websocket()


if __name__ == "__main__":
    # Run the demo
    asyncio.run(main())