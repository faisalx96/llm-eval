"""FastAPI dependencies for the LLM-Eval API.

This module provides reusable dependency functions for authentication,
validation, and common API operations.
"""

import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Request

from ..storage.run_repository import RunRepository
from ..storage.database import get_database_manager


logger = logging.getLogger(__name__)


def get_run_repository() -> RunRepository:
    """
    Dependency to get a run repository instance.
    
    Returns:
        RunRepository instance for database operations
    """
    return RunRepository()


def get_database_manager():
    """
    Dependency to get the database manager.
    
    Returns:
        DatabaseManager instance
        
    Raises:
        HTTPException: If database is not available
    """
    try:
        return get_database_manager()
    except Exception as e:
        logger.error(f"Database unavailable: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )


async def validate_api_key(request: Request) -> Optional[str]:
    """
    Validate API key from request headers (optional authentication).
    
    Args:
        request: FastAPI request object
        
    Returns:
        API key if provided and valid, None if no auth required
        
    Raises:
        HTTPException: If API key is invalid
    """
    # This is a placeholder for future API key authentication
    # For now, we'll allow all requests without authentication
    api_key = request.headers.get("X-API-Key")
    
    if api_key:
        # TODO: Implement actual API key validation
        # For now, just log that a key was provided
        logger.info("API key provided in request")
    
    return api_key


def validate_pagination_params(page: int = 1, per_page: int = 20) -> Dict[str, int]:
    """
    Validate and normalize pagination parameters.
    
    Args:
        page: Page number (1-based)
        per_page: Items per page
        
    Returns:
        Dictionary with validated pagination params
        
    Raises:
        HTTPException: If parameters are invalid
    """
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page number must be >= 1"
        )
    
    if per_page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Items per page must be >= 1"
        )
    
    if per_page > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Items per page cannot exceed 100"
        )
    
    return {
        'page': page,
        'per_page': per_page,
        'offset': (page - 1) * per_page
    }


def validate_sort_params(order_by: str, descending: bool = True) -> Dict[str, Any]:
    """
    Validate sorting parameters.
    
    Args:
        order_by: Field to sort by
        descending: Sort direction
        
    Returns:
        Dictionary with validated sort params
        
    Raises:
        HTTPException: If sort field is invalid
    """
    valid_sort_fields = {
        'created_at', 'name', 'status', 'success_rate', 
        'duration_seconds', 'total_items', 'model_name'
    }
    
    if order_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort field. Valid fields: {', '.join(valid_sort_fields)}"
        )
    
    return {
        'order_by': order_by,
        'descending': descending
    }


async def check_run_exists(run_id: str, repo: RunRepository) -> None:
    """
    Check if a run exists and raise 404 if not.
    
    Args:
        run_id: Run UUID to check
        repo: Repository instance
        
    Raises:
        HTTPException: If run doesn't exist
    """
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with ID {run_id} not found"
        )


def format_api_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """
    Format an exception into a standardized API error response.
    
    Args:
        error: Exception to format
        context: Additional context about where the error occurred
        
    Returns:
        Standardized error dictionary
    """
    error_type = error.__class__.__name__
    error_message = str(error)
    
    if context:
        error_message = f"{context}: {error_message}"
    
    return {
        "error": error_type,
        "message": error_message,
        "type": "API_ERROR"
    }