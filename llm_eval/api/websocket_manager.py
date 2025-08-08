"""WebSocket connection manager for real-time evaluation updates.

This module handles WebSocket connections for real-time progress updates
during evaluation runs, providing efficient broadcasting and connection management.
"""

import asyncio
import json
import logging
from typing import Dict, Set, List, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class ProgressUpdate(BaseModel):
    """Model for progress update messages."""
    run_id: str
    event_type: str  # "progress", "status", "result", "error", "completed"
    timestamp: datetime
    data: Dict[str, Any]
    
    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class ConnectionInfo(BaseModel):
    """Information about a WebSocket connection."""
    websocket: WebSocket
    run_ids: Set[str] = set()
    connected_at: datetime
    last_ping: Optional[datetime] = None
    
    class Config:
        arbitrary_types_allowed = True


class WebSocketManager:
    """
    Manages WebSocket connections for real-time evaluation updates.
    
    Handles multiple clients, run-specific subscriptions, and efficient
    broadcasting of progress updates during evaluation runs.
    """
    
    def __init__(self, max_connections: int = 1000, cleanup_interval: int = 300):
        # Active connections: connection_id -> ConnectionInfo
        self.connections: Dict[str, ConnectionInfo] = {}
        
        # Run subscriptions: run_id -> set of connection_ids
        self.run_subscriptions: Dict[str, Set[str]] = {}
        
        # General status subscriptions: connection_ids
        self.status_subscriptions: Set[str] = set()
        
        # Connection management settings
        self.max_connections = max_connections
        self.cleanup_interval = cleanup_interval
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        
        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # Connection health tracking
        self._connection_errors: Dict[str, int] = {}  # connection_id -> error_count
        self._max_errors_per_connection = 5
    
    def generate_connection_id(self) -> str:
        """Generate a unique connection ID."""
        return f"conn_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    async def connect(self, websocket: WebSocket) -> str:
        """
        Accept a new WebSocket connection with connection limits.
        
        Args:
            websocket: The WebSocket connection
            
        Returns:
            Connection ID for this connection
            
        Raises:
            RuntimeError: If connection limit exceeded
        """
        async with self._lock:
            # Check connection limit
            if len(self.connections) >= self.max_connections:
                await websocket.close(code=1000, reason="Connection limit exceeded")
                raise RuntimeError(f"Connection limit exceeded ({self.max_connections})")
        
        await websocket.accept()
        
        connection_id = self.generate_connection_id()
        
        async with self._lock:
            self.connections[connection_id] = ConnectionInfo(
                websocket=websocket,
                connected_at=datetime.now()
            )
            # Initialize error counter
            self._connection_errors[connection_id] = 0
        
        logger.info(f"WebSocket connection established: {connection_id} ({len(self.connections)}/{self.max_connections})")
        
        # Start cleanup task if not already running
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._background_cleanup())
        
        return connection_id
    
    async def disconnect(self, connection_id: str, force_close: bool = False):
        """
        Handle WebSocket disconnection with proper cleanup.
        
        Args:
            connection_id: The connection to disconnect
            force_close: Whether to force close the WebSocket
        """
        async with self._lock:
            if connection_id in self.connections:
                connection_info = self.connections[connection_id]
                
                # Close WebSocket if still open and force_close is True
                if force_close:
                    try:
                        await connection_info.websocket.close()
                    except Exception as e:
                        logger.debug(f"Error closing WebSocket {connection_id}: {e}")
                
                # Remove from run subscriptions
                for run_id in list(connection_info.run_ids):  # Copy to avoid modification during iteration
                    if run_id in self.run_subscriptions:
                        self.run_subscriptions[run_id].discard(connection_id)
                        if not self.run_subscriptions[run_id]:
                            del self.run_subscriptions[run_id]
                
                # Remove from status subscriptions
                self.status_subscriptions.discard(connection_id)
                
                # Clean up error tracking
                self._connection_errors.pop(connection_id, None)
                
                # Remove connection
                del self.connections[connection_id]
        
        logger.info(f"WebSocket connection closed: {connection_id} ({len(self.connections)} remaining)")
    
    async def subscribe_to_run(self, connection_id: str, run_id: str):
        """
        Subscribe a connection to updates for a specific run.
        
        Args:
            connection_id: The connection to subscribe
            run_id: The run ID to subscribe to
        """
        async with self._lock:
            if connection_id in self.connections:
                # Add to connection's run list
                self.connections[connection_id].run_ids.add(run_id)
                
                # Add to run subscriptions
                if run_id not in self.run_subscriptions:
                    self.run_subscriptions[run_id] = set()
                self.run_subscriptions[run_id].add(connection_id)
        
        logger.debug(f"Connection {connection_id} subscribed to run {run_id}")
    
    async def unsubscribe_from_run(self, connection_id: str, run_id: str):
        """
        Unsubscribe a connection from a specific run.
        
        Args:
            connection_id: The connection to unsubscribe
            run_id: The run ID to unsubscribe from
        """
        async with self._lock:
            if connection_id in self.connections:
                # Remove from connection's run list
                self.connections[connection_id].run_ids.discard(run_id)
                
                # Remove from run subscriptions
                if run_id in self.run_subscriptions:
                    self.run_subscriptions[run_id].discard(connection_id)
                    if not self.run_subscriptions[run_id]:
                        del self.run_subscriptions[run_id]
        
        logger.debug(f"Connection {connection_id} unsubscribed from run {run_id}")
    
    async def subscribe_to_status(self, connection_id: str):
        """
        Subscribe a connection to general status updates.
        
        Args:
            connection_id: The connection to subscribe
        """
        async with self._lock:
            self.status_subscriptions.add(connection_id)
        
        logger.debug(f"Connection {connection_id} subscribed to status updates")
    
    async def unsubscribe_from_status(self, connection_id: str):
        """
        Unsubscribe a connection from general status updates.
        
        Args:
            connection_id: The connection to unsubscribe
        """
        async with self._lock:
            self.status_subscriptions.discard(connection_id)
        
        logger.debug(f"Connection {connection_id} unsubscribed from status updates")
    
    async def send_personal_message(self, connection_id: str, message: Dict[str, Any]) -> bool:
        """
        Send a message to a specific connection with error tracking.
        
        Args:
            connection_id: Target connection
            message: Message to send
            
        Returns:
            True if message sent successfully, False otherwise
        """
        if connection_id not in self.connections:
            return False
            
        websocket = self.connections[connection_id].websocket
        
        try:
            await websocket.send_text(json.dumps(message))
            # Reset error count on successful send
            async with self._lock:
                self._connection_errors[connection_id] = 0
            return True
            
        except Exception as e:
            logger.warning(f"Failed to send message to {connection_id}: {e}")
            
            # Increment error count
            async with self._lock:
                if connection_id in self._connection_errors:
                    self._connection_errors[connection_id] += 1
                    
                    # If too many errors, disconnect
                    if self._connection_errors[connection_id] >= self._max_errors_per_connection:
                        logger.error(f"Too many errors for connection {connection_id}, disconnecting")
                        await self.disconnect(connection_id, force_close=True)
                        return False
            
            return False
    
    async def broadcast_to_run(self, run_id: str, update: ProgressUpdate):
        """
        Broadcast a progress update to all connections subscribed to a run.
        
        Args:
            run_id: The run ID
            update: Progress update to broadcast
        """
        if run_id not in self.run_subscriptions:
            return
        
        message = update.dict()
        connection_ids = list(self.run_subscriptions[run_id])
        
        # Send to all subscribed connections
        for connection_id in connection_ids:
            await self.send_personal_message(connection_id, message)
    
    async def broadcast_status_update(self, update: Dict[str, Any]):
        """
        Broadcast a general status update to all status subscribers.
        
        Args:
            update: Status update to broadcast
        """
        connection_ids = list(self.status_subscriptions)
        
        # Send to all status subscribers
        for connection_id in connection_ids:
            await self.send_personal_message(connection_id, update)
    
    async def broadcast_to_all(self, message: Dict[str, Any]):
        """
        Broadcast a message to all connected clients.
        
        Args:
            message: Message to broadcast
        """
        connection_ids = list(self.connections.keys())
        
        # Send to all connections
        for connection_id in connection_ids:
            await self.send_personal_message(connection_id, message)
    
    async def get_connection_count(self) -> int:
        """Get the number of active connections."""
        async with self._lock:
            return len(self.connections)
    
    async def get_run_subscriber_count(self, run_id: str) -> int:
        """Get the number of connections subscribed to a specific run."""
        async with self._lock:
            return len(self.run_subscriptions.get(run_id, set()))
    
    async def cleanup_stale_connections(self):
        """Remove connections that might be stale with improved health checks."""
        current_time = datetime.now()
        stale_connections = []
        
        async with self._lock:
            for connection_id, info in self.connections.items():
                should_remove = False
                
                # Check silence duration
                if info.last_ping:
                    silence_duration = (current_time - info.last_ping).total_seconds()
                    if silence_duration > 300:  # 5 minutes of silence
                        should_remove = True
                        logger.debug(f"Connection {connection_id} silent for {silence_duration}s")
                
                # Check connection age without activity
                connection_age = (current_time - info.connected_at).total_seconds()
                if not info.last_ping and connection_age > 600:  # 10 minutes without any ping
                    should_remove = True
                    logger.debug(f"Connection {connection_id} aged {connection_age}s without activity")
                
                # Check error count
                error_count = self._connection_errors.get(connection_id, 0)
                if error_count >= self._max_errors_per_connection:
                    should_remove = True
                    logger.debug(f"Connection {connection_id} has {error_count} errors")
                
                if should_remove:
                    stale_connections.append(connection_id)
        
        # Remove stale connections
        for connection_id in stale_connections:
            logger.info(f"Removing stale connection: {connection_id}")
            await self.disconnect(connection_id, force_close=True)
        
        if stale_connections:
            logger.info(f"Cleaned up {len(stale_connections)} stale connections")
    
    async def _background_cleanup(self):
        """Background task for periodic connection cleanup."""
        logger.info("Starting background cleanup task")
        
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), 
                    timeout=self.cleanup_interval
                )
                # If we get here, shutdown was requested
                break
            except asyncio.TimeoutError:
                # Timeout is expected, time to run cleanup
                pass
            
            try:
                await self.cleanup_stale_connections()
            except Exception as e:
                logger.error(f"Error during background cleanup: {e}")
        
        logger.info("Background cleanup task stopped")
    
    async def shutdown(self):
        """Shutdown the WebSocket manager and clean up resources."""
        logger.info("Shutting down WebSocket manager")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Wait for cleanup task to finish
        if self._cleanup_task and not self._cleanup_task.done():
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Background cleanup task did not shutdown gracefully")
                self._cleanup_task.cancel()
        
        # Disconnect all connections
        connection_ids = list(self.connections.keys())
        for connection_id in connection_ids:
            await self.disconnect(connection_id, force_close=True)
        
        logger.info("WebSocket manager shutdown complete")
    
    async def ping_connection(self, connection_id: str) -> bool:
        """
        Ping a specific connection to check if it's alive.
        
        Args:
            connection_id: Connection to ping
            
        Returns:
            True if ping successful, False otherwise
        """
        if connection_id not in self.connections:
            return False
        
        ping_message = {
            "event_type": "ping",
            "timestamp": datetime.now().isoformat(),
            "connection_id": connection_id
        }
        
        success = await self.send_personal_message(connection_id, ping_message)
        
        if success:
            async with self._lock:
                if connection_id in self.connections:
                    self.connections[connection_id].last_ping = datetime.now()
        
        return success
    
    async def ping_all_connections(self) -> int:
        """
        Ping all connections to check health.
        
        Returns:
            Number of successful pings
        """
        connection_ids = list(self.connections.keys())
        successful_pings = 0
        
        for connection_id in connection_ids:
            if await self.ping_connection(connection_id):
                successful_pings += 1
        
        logger.debug(f"Pinged {successful_pings}/{len(connection_ids)} connections successfully")
        return successful_pings
    
    async def health_check(self) -> Dict[str, Any]:
        """Get comprehensive manager health information."""
        current_time = datetime.now()
        
        async with self._lock:
            # Connection statistics
            total_connections = len(self.connections)
            error_counts = sum(self._connection_errors.values())
            avg_connection_age = 0
            
            if self.connections:
                total_age = sum(
                    (current_time - info.connected_at).total_seconds() 
                    for info in self.connections.values()
                )
                avg_connection_age = total_age / len(self.connections)
            
            # Health status determination
            health_status = "healthy"
            if total_connections >= self.max_connections * 0.9:
                health_status = "warning"  # Near capacity
            elif error_counts > total_connections * 2:  # More than 2 errors per connection on average
                health_status = "warning"
            
            return {
                "status": health_status,
                "connections": {
                    "total": total_connections,
                    "limit": self.max_connections,
                    "utilization": round(total_connections / self.max_connections * 100, 1) if self.max_connections > 0 else 0,
                    "avg_age_seconds": round(avg_connection_age, 1)
                },
                "subscriptions": {
                    "run_subscriptions": len(self.run_subscriptions),
                    "status_subscriptions": len(self.status_subscriptions),
                    "total_run_subscribers": sum(len(subs) for subs in self.run_subscriptions.values())
                },
                "errors": {
                    "total_error_count": error_counts,
                    "connections_with_errors": len([c for c in self._connection_errors.values() if c > 0])
                },
                "cleanup": {
                    "task_running": self._cleanup_task is not None and not self._cleanup_task.done(),
                    "cleanup_interval": self.cleanup_interval
                },
                "timestamp": current_time.isoformat()
            }


# Global WebSocket manager instance with production settings
websocket_manager = WebSocketManager(max_connections=1000, cleanup_interval=300)


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance."""
    return websocket_manager


@asynccontextmanager
async def managed_websocket_connection(websocket: WebSocket):
    """
    Context manager for handling WebSocket connections with automatic cleanup.
    
    Args:
        websocket: The WebSocket connection
        
    Yields:
        Tuple of (connection_id, manager)
        
    Raises:
        RuntimeError: If connection limit exceeded
    """
    manager = get_websocket_manager()
    connection_id = None
    
    try:
        connection_id = await manager.connect(websocket)
        yield connection_id, manager
        
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
        raise  # Re-raise to let the caller handle
        
    except RuntimeError as e:
        # Connection limit exceeded or other connection errors
        logger.warning(f"WebSocket connection failed: {e}")
        raise
        
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
        raise
        
    finally:
        # Always ensure cleanup happens
        if connection_id:
            try:
                await manager.disconnect(connection_id, force_close=True)
            except Exception as cleanup_error:
                logger.error(f"Error during connection cleanup {connection_id}: {cleanup_error}")
                # Don't re-raise cleanup errors to avoid masking original exceptions