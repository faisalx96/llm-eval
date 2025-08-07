"""WebSocket endpoints for real-time evaluation updates.

This module provides WebSocket endpoints that enable real-time communication
between the evaluation backend and frontend, supporting live progress tracking
and status updates during evaluation runs.
"""

import asyncio
import json
import logging
from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Path, HTTPException
from pydantic import ValidationError

from .websocket_manager import (
    managed_websocket_connection, 
    get_websocket_manager,
    ProgressUpdate
)
from ..storage.run_repository import RunRepository
from ..storage.database import get_database_manager


logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_general(websocket: WebSocket):
    """
    General WebSocket endpoint for dashboard connections.
    
    This endpoint provides general run status updates and system information
    for the main dashboard view.
    """
    async with managed_websocket_connection(websocket) as (connection_id, manager):
        logger.info(f"Client connected to general WebSocket: {connection_id}")
        
        # Subscribe to general status updates
        await manager.subscribe_to_status(connection_id)
        
        # Send initial connection confirmation
        await websocket.send_text(json.dumps({
            "event_type": "connected",
            "connection_id": connection_id,
            "timestamp": datetime.now().isoformat()
        }))
        
        try:
            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages from client with timeout
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    # Parse client message
                    try:
                        message = json.loads(data)
                        await handle_status_client_message(connection_id, message, manager)
                    except json.JSONDecodeError:
                        await websocket.send_text(json.dumps({
                            "error": "Invalid JSON format",
                            "timestamp": datetime.now().isoformat()
                        }))
                    
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_text(json.dumps({
                        "event_type": "ping",
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                except WebSocketDisconnect:
                    logger.info(f"Client disconnected from general WebSocket: {connection_id}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in general WebSocket {connection_id}: {e}")
        finally:
            await manager.unsubscribe_from_status(connection_id)


@router.websocket("/ws/{run_id}")
async def websocket_run_specific(websocket: WebSocket, run_id: str = Path(...)):
    """
    WebSocket endpoint for specific run monitoring.
    
    This endpoint provides real-time updates for a specific evaluation run.
    """
    async with managed_websocket_connection(websocket) as (connection_id, manager):
        logger.info(f"Client connected to run-specific WebSocket: {connection_id} -> {run_id}")
        
        # Verify run exists
        db_manager = get_database_manager()
        
        with db_manager.get_session() as session:
            run_repo = RunRepository(session)
            try:
                run = run_repo.get_run(run_id)
                if not run:
                    await websocket.send_text(json.dumps({
                        "error": "Run not found",
                        "run_id": run_id,
                        "timestamp": datetime.now().isoformat()
                    }))
                    return
            except Exception as e:
                logger.error(f"Error checking run {run_id}: {e}")
                await websocket.send_text(json.dumps({
                    "error": "Failed to verify run",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }))
                return
        
        # Subscribe to run updates
        await manager.subscribe_to_run(connection_id, run_id)
        
        # Send initial run status
        await websocket.send_text(json.dumps({
            "event_type": "connected",
            "run_id": run_id,
            "run_status": run.get('status', 'unknown') if isinstance(run, dict) else getattr(run, 'status', 'unknown'),
            "connection_id": connection_id,
            "timestamp": datetime.now().isoformat()
        }))
        
        try:
            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages from client with timeout
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    # Parse client message
                    try:
                        message = json.loads(data)
                        await handle_client_message(connection_id, run_id, message, manager)
                    except json.JSONDecodeError:
                        await websocket.send_text(json.dumps({
                            "error": "Invalid JSON format",
                            "timestamp": datetime.now().isoformat()
                        }))
                    
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_text(json.dumps({
                        "event_type": "ping",
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                except WebSocketDisconnect:
                    logger.info(f"Client disconnected from run-specific WebSocket: {connection_id}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in run-specific WebSocket {connection_id}: {e}")
        finally:
            await manager.unsubscribe_from_run(connection_id, run_id)


@router.websocket("/ws/runs/{run_id}/progress")
async def websocket_run_progress(websocket: WebSocket, run_id: str = Path(...)):
    """
    WebSocket endpoint for real-time progress updates for a specific evaluation run.
    
    Clients can connect to this endpoint to receive live updates about:
    - Evaluation progress (items completed, success rate)
    - Individual item results as they complete
    - Error notifications
    - Completion status
    
    Args:
        websocket: WebSocket connection
        run_id: The evaluation run ID to monitor
    """
    async with managed_websocket_connection(websocket) as (connection_id, manager):
        logger.info(f"Client connected to run progress: {connection_id} -> {run_id}")
        
        # Verify run exists
        db_manager = get_database_manager()
        run_repo = RunRepository(db_manager)
        
        try:
            run = await run_repo.get_run(run_id)
            if not run:
                await websocket.send_text(json.dumps({
                    "error": "Run not found",
                    "run_id": run_id,
                    "timestamp": datetime.now().isoformat()
                }))
                return
        except Exception as e:
            logger.error(f"Error checking run {run_id}: {e}")
            await websocket.send_text(json.dumps({
                "error": "Failed to verify run",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }))
            return
        
        # Subscribe to run updates
        await manager.subscribe_to_run(connection_id, run_id)
        
        # Send initial run status
        await websocket.send_text(json.dumps({
            "event_type": "connected",
            "run_id": run_id,
            "run_status": run.status,
            "connection_id": connection_id,
            "timestamp": datetime.now().isoformat()
        }))
        
        try:
            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages from client with timeout
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    # Parse client message
                    try:
                        message = json.loads(data)
                        await handle_client_message(connection_id, run_id, message, manager)
                    except json.JSONDecodeError:
                        await websocket.send_text(json.dumps({
                            "error": "Invalid JSON format",
                            "timestamp": datetime.now().isoformat()
                        }))
                    
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_text(json.dumps({
                        "event_type": "ping",
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                except WebSocketDisconnect:
                    logger.info(f"Client disconnected from run progress: {connection_id}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in run progress WebSocket {connection_id}: {e}")
        finally:
            await manager.unsubscribe_from_run(connection_id, run_id)


@router.websocket("/ws/runs/status")
async def websocket_runs_status(websocket: WebSocket):
    """
    WebSocket endpoint for general run status updates across all evaluation runs.
    
    Clients can connect to this endpoint to receive notifications about:
    - New runs starting
    - Run status changes (running -> completed, failed)
    - System status updates
    - Run statistics summaries
    
    Args:
        websocket: WebSocket connection
    """
    async with managed_websocket_connection(websocket) as (connection_id, manager):
        logger.info(f"Client connected to runs status: {connection_id}")
        
        # Subscribe to status updates
        await manager.subscribe_to_status(connection_id)
        
        # Send initial connection confirmation
        await websocket.send_text(json.dumps({
            "event_type": "connected",
            "connection_id": connection_id,
            "timestamp": datetime.now().isoformat()
        }))
        
        # Send basic connection stats
        try:
            manager_stats = await manager.health_check()
            await websocket.send_text(json.dumps({
                "event_type": "initial_stats",
                "data": {
                    "websocket_connections": manager_stats["connections"],
                    "active_subscriptions": manager_stats["run_subscriptions"],
                    "status": "connected"
                },
                "timestamp": datetime.now().isoformat()
            }))
            
        except Exception as e:
            logger.error(f"Error sending initial stats: {e}")
        
        try:
            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages from client with timeout
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    # Parse client message
                    try:
                        message = json.loads(data)
                        await handle_status_client_message(connection_id, message, manager)
                    except json.JSONDecodeError:
                        await websocket.send_text(json.dumps({
                            "error": "Invalid JSON format",
                            "timestamp": datetime.now().isoformat()
                        }))
                    
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_text(json.dumps({
                        "event_type": "ping",
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                except WebSocketDisconnect:
                    logger.info(f"Client disconnected from runs status: {connection_id}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in runs status WebSocket {connection_id}: {e}")
        finally:
            await manager.unsubscribe_from_status(connection_id)


async def handle_client_message(
    connection_id: str, 
    run_id: str, 
    message: Dict[str, Any], 
    manager
):
    """
    Handle incoming messages from clients on run progress WebSocket.
    
    Args:
        connection_id: The client connection ID
        run_id: The run ID being monitored
        message: The message from the client
        manager: WebSocket manager instance
    """
    message_type = message.get("type")
    
    if message_type == "pong":
        # Client responding to ping
        logger.debug(f"Received pong from {connection_id}")
        
    elif message_type == "get_current_status":
        # Client requesting current run status
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as session:
                run_repo = RunRepository(session)
                run = run_repo.get_run(run_id)
            
            if run:
                await manager.send_personal_message(connection_id, {
                    "event_type": "current_status",
                    "run_id": run_id,
                    "data": {
                        "status": run.get('status', 'unknown') if isinstance(run, dict) else getattr(run, 'status', 'unknown'),
                        "progress": run.get('progress', {}) if isinstance(run, dict) else getattr(run, 'progress', {}),
                        "updated_at": datetime.now().isoformat()
                    },
                    "timestamp": datetime.now().isoformat()
                })
            else:
                await manager.send_personal_message(connection_id, {
                    "error": "Run not found",
                    "run_id": run_id,
                    "timestamp": datetime.now().isoformat()
                })
                
        except Exception as e:
            logger.error(f"Error getting current status for {run_id}: {e}")
            await manager.send_personal_message(connection_id, {
                "error": "Failed to get current status",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    else:
        logger.warning(f"Unknown message type from {connection_id}: {message_type}")


async def handle_status_client_message(
    connection_id: str, 
    message: Dict[str, Any], 
    manager
):
    """
    Handle incoming messages from clients on runs status WebSocket.
    
    Args:
        connection_id: The client connection ID
        message: The message from the client
        manager: WebSocket manager instance
    """
    message_type = message.get("type")
    
    if message_type == "pong":
        # Client responding to ping
        logger.debug(f"Received pong from {connection_id}")
        
    elif message_type == "get_run_statistics":
        # Client requesting current run statistics
        try:
            db_manager = get_database_manager()
            with db_manager.get_session() as session:
                run_repo = RunRepository(session)
                # Get basic stats
                total_runs = run_repo.count_runs()
            
            stats = {
                "total_runs": total_runs,
                "timestamp": datetime.now().isoformat()
            }
            
            await manager.send_personal_message(connection_id, {
                "event_type": "run_statistics",
                "data": stats,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error getting run statistics: {e}")
            await manager.send_personal_message(connection_id, {
                "error": "Failed to get run statistics",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    else:
        logger.warning(f"Unknown message type from {connection_id}: {message_type}")


# Utility functions for emitting progress updates

async def emit_progress_update(
    run_id: str,
    event_type: str,
    data: Dict[str, Any]
):
    """
    Emit a progress update for a specific run.
    
    Args:
        run_id: The run ID
        event_type: Type of update (progress, result, error, completed)
        data: Update data
    """
    manager = get_websocket_manager()
    
    update = ProgressUpdate(
        run_id=run_id,
        event_type=event_type,
        timestamp=datetime.now(),
        data=data
    )
    
    await manager.broadcast_to_run(run_id, update)


async def emit_status_update(update_data: Dict[str, Any]):
    """
    Emit a general status update to all status subscribers.
    
    Args:
        update_data: Status update data
    """
    manager = get_websocket_manager()
    
    update = {
        "event_type": "status_update",
        "data": update_data,
        "timestamp": datetime.now().isoformat()
    }
    
    await manager.broadcast_status_update(update)


async def emit_run_started(run_id: str, run_data: Dict[str, Any]):
    """
    Emit notification that a new run has started.
    
    Args:
        run_id: The run ID
        run_data: Run information
    """
    await emit_status_update({
        "type": "run_started",
        "run_id": run_id,
        "run_data": run_data
    })


async def emit_run_completed(run_id: str, run_data: Dict[str, Any]):
    """
    Emit notification that a run has completed.
    
    Args:
        run_id: The run ID
        run_data: Run results and information
    """
    # Notify run subscribers
    await emit_progress_update(run_id, "completed", run_data)
    
    # Notify status subscribers
    await emit_status_update({
        "type": "run_completed",
        "run_id": run_id,
        "run_data": run_data
    })


async def emit_run_failed(run_id: str, error_data: Dict[str, Any]):
    """
    Emit notification that a run has failed.
    
    Args:
        run_id: The run ID
        error_data: Error information
    """
    # Notify run subscribers
    await emit_progress_update(run_id, "error", error_data)
    
    # Notify status subscribers
    await emit_status_update({
        "type": "run_failed",
        "run_id": run_id,
        "error_data": error_data
    })