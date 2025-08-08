"""Health check endpoints for API monitoring."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..models import HealthCheckResponse, DatabaseHealth
from ...storage.database import get_database_manager


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=HealthCheckResponse)
async def health_check():
    """
    Comprehensive health check for the API and database.
    
    Returns:
        Health status including database connectivity and basic statistics
    """
    try:
        # Check database health
        db_manager = get_database_manager()
        db_health = db_manager.health_check()
        
        # Determine overall status
        overall_status = "healthy" if db_health["status"] == "healthy" else "unhealthy"
        
        return HealthCheckResponse(
            status=overall_status,
            timestamp=datetime.utcnow(),
            database=DatabaseHealth(**db_health),
            version="0.3.0"
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Service Unavailable",
                "message": "Health check failed",
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/database")
async def database_health():
    """
    Database-specific health check.
    
    Returns:
        Database connectivity status and statistics
    """
    try:
        db_manager = get_database_manager()
        health_status = db_manager.health_check()
        
        if health_status["status"] == "healthy":
            return JSONResponse(
                status_code=200,
                content=health_status
            )
        else:
            return JSONResponse(
                status_code=503,
                content=health_status
            )
            
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/ready")
async def readiness_check():
    """
    Readiness check for Kubernetes/container orchestration.
    
    Returns:
        Simple ready/not ready status
    """
    try:
        db_manager = get_database_manager()
        db_health = db_manager.health_check()
        
        if db_health["status"] == "healthy":
            return {"status": "ready"}
        else:
            raise HTTPException(
                status_code=503,
                detail={"status": "not ready", "reason": "database unhealthy"}
            )
            
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "reason": str(e)}
        )