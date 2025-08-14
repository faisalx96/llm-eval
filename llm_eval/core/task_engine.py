"""Async Task Execution Engine for UI-driven evaluations.

This module provides a task execution engine that manages evaluation tasks
in an async queue with progress tracking, state management, and control operations.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

import psutil
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..models.run_models import EvaluationConfig, EvaluationRun, TaskExecution
from ..storage.database import get_database_manager
from ..api.websocket_manager import WebSocketManager
from ..core.evaluator import Evaluator
from ..utils.errors import LLMEvalError

logger = logging.getLogger(__name__)


class TaskState:
    """Task execution state constants."""
    
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionProgress:
    """Progress tracking for task execution."""
    
    def __init__(self, execution_id: str, total_steps: int = 0):
        self.execution_id = execution_id
        self.total_steps = total_steps
        self.completed_steps = 0
        self.current_step = ""
        self.progress_percentage = 0.0
        self.start_time = datetime.now(timezone.utc)
        self.estimated_completion: Optional[datetime] = None
    
    def update_step(self, step_description: str, completed_steps: int = None):
        """Update current step and progress."""
        self.current_step = step_description
        if completed_steps is not None:
            self.completed_steps = completed_steps
        
        if self.total_steps > 0:
            self.progress_percentage = (self.completed_steps / self.total_steps) * 100.0
            
            # Estimate completion time
            if self.completed_steps > 0:
                elapsed = datetime.now(timezone.utc) - self.start_time
                avg_time_per_step = elapsed.total_seconds() / self.completed_steps
                remaining_steps = self.total_steps - self.completed_steps
                remaining_seconds = avg_time_per_step * remaining_steps
                self.estimated_completion = datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)
    
    def increment_step(self, step_description: str):
        """Increment completed steps by 1."""
        self.update_step(step_description, self.completed_steps + 1)


class TaskExecutionEngine:
    """Async task execution engine with queue management."""
    
    def __init__(self, max_concurrent_tasks: int = 3, websocket_manager: Optional[WebSocketManager] = None):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.websocket_manager = websocket_manager
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.paused_tasks: Set[str] = set()
        self.cancelled_tasks: Set[str] = set()
        self.progress_trackers: Dict[str, ExecutionProgress] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the task execution engine."""
        if self._running:
            logger.warning("Task execution engine is already running")
            return
        
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Task execution engine started")
    
    async def stop(self):
        """Stop the task execution engine."""
        self._running = False
        
        # Cancel all running tasks
        for task_id in list(self.running_tasks.keys()):
            await self.cancel_task(task_id)
        
        # Cancel worker task
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Task execution engine stopped")
    
    async def queue_task(
        self,
        config_id: str,
        task_name: str,
        priority: int = 0,
        created_by: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> str:
        """Queue a new evaluation task for execution."""
        try:
            logger.info(f"Queueing task: {task_name} (config: {config_id})")
            
            # Generate execution key
            execution_key = f"task_{uuid.uuid4().hex[:12]}"
            
            # Create task execution record
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                # Get configuration
                config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
                if not config:
                    raise LLMEvalError(f"Configuration {config_id} not found")
                
                # Create task execution record
                execution = TaskExecution(
                    execution_key=execution_key,
                    task_name=task_name,
                    config_id=config_id,
                    status=TaskState.QUEUED,
                    priority=priority,
                    created_by=created_by,
                    project_id=project_id
                )
                
                db.add(execution)
                db.commit()
                db.refresh(execution)
                
                execution_id = str(execution.id)
            
            # Add to queue
            await self.task_queue.put({
                'execution_id': execution_id,
                'execution_key': execution_key,
                'config_id': config_id,
                'task_name': task_name,
                'priority': priority,
                'created_by': created_by,
                'project_id': project_id
            })
            
            logger.info(f"Task queued with execution ID: {execution_id}")
            return execution_id
            
        except Exception as e:
            logger.error(f"Error queueing task: {e}")
            raise LLMEvalError(f"Failed to queue task: {str(e)}")
    
    async def pause_task(self, execution_id: str) -> bool:
        """Pause a running task."""
        try:
            logger.info(f"Pausing task: {execution_id}")
            
            if execution_id not in self.running_tasks:
                logger.warning(f"Task {execution_id} is not running")
                return False
            
            # Add to paused set
            self.paused_tasks.add(execution_id)
            
            # Update database
            await self._update_task_status(execution_id, TaskState.PAUSED)
            
            # Notify via WebSocket
            await self._notify_task_update(execution_id, {"status": TaskState.PAUSED})
            
            logger.info(f"Task paused: {execution_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error pausing task {execution_id}: {e}")
            return False
    
    async def resume_task(self, execution_id: str) -> bool:
        """Resume a paused task."""
        try:
            logger.info(f"Resuming task: {execution_id}")
            
            if execution_id not in self.paused_tasks:
                logger.warning(f"Task {execution_id} is not paused")
                return False
            
            # Remove from paused set
            self.paused_tasks.remove(execution_id)
            
            # Update database
            await self._update_task_status(execution_id, TaskState.RUNNING)
            
            # Notify via WebSocket
            await self._notify_task_update(execution_id, {"status": TaskState.RUNNING})
            
            logger.info(f"Task resumed: {execution_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error resuming task {execution_id}: {e}")
            return False
    
    async def cancel_task(self, execution_id: str) -> bool:
        """Cancel a task (queued, running, or paused)."""
        try:
            logger.info(f"Cancelling task: {execution_id}")
            
            # Add to cancelled set
            self.cancelled_tasks.add(execution_id)
            
            # Cancel running asyncio task if exists
            if execution_id in self.running_tasks:
                task = self.running_tasks[execution_id]
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
                del self.running_tasks[execution_id]
            
            # Remove from paused if it was paused
            self.paused_tasks.discard(execution_id)
            
            # Update database
            await self._update_task_status(execution_id, TaskState.CANCELLED)
            
            # Notify via WebSocket
            await self._notify_task_update(execution_id, {"status": TaskState.CANCELLED})
            
            logger.info(f"Task cancelled: {execution_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling task {execution_id}: {e}")
            return False
    
    async def get_task_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a task."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
                if not execution:
                    return None
                
                return execution.to_dict()
                
        except Exception as e:
            logger.error(f"Error getting task status {execution_id}: {e}")
            return None
    
    async def list_active_tasks(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all active (queued, running, paused) tasks."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                query = db.query(TaskExecution).filter(
                    TaskExecution.status.in_([TaskState.QUEUED, TaskState.RUNNING, TaskState.PAUSED])
                )
                
                if project_id:
                    query = query.filter(TaskExecution.project_id == project_id)
                
                executions = query.order_by(desc(TaskExecution.priority), TaskExecution.queued_at).all()
                
                return [execution.to_dict() for execution in executions]
                
        except Exception as e:
            logger.error(f"Error listing active tasks: {e}")
            return []
    
    async def _worker_loop(self):
        """Main worker loop that processes queued tasks."""
        logger.info("Task execution worker loop started")
        
        while self._running:
            try:
                # Check if we can start more tasks
                if len(self.running_tasks) >= self.max_concurrent_tasks:
                    await asyncio.sleep(1)
                    continue
                
                # Get next task from queue (with timeout to allow checking for stop)
                try:
                    task_data = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                execution_id = task_data['execution_id']
                
                # Check if task was cancelled while in queue
                if execution_id in self.cancelled_tasks:
                    self.cancelled_tasks.remove(execution_id)
                    continue
                
                # Start task execution
                task = asyncio.create_task(self._execute_task(task_data))
                self.running_tasks[execution_id] = task
                
                logger.info(f"Started task execution: {execution_id}")
                
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(1)
    
    async def _execute_task(self, task_data: Dict[str, Any]):
        """Execute a single evaluation task."""
        execution_id = task_data['execution_id']
        
        try:
            logger.info(f"Executing task: {execution_id}")
            
            # Update status to running
            await self._update_task_status(execution_id, TaskState.RUNNING)
            await self._notify_task_update(execution_id, {"status": TaskState.RUNNING})
            
            # Get configuration and create evaluator
            config = await self._get_configuration(task_data['config_id'])
            if not config:
                raise LLMEvalError(f"Configuration {task_data['config_id']} not found")
            
            # Initialize progress tracker
            progress = ExecutionProgress(execution_id)
            self.progress_trackers[execution_id] = progress
            
            # Create evaluation run
            run_id = await self._create_evaluation_run(config, task_data)
            await self._update_task_run_id(execution_id, run_id)
            
            # Execute evaluation with progress tracking
            await self._run_evaluation(config, run_id, progress)
            
            # Mark as completed
            await self._update_task_status(execution_id, TaskState.COMPLETED)
            await self._notify_task_update(execution_id, {
                "status": TaskState.COMPLETED,
                "progress_percentage": 100.0,
                "completed_at": datetime.now(timezone.utc).isoformat()
            })
            
            logger.info(f"Task completed successfully: {execution_id}")
            
        except asyncio.CancelledError:
            logger.info(f"Task cancelled: {execution_id}")
            await self._update_task_status(execution_id, TaskState.CANCELLED)
            raise
            
        except Exception as e:
            logger.error(f"Task failed: {execution_id} - {e}")
            await self._update_task_status(execution_id, TaskState.FAILED, str(e))
            await self._notify_task_update(execution_id, {
                "status": TaskState.FAILED,
                "error_message": str(e)
            })
            
        finally:
            # Cleanup
            if execution_id in self.running_tasks:
                del self.running_tasks[execution_id]
            if execution_id in self.progress_trackers:
                del self.progress_trackers[execution_id]
            self.paused_tasks.discard(execution_id)
            self.cancelled_tasks.discard(execution_id)
    
    async def _run_evaluation(self, config: Dict[str, Any], run_id: str, progress: ExecutionProgress):
        """Run the actual evaluation with progress tracking."""
        # Estimate total steps for progress tracking
        dataset_size = config.get('dataset_config', {}).get('estimated_size', 100)
        metrics_count = len(config.get('metrics_config', {}).get('metrics', []))
        total_steps = dataset_size + metrics_count + 3  # +3 for setup, dataset loading, finalization
        
        progress.total_steps = total_steps
        
        # Step 1: Initialize evaluator
        progress.update_step("Initializing evaluator...", 1)
        await self._notify_progress_update(progress)
        
        evaluator = Evaluator()
        
        # Check for pause/cancel
        await self._check_pause_cancel(progress.execution_id)
        
        # Step 2: Load dataset
        progress.update_step("Loading dataset...", 2)
        await self._notify_progress_update(progress)
        
        # Simulate dataset loading (in real implementation, this would load from Langfuse)
        await asyncio.sleep(0.5)  # Simulate work
        
        # Check for pause/cancel
        await self._check_pause_cancel(progress.execution_id)
        
        # Step 3: Run evaluation items
        current_step = 3
        for i in range(dataset_size):
            if i % 10 == 0:  # Update progress every 10 items
                progress.update_step(f"Evaluating item {i+1}/{dataset_size}...", current_step + i)
                await self._notify_progress_update(progress)
            
            # Check for pause/cancel every few items
            if i % 5 == 0:
                await self._check_pause_cancel(progress.execution_id)
            
            # Simulate evaluation work
            await asyncio.sleep(0.01)  # Small delay to simulate work
        
        current_step += dataset_size
        
        # Step 4: Calculate metrics
        for i, metric in enumerate(config.get('metrics_config', {}).get('metrics', [])):
            progress.update_step(f"Calculating {metric}...", current_step + i + 1)
            await self._notify_progress_update(progress)
            
            # Check for pause/cancel
            await self._check_pause_cancel(progress.execution_id)
            
            # Simulate metric calculation
            await asyncio.sleep(0.1)
        
        # Step 5: Finalize
        progress.update_step("Finalizing results...", total_steps)
        await self._notify_progress_update(progress)
        
        # Simulate finalization
        await asyncio.sleep(0.2)
    
    async def _check_pause_cancel(self, execution_id: str):
        """Check if task should be paused or cancelled."""
        if execution_id in self.cancelled_tasks:
            raise asyncio.CancelledError("Task was cancelled")
        
        # Handle pause - wait until resumed or cancelled
        while execution_id in self.paused_tasks:
            if execution_id in self.cancelled_tasks:
                raise asyncio.CancelledError("Task was cancelled while paused")
            await asyncio.sleep(0.5)
    
    async def _get_configuration(self, config_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration from database."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
                if config:
                    return config.to_dict()
                return None
        except Exception as e:
            logger.error(f"Error getting configuration {config_id}: {e}")
            return None
    
    async def _create_evaluation_run(self, config: Dict[str, Any], task_data: Dict[str, Any]) -> str:
        """Create a new evaluation run."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                run = EvaluationRun(
                    name=f"UI Evaluation - {task_data['task_name']}",
                    dataset_name=config['dataset_config']['dataset_name'],
                    metrics_used=config['metrics_config']['metrics'],
                    metric_configs=config['metrics_config'],
                    status="running",
                    task_type=config['task_type'],
                    config=config,
                    created_by=task_data.get('created_by'),
                    project_id=task_data.get('project_id'),
                    started_at=datetime.now(timezone.utc)
                )
                
                db.add(run)
                db.commit()
                db.refresh(run)
                
                return str(run.id)
                
        except Exception as e:
            logger.error(f"Error creating evaluation run: {e}")
            raise LLMEvalError(f"Failed to create evaluation run: {str(e)}")
    
    async def _update_task_status(self, execution_id: str, status: str, error_message: Optional[str] = None):
        """Update task execution status in database."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
                if execution:
                    execution.status = status
                    if error_message:
                        execution.error_message = error_message
                    
                    # Update timestamps based on status
                    now = datetime.now(timezone.utc)
                    if status == TaskState.RUNNING:
                        execution.started_at = now
                    elif status == TaskState.PAUSED:
                        execution.paused_at = now
                    elif status in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED]:
                        execution.completed_at = now
                    
                    db.commit()
                    
        except Exception as e:
            logger.error(f"Error updating task status {execution_id}: {e}")
    
    async def _update_task_run_id(self, execution_id: str, run_id: str):
        """Update task execution with associated run ID."""
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as db:
                execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
                if execution:
                    execution.run_id = run_id
                    db.commit()
                    
        except Exception as e:
            logger.error(f"Error updating task run ID {execution_id}: {e}")
    
    async def _notify_task_update(self, execution_id: str, update_data: Dict[str, Any]):
        """Send task update via WebSocket."""
        if self.websocket_manager:
            try:
                await self.websocket_manager.broadcast_to_room(
                    f"task_{execution_id}",
                    {
                        "type": "task_update",
                        "execution_id": execution_id,
                        "data": update_data
                    }
                )
            except Exception as e:
                logger.error(f"Error broadcasting task update: {e}")
    
    async def _notify_progress_update(self, progress: ExecutionProgress):
        """Send progress update via WebSocket."""
        if self.websocket_manager:
            try:
                await self.websocket_manager.broadcast_to_room(
                    f"task_{progress.execution_id}",
                    {
                        "type": "progress_update",
                        "execution_id": progress.execution_id,
                        "data": {
                            "progress_percentage": progress.progress_percentage,
                            "current_step": progress.current_step,
                            "completed_steps": progress.completed_steps,
                            "total_steps": progress.total_steps,
                            "estimated_completion": progress.estimated_completion.isoformat() if progress.estimated_completion else None
                        }
                    }
                )
                
                # Also update database
                db_manager = get_database_manager()
                with db_manager.get_session() as db:
                    execution = db.query(TaskExecution).filter(TaskExecution.id == progress.execution_id).first()
                    if execution:
                        execution.progress_percentage = progress.progress_percentage
                        execution.current_step = progress.current_step
                        execution.completed_steps = progress.completed_steps
                        execution.total_steps = progress.total_steps
                        execution.estimated_completion = progress.estimated_completion
                        db.commit()
                        
            except Exception as e:
                logger.error(f"Error broadcasting progress update: {e}")


# Global task engine instance
_task_engine: Optional[TaskExecutionEngine] = None


def get_task_engine() -> TaskExecutionEngine:
    """Get the global task execution engine instance."""
    global _task_engine
    if _task_engine is None:
        # Import here to avoid circular imports
        from ..api.websocket_manager import get_websocket_manager
        websocket_manager = get_websocket_manager()
        _task_engine = TaskExecutionEngine(websocket_manager=websocket_manager)
    return _task_engine


async def start_task_engine():
    """Start the global task execution engine."""
    engine = get_task_engine()
    await engine.start()


async def stop_task_engine():
    """Stop the global task execution engine."""
    global _task_engine
    if _task_engine:
        await _task_engine.stop()
        _task_engine = None