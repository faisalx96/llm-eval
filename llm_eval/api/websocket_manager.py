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
    
    def __init__(self):
        # Active connections: connection_id -> ConnectionInfo
        self.connections: Dict[str, ConnectionInfo] = {}
        
        # Run subscriptions: run_id -> set of connection_ids
        self.run_subscriptions: Dict[str, Set[str]] = {}
        
        # General status subscriptions: connection_ids
        self.status_subscriptions: Set[str] = set()
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
    def generate_connection_id(self) -> str:
        """Generate a unique connection ID."""
        return f"conn_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    async def connect(self, websocket: WebSocket) -> str:
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection
            
        Returns:
            Connection ID for this connection
        """
        await websocket.accept()
        
        connection_id = self.generate_connection_id()
        
        async with self._lock:
            self.connections[connection_id] = ConnectionInfo(
                websocket=websocket,
                connected_at=datetime.now()
            )
        
        logger.info(f"WebSocket connection established: {connection_id}")
        return connection_id
    
    async def disconnect(self, connection_id: str):
        """
        Handle WebSocket disconnection.
        
        Args:
            connection_id: The connection to disconnect
        """
        async with self._lock:
            if connection_id in self.connections:
                connection_info = self.connections[connection_id]
                
                # Remove from run subscriptions
                for run_id in connection_info.run_ids:
                    if run_id in self.run_subscriptions:
                        self.run_subscriptions[run_id].discard(connection_id)
                        if not self.run_subscriptions[run_id]:
                            del self.run_subscriptions[run_id]
                
                # Remove from status subscriptions
                self.status_subscriptions.discard(connection_id)
                
                # Remove connection
                del self.connections[connection_id]
        
        logger.info(f"WebSocket connection closed: {connection_id}")
    
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
    
    async def send_personal_message(self, connection_id: str, message: Dict[str, Any]):
        """
        Send a message to a specific connection.
        
        Args:
            connection_id: Target connection
            message: Message to send
        """
        async with self._lock:
            if connection_id in self.connections:
                websocket = self.connections[connection_id].websocket
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.warning(f"Failed to send message to {connection_id}: {e}")
                    # Connection might be broken, remove it
                    await self.disconnect(connection_id)
    
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
        """Remove connections that might be stale."""
        current_time = datetime.now()
        stale_connections = []
        
        async with self._lock:
            for connection_id, info in self.connections.items():
                # Check if connection has been silent for too long
                if info.last_ping:
                    silence_duration = (current_time - info.last_ping).total_seconds()
                    if silence_duration > 300:  # 5 minutes
                        stale_connections.append(connection_id)
        
        # Remove stale connections
        for connection_id in stale_connections:
            await self.disconnect(connection_id)
    
    async def health_check(self) -> Dict[str, Any]:
        """Get manager health information."""
        async with self._lock:
            return {
                "status": "healthy",
                "connections": len(self.connections),
                "run_subscriptions": len(self.run_subscriptions),
                "status_subscriptions": len(self.status_subscriptions),
                "timestamp": datetime.now().isoformat()
            }


# Global WebSocket manager instance
websocket_manager = WebSocketManager()


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
    """
    manager = get_websocket_manager()
    connection_id = await manager.connect(websocket)
    
    try:
        yield connection_id, manager
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
    finally:
        await manager.disconnect(connection_id)