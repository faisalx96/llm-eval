import { useState, useEffect, useRef, useCallback } from 'react';
import { apiClient } from '../lib/api';
import { WebSocketMessage } from '../types';

interface UseWebSocketOptions {
  runId?: string;
  autoConnect?: boolean;
  reconnectAttempts?: number;
  reconnectInterval?: number;
}

interface UseWebSocketReturn {
  socket: WebSocket | null;
  connectionState: 'connecting' | 'connected' | 'disconnected' | 'error';
  lastMessage: WebSocketMessage | null;
  error: string | null;
  connect: () => void;
  disconnect: () => void;
  sendMessage: (message: any) => void;
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    runId,
    autoConnect = true,
    reconnectAttempts = 3,
    reconnectInterval = 1000,
  } = options;

  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [connectionState, setConnectionState] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reconnectCount = useRef(0);
  const reconnectTimeout = useRef<NodeJS.Timeout | undefined>(undefined);

  const connect = useCallback(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      return;
    }

    setConnectionState('connecting');
    setError(null);

    try {
      const ws = apiClient.createWebSocketConnection(runId);

      ws.onopen = () => {
        setConnectionState('connected');
        setSocket(ws);
        reconnectCount.current = 0;
        console.log('WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          setLastMessage(message);
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', event.data);
        }
      };

      ws.onclose = (event) => {
        setSocket(null);
        setConnectionState('disconnected');
        
        // Attempt reconnection if not manually closed
        if (event.code !== 1000 && reconnectCount.current < reconnectAttempts) {
          reconnectCount.current++;
          console.log(`Attempting to reconnect (${reconnectCount.current}/${reconnectAttempts})...`);
          
          reconnectTimeout.current = setTimeout(() => {
            connect();
          }, reconnectInterval * reconnectCount.current);
        }
      };

      ws.onerror = (event) => {
        setConnectionState('error');
        setError('WebSocket connection error');
        console.error('WebSocket error:', event);
      };

    } catch (err) {
      setConnectionState('error');
      setError(err instanceof Error ? err.message : 'Failed to create WebSocket connection');
    }
  }, [runId, reconnectAttempts, reconnectInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current);
    }
    
    if (socket) {
      socket.close(1000, 'Manual disconnect');
      setSocket(null);
    }
    
    setConnectionState('disconnected');
    reconnectCount.current = reconnectAttempts; // Prevent reconnection
  }, [socket, reconnectAttempts]);

  const sendMessage = useCallback((message: any) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    } else {
      console.warn('Cannot send message: WebSocket not connected');
    }
  }, [socket]);

  // Auto-connect on mount if enabled
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      if (socket) {
        socket.close();
      }
    };
  }, [autoConnect, connect]);

  // Reconnect when runId changes
  useEffect(() => {
    if (socket && runId) {
      disconnect();
      setTimeout(() => connect(), 100);
    }
  }, [runId]);

  return {
    socket,
    connectionState,
    lastMessage,
    error,
    connect,
    disconnect,
    sendMessage,
  };
}