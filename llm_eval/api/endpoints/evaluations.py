"""Evaluation Configuration API endpoints.

This module provides REST API endpoints for managing evaluation configurations
in the UI-driven evaluation platform. Supports versioning, validation, and
draft/published states for reusable evaluation configurations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session

from ...models.run_models import EvaluationConfig, TaskExecution
from ...storage.database import get_database_manager
from ...templates.registry import TEMPLATE_REGISTRY, recommend_template
from ...core.task_engine import get_task_engine
from ...metrics.configuration import (
    get_metric_registry, 
    get_metric_validator,
    MetricConfigurationRequest,
    MetricConfigurationResponse,
    MetricPreviewRequest,
    MetricPreviewResponse
)
from ...utils.errors import LLMEvalError

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request/response validation
class ConfigurationRequest(BaseModel):
    """Request model for creating/updating evaluation configurations."""
    
    name: str = Field(..., description="User-friendly configuration name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Optional configuration description", max_length=1000)
    config_key: Optional[str] = Field(None, description="Unique configuration identifier (auto-generated if not provided)", max_length=255)
    
    task_type: str = Field(..., description="Type of evaluation task", max_length=50)
    template_name: Optional[str] = Field(None, description="Base template used", max_length=100)
    
    task_config: Dict[str, Any] = Field(..., description="Complete task configuration")
    dataset_config: Dict[str, Any] = Field(..., description="Dataset configuration and filters")
    metrics_config: Dict[str, Any] = Field(..., description="Metrics configuration with parameters")
    
    execution_config: Optional[Dict[str, Any]] = Field(None, description="Execution parameters (batch size, parallel, etc.)")
    langfuse_config: Optional[Dict[str, Any]] = Field(None, description="Langfuse connection and project settings")
    
    tags: Optional[List[str]] = Field(None, description="User-defined tags for organization")
    project_id: Optional[str] = Field(None, description="Project/workspace identifier", max_length=255)

    @validator('template_name')
    def validate_template_name(cls, v):
        if v and v not in TEMPLATE_REGISTRY:
            available = list(TEMPLATE_REGISTRY.keys())
            raise ValueError(f"Template '{v}' not found. Available: {', '.join(available)}")
        return v

    @validator('task_config')
    def validate_task_config(cls, v):
        if not v:
            raise ValueError("task_config cannot be empty")
        return v

    @validator('dataset_config')
    def validate_dataset_config(cls, v):
        if not v:
            raise ValueError("dataset_config cannot be empty")
        # Check for required dataset fields
        if 'dataset_name' not in v:
            raise ValueError("dataset_config must include 'dataset_name'")
        return v

    @validator('metrics_config')
    def validate_metrics_config(cls, v):
        if not v:
            raise ValueError("metrics_config cannot be empty")
        # Check for required metrics fields
        if 'metrics' not in v or not v['metrics']:
            raise ValueError("metrics_config must include at least one metric")
        return v


class ConfigurationResponse(BaseModel):
    """Response model for evaluation configurations."""
    
    id: str
    name: str
    description: Optional[str]
    config_key: str
    version: int
    is_current_version: bool
    parent_config_id: Optional[str]
    status: str
    task_type: str
    template_name: Optional[str]
    task_config: Dict[str, Any]
    dataset_config: Dict[str, Any]
    metrics_config: Dict[str, Any]
    execution_config: Optional[Dict[str, Any]]
    langfuse_config: Optional[Dict[str, Any]]
    tags: Optional[List[str]]
    created_at: str
    updated_at: str
    created_by: Optional[str]
    project_id: Optional[str]
    usage_count: int
    last_used_at: Optional[str]

    class Config:
        from_attributes = True


class ConfigurationListResponse(BaseModel):
    """Response model for configuration lists."""
    
    configurations: List[ConfigurationResponse]
    total_count: int
    filtered_count: int
    page: int
    page_size: int
    has_more: bool


class ConfigurationUpdateRequest(BaseModel):
    """Request model for updating evaluation configurations."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[str] = Field(None, pattern="^(draft|published|archived)$")
    task_config: Optional[Dict[str, Any]] = None
    dataset_config: Optional[Dict[str, Any]] = None
    metrics_config: Optional[Dict[str, Any]] = None
    execution_config: Optional[Dict[str, Any]] = None
    langfuse_config: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class TemplateRecommendationRequest(BaseModel):
    """Request model for template recommendations."""
    
    description: str = Field(..., description="Description of the evaluation task", min_length=10)
    sample_data: Optional[Dict[str, Any]] = Field(None, description="Sample input/output data")
    use_case: Optional[str] = Field(None, description="Specific use case or domain")


class TemplateRecommendationResponse(BaseModel):
    """Response model for template recommendations."""
    
    template_name: str
    confidence: float
    name: str
    description: str
    metrics: List[str]
    reason: str


class TaskExecutionRequest(BaseModel):
    """Request model for task execution."""
    
    config_id: str = Field(..., description="Configuration ID to execute")
    task_name: str = Field(..., description="Human-readable task name", min_length=1, max_length=255)
    priority: int = Field(0, description="Execution priority (higher = more urgent)", ge=0)
    project_id: Optional[str] = Field(None, description="Project/workspace identifier")


class TaskExecutionResponse(BaseModel):
    """Response model for task execution."""
    
    id: str
    execution_key: str
    task_name: str
    config_id: Optional[str]
    run_id: Optional[str]
    status: str
    queue_position: Optional[int]
    priority: int
    progress_percentage: float
    current_step: Optional[str]
    total_steps: Optional[int]
    completed_steps: int
    queued_at: str
    started_at: Optional[str]
    paused_at: Optional[str]
    completed_at: Optional[str]
    estimated_completion: Optional[str]
    error_message: Optional[str]
    error_type: Optional[str]
    retry_count: int
    max_retries: int
    resource_usage: Optional[Dict[str, Any]]
    performance_metrics: Optional[Dict[str, Any]]
    created_by: Optional[str]
    project_id: Optional[str]

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """Response model for task execution lists."""
    
    executions: List[TaskExecutionResponse]
    total_count: int
    active_count: int


# Database dependency
def get_db() -> Session:
    """Get database session."""
    db_manager = get_database_manager()
    with db_manager.get_session() as session:
        yield session


# API Endpoints

@router.post("/configs", response_model=ConfigurationResponse, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    config_data: ConfigurationRequest,
    db: Session = Depends(get_db),
    created_by: Optional[str] = Query(None, description="User who created the configuration")
):
    """Create a new evaluation configuration."""
    try:
        logger.info(f"Creating new evaluation configuration: {config_data.name}")
        
        # Generate config_key if not provided
        if not config_data.config_key:
            config_data.config_key = f"{config_data.name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        
        # Check if config_key already exists
        existing = db.query(EvaluationConfig).filter_by(config_key=config_data.config_key).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Configuration with key '{config_data.config_key}' already exists"
            )
        
        # Create new configuration
        config = EvaluationConfig(
            name=config_data.name,
            description=config_data.description,
            config_key=config_data.config_key,
            task_type=config_data.task_type,
            template_name=config_data.template_name,
            task_config=config_data.task_config,
            dataset_config=config_data.dataset_config,
            metrics_config=config_data.metrics_config,
            execution_config=config_data.execution_config,
            langfuse_config=config_data.langfuse_config,
            tags=config_data.tags,
            created_by=created_by,
            project_id=config_data.project_id,
        )
        
        db.add(config)
        db.commit()
        db.refresh(config)
        
        logger.info(f"Created evaluation configuration: {config.id}")
        return ConfigurationResponse.from_orm(config.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating evaluation configuration: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create configuration: {str(e)}"
        )


@router.get("/configs", response_model=ConfigurationListResponse)
async def list_configurations(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    status_filter: Optional[str] = Query(None, pattern="^(draft|published|archived)$", description="Filter by status"),
    task_type_filter: Optional[str] = Query(None, description="Filter by task type"),
    template_filter: Optional[str] = Query(None, description="Filter by template name"),
    project_filter: Optional[str] = Query(None, description="Filter by project ID"),
    created_by_filter: Optional[str] = Query(None, description="Filter by creator"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    current_versions_only: bool = Query(True, description="Show only current versions")
):
    """List evaluation configurations with filtering and pagination."""
    try:
        logger.info(f"Listing configurations with filters - status: {status_filter}, task_type: {task_type_filter}")
        
        # Build base query
        query = db.query(EvaluationConfig)
        
        # Apply current versions filter
        if current_versions_only:
            query = query.filter(EvaluationConfig.is_current_version == True)
        
        # Apply filters
        if status_filter:
            query = query.filter(EvaluationConfig.status == status_filter)
        if task_type_filter:
            query = query.filter(EvaluationConfig.task_type == task_type_filter)
        if template_filter:
            query = query.filter(EvaluationConfig.template_name == template_filter)
        if project_filter:
            query = query.filter(EvaluationConfig.project_id == project_filter)
        if created_by_filter:
            query = query.filter(EvaluationConfig.created_by == created_by_filter)
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    EvaluationConfig.name.ilike(search_term),
                    EvaluationConfig.description.ilike(search_term)
                )
            )
        
        # Get total count before pagination
        filtered_count = query.count()
        total_count = db.query(EvaluationConfig).count()
        
        # Apply pagination and ordering
        query = query.order_by(desc(EvaluationConfig.updated_at))
        offset = (page - 1) * page_size
        configs = query.offset(offset).limit(page_size).all()
        
        # Convert to response format
        config_responses = [ConfigurationResponse.from_orm(config.to_dict()) for config in configs]
        
        return ConfigurationListResponse(
            configurations=config_responses,
            total_count=total_count,
            filtered_count=filtered_count,
            page=page,
            page_size=page_size,
            has_more=filtered_count > (page * page_size)
        )
        
    except Exception as e:
        logger.error(f"Error listing configurations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list configurations: {str(e)}"
        )


@router.get("/configs/{config_id}", response_model=ConfigurationResponse)
async def get_configuration(
    config_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific evaluation configuration by ID."""
    try:
        logger.info(f"Getting configuration: {config_id}")
        
        config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_id} not found"
            )
        
        return ConfigurationResponse.from_orm(config.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting configuration {config_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration: {str(e)}"
        )


@router.put("/configs/{config_id}", response_model=ConfigurationResponse)
async def update_configuration(
    config_id: str,
    update_data: ConfigurationUpdateRequest,
    db: Session = Depends(get_db),
    create_new_version: bool = Query(False, description="Create new version instead of updating in place")
):
    """Update an evaluation configuration."""
    try:
        logger.info(f"Updating configuration: {config_id}, create_version: {create_new_version}")
        
        config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_id} not found"
            )
        
        if create_new_version:
            # Create new version - mark current as not current, create new one
            config.is_current_version = False
            
            new_config = EvaluationConfig(
                name=update_data.name or config.name,
                description=update_data.description or config.description,
                config_key=config.config_key,  # Same key, new version
                version=config.version + 1,
                is_current_version=True,
                parent_config_id=config.id,
                status=update_data.status or config.status,
                task_type=config.task_type,
                template_name=config.template_name,
                task_config=update_data.task_config or config.task_config,
                dataset_config=update_data.dataset_config or config.dataset_config,
                metrics_config=update_data.metrics_config or config.metrics_config,
                execution_config=update_data.execution_config or config.execution_config,
                langfuse_config=update_data.langfuse_config or config.langfuse_config,
                tags=update_data.tags or config.tags,
                created_by=config.created_by,
                project_id=config.project_id,
            )
            
            db.add(new_config)
            db.commit()
            db.refresh(new_config)
            
            logger.info(f"Created new version {new_config.version} of configuration: {config_id}")
            return ConfigurationResponse.from_orm(new_config.to_dict())
            
        else:
            # Update in place
            if update_data.name is not None:
                config.name = update_data.name
            if update_data.description is not None:
                config.description = update_data.description
            if update_data.status is not None:
                config.status = update_data.status
            if update_data.task_config is not None:
                config.task_config = update_data.task_config
            if update_data.dataset_config is not None:
                config.dataset_config = update_data.dataset_config
            if update_data.metrics_config is not None:
                config.metrics_config = update_data.metrics_config
            if update_data.execution_config is not None:
                config.execution_config = update_data.execution_config
            if update_data.langfuse_config is not None:
                config.langfuse_config = update_data.langfuse_config
            if update_data.tags is not None:
                config.tags = update_data.tags
            
            config.updated_at = datetime.now(timezone.utc)
            
            db.commit()
            db.refresh(config)
            
            logger.info(f"Updated configuration: {config_id}")
            return ConfigurationResponse.from_orm(config.to_dict())
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating configuration {config_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}"
        )


@router.delete("/configs/{config_id}")
async def delete_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    force_delete: bool = Query(False, description="Force delete even if used in runs")
):
    """Delete an evaluation configuration."""
    try:
        logger.info(f"Deleting configuration: {config_id}, force: {force_delete}")
        
        config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_id} not found"
            )
        
        # Check if configuration is being used (if we have runs referencing it)
        if not force_delete and config.usage_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Configuration is in use ({config.usage_count} times). Use force_delete=true to delete anyway."
            )
        
        db.delete(config)
        db.commit()
        
        logger.info(f"Deleted configuration: {config_id}")
        return {"message": "Configuration deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting configuration {config_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete configuration: {str(e)}"
        )


@router.post("/configs/{config_id}/publish", response_model=ConfigurationResponse)
async def publish_configuration(
    config_id: str,
    db: Session = Depends(get_db)
):
    """Publish a draft configuration."""
    try:
        logger.info(f"Publishing configuration: {config_id}")
        
        config = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_id} not found"
            )
        
        if config.status == "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Configuration is already published"
            )
        
        config.status = "published"
        config.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(config)
        
        logger.info(f"Published configuration: {config_id}")
        return ConfigurationResponse.from_orm(config.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing configuration {config_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish configuration: {str(e)}"
        )


@router.get("/configs/{config_key}/versions", response_model=List[ConfigurationResponse])
async def get_configuration_versions(
    config_key: str,
    db: Session = Depends(get_db)
):
    """Get all versions of a configuration by key."""
    try:
        logger.info(f"Getting configuration versions for key: {config_key}")
        
        configs = db.query(EvaluationConfig).filter(
            EvaluationConfig.config_key == config_key
        ).order_by(desc(EvaluationConfig.version)).all()
        
        if not configs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No configurations found with key '{config_key}'"
            )
        
        return [ConfigurationResponse.from_orm(config.to_dict()) for config in configs]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting configuration versions for {config_key}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration versions: {str(e)}"
        )


@router.post("/recommend-template", response_model=List[TemplateRecommendationResponse])
async def recommend_evaluation_template(
    request: TemplateRecommendationRequest
):
    """Recommend evaluation templates based on description and context."""
    try:
        logger.info(f"Recommending templates for: {request.description[:100]}...")
        
        recommendations = recommend_template(
            input_description=request.description,
            sample_data=request.sample_data,
            use_case=request.use_case
        )
        
        # Convert to response format
        return [
            TemplateRecommendationResponse(
                template_name=rec["template_name"],
                confidence=rec["confidence"],
                name=rec["name"],
                description=rec["description"],
                metrics=rec["metrics"],
                reason=rec["reason"]
            )
            for rec in recommendations[:5]  # Limit to top 5 recommendations
        ]
        
    except Exception as e:
        logger.error(f"Error recommending templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recommend templates: {str(e)}"
        )


@router.post("/configs/{config_id}/duplicate", response_model=ConfigurationResponse)
async def duplicate_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    new_name: Optional[str] = Query(None, description="Name for the duplicated configuration")
):
    """Create a duplicate of an existing configuration."""
    try:
        logger.info(f"Duplicating configuration: {config_id}")
        
        original = db.query(EvaluationConfig).filter(EvaluationConfig.id == config_id).first()
        if not original:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_id} not found"
            )
        
        # Generate new name and config_key
        duplicate_name = new_name or f"{original.name} (Copy)"
        duplicate_key = f"{duplicate_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        
        # Create duplicate
        duplicate = EvaluationConfig(
            name=duplicate_name,
            description=original.description,
            config_key=duplicate_key,
            task_type=original.task_type,
            template_name=original.template_name,
            task_config=original.task_config,
            dataset_config=original.dataset_config,
            metrics_config=original.metrics_config,
            execution_config=original.execution_config,
            langfuse_config=original.langfuse_config,
            tags=original.tags,
            created_by=original.created_by,
            project_id=original.project_id,
        )
        
        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)
        
        logger.info(f"Created duplicate configuration: {duplicate.id}")
        return ConfigurationResponse.from_orm(duplicate.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error duplicating configuration {config_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to duplicate configuration: {str(e)}"
        )


# Task Execution Endpoints

@router.post("/tasks/execute", response_model=TaskExecutionResponse, status_code=status.HTTP_201_CREATED)
async def execute_configuration(
    execution_request: TaskExecutionRequest,
    db: Session = Depends(get_db),
    created_by: Optional[str] = Query(None, description="User executing the task")
):
    """Execute an evaluation configuration as a task."""
    try:
        logger.info(f"Executing configuration: {execution_request.config_id}")
        
        # Verify configuration exists
        config = db.query(EvaluationConfig).filter(EvaluationConfig.id == execution_request.config_id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {execution_request.config_id} not found"
            )
        
        if config.status != "published":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only published configurations can be executed"
            )
        
        # Queue task for execution
        task_engine = get_task_engine()
        execution_id = await task_engine.queue_task(
            config_id=execution_request.config_id,
            task_name=execution_request.task_name,
            priority=execution_request.priority,
            created_by=created_by,
            project_id=execution_request.project_id
        )
        
        # Update configuration usage
        config.usage_count += 1
        config.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        # Get and return execution details
        execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create task execution"
            )
        
        return TaskExecutionResponse.from_orm(execution.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute configuration: {str(e)}"
        )


@router.get("/tasks", response_model=TaskListResponse)
async def list_task_executions(
    db: Session = Depends(get_db),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    created_by: Optional[str] = Query(None, description="Filter by creator"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    active_only: bool = Query(True, description="Show only active (queued, running, paused) tasks")
):
    """List task executions with filtering."""
    try:
        logger.info(f"Listing task executions - project: {project_id}, active_only: {active_only}")
        
        query = db.query(TaskExecution)
        
        if active_only:
            query = query.filter(TaskExecution.status.in_(["queued", "running", "paused"]))
        
        if project_id:
            query = query.filter(TaskExecution.project_id == project_id)
        if created_by:
            query = query.filter(TaskExecution.created_by == created_by)
        if status_filter:
            query = query.filter(TaskExecution.status == status_filter)
        
        # Order by priority (desc) then queued time
        executions = query.order_by(desc(TaskExecution.priority), TaskExecution.queued_at).all()
        
        # Get counts
        total_count = db.query(TaskExecution).count()
        active_count = db.query(TaskExecution).filter(
            TaskExecution.status.in_(["queued", "running", "paused"])
        ).count()
        
        execution_responses = [TaskExecutionResponse.from_orm(execution.to_dict()) for execution in executions]
        
        return TaskListResponse(
            executions=execution_responses,
            total_count=total_count,
            active_count=active_count
        )
        
    except Exception as e:
        logger.error(f"Error listing task executions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list task executions: {str(e)}"
        )


@router.get("/tasks/{execution_id}", response_model=TaskExecutionResponse)
async def get_task_execution(
    execution_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific task execution by ID."""
    try:
        logger.info(f"Getting task execution: {execution_id}")
        
        execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task execution {execution_id} not found"
            )
        
        return TaskExecutionResponse.from_orm(execution.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task execution {execution_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task execution: {str(e)}"
        )


@router.post("/tasks/{execution_id}/pause")
async def pause_task_execution(
    execution_id: str,
    db: Session = Depends(get_db)
):
    """Pause a running task execution."""
    try:
        logger.info(f"Pausing task execution: {execution_id}")
        
        # Verify task exists
        execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task execution {execution_id} not found"
            )
        
        if execution.status != "running":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task is not running (current status: {execution.status})"
            )
        
        # Pause task
        task_engine = get_task_engine()
        success = await task_engine.pause_task(execution_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to pause task"
            )
        
        return {"message": "Task paused successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing task {execution_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause task: {str(e)}"
        )


@router.post("/tasks/{execution_id}/resume")
async def resume_task_execution(
    execution_id: str,
    db: Session = Depends(get_db)
):
    """Resume a paused task execution."""
    try:
        logger.info(f"Resuming task execution: {execution_id}")
        
        # Verify task exists
        execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task execution {execution_id} not found"
            )
        
        if execution.status != "paused":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task is not paused (current status: {execution.status})"
            )
        
        # Resume task
        task_engine = get_task_engine()
        success = await task_engine.resume_task(execution_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resume task"
            )
        
        return {"message": "Task resumed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming task {execution_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume task: {str(e)}"
        )


@router.post("/tasks/{execution_id}/cancel")
async def cancel_task_execution(
    execution_id: str,
    db: Session = Depends(get_db)
):
    """Cancel a task execution."""
    try:
        logger.info(f"Cancelling task execution: {execution_id}")
        
        # Verify task exists
        execution = db.query(TaskExecution).filter(TaskExecution.id == execution_id).first()
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task execution {execution_id} not found"
            )
        
        if execution.status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task is already finished (current status: {execution.status})"
            )
        
        # Cancel task
        task_engine = get_task_engine()
        success = await task_engine.cancel_task(execution_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel task"
            )
        
        return {"message": "Task cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {execution_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel task: {str(e)}"
        )


# Metric Configuration Endpoints

@router.get("/metrics")
async def list_available_metrics(
    category: Optional[str] = Query(None, description="Filter by metric category"),
    tags: Optional[str] = Query(None, description="Comma-separated list of tags to filter by"),
    metric_type: Optional[str] = Query(None, description="Filter by metric type")
):
    """List all available metrics with their configurations."""
    try:
        logger.info(f"Listing metrics - category: {category}, tags: {tags}, type: {metric_type}")
        
        registry = get_metric_registry()
        
        # Parse tags
        tag_list = None
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        # Parse metric type
        from ...metrics.configuration import MetricType
        metric_type_enum = None
        if metric_type:
            try:
                metric_type_enum = MetricType(metric_type.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid metric type: {metric_type}"
                )
        
        metrics = registry.list_metrics(
            category=category,
            tags=tag_list,
            metric_type=metric_type_enum
        )
        
        # Convert to response format
        metric_data = []
        for metric in metrics:
            metric_data.append({
                "name": metric.name,
                "display_name": metric.display_name,
                "description": metric.description,
                "metric_type": metric.metric_type.value,
                "category": metric.category,
                "tags": metric.tags,
                "min_score": metric.min_score,
                "max_score": metric.max_score,
                "higher_is_better": metric.higher_is_better,
                "requires_reference": metric.requires_reference,
                "supports_batch": metric.supports_batch,
                "parameters": [
                    {
                        "name": param.name,
                        "type": param.type.value,
                        "description": param.description,
                        "default": param.default,
                        "required": param.required,
                        "min_value": param.min_value,
                        "max_value": param.max_value,
                        "options": param.options
                    }
                    for param in metric.parameters
                ],
                "default_config": metric.get_default_config()
            })
        
        return {
            "metrics": metric_data,
            "total_count": len(metric_data),
            "categories": registry.get_categories(),
            "available_tags": registry.get_tags()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list metrics: {str(e)}"
        )


@router.get("/metrics/{metric_name}")
async def get_metric_details(metric_name: str):
    """Get detailed information about a specific metric."""
    try:
        logger.info(f"Getting metric details: {metric_name}")
        
        registry = get_metric_registry()
        metric = registry.get_metric(metric_name)
        
        if not metric:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Metric '{metric_name}' not found"
            )
        
        return {
            "name": metric.name,
            "display_name": metric.display_name,
            "description": metric.description,
            "metric_type": metric.metric_type.value,
            "category": metric.category,
            "tags": metric.tags,
            "min_score": metric.min_score,
            "max_score": metric.max_score,
            "higher_is_better": metric.higher_is_better,
            "requires_reference": metric.requires_reference,
            "supports_batch": metric.supports_batch,
            "parameters": [
                {
                    "name": param.name,
                    "type": param.type.value,
                    "description": param.description,
                    "default": param.default,
                    "required": param.required,
                    "min_value": param.min_value,
                    "max_value": param.max_value,
                    "options": param.options,
                    "validation_regex": param.validation_regex
                }
                for param in metric.parameters
            ],
            "default_config": metric.get_default_config()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metric details {metric_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metric details: {str(e)}"
        )


@router.post("/metrics/validate", response_model=MetricConfigurationResponse)
async def validate_metric_configuration(
    config_request: MetricConfigurationRequest
):
    """Validate a metric configuration."""
    try:
        logger.info(f"Validating metric configuration: {config_request.metric_name}")
        
        registry = get_metric_registry()
        
        # Check if metric exists
        metric = registry.get_metric(config_request.metric_name)
        if not metric:
            return MetricConfigurationResponse(
                metric_name=config_request.metric_name,
                is_valid=False,
                errors=[f"Unknown metric: {config_request.metric_name}"],
                validated_parameters=None,
                default_parameters={}
            )
        
        # Validate configuration
        is_valid, errors = registry.validate_config(
            config_request.metric_name, 
            config_request.parameters
        )
        
        return MetricConfigurationResponse(
            metric_name=config_request.metric_name,
            is_valid=is_valid,
            errors=errors,
            validated_parameters=config_request.parameters if is_valid else None,
            default_parameters=metric.get_default_config()
        )
        
    except Exception as e:
        logger.error(f"Error validating metric configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate metric configuration: {str(e)}"
        )


@router.post("/metrics/validate-batch")
async def validate_metrics_configuration(
    metrics_config: Dict[str, Any]
):
    """Validate a complete metrics configuration (multiple metrics)."""
    try:
        logger.info(f"Validating metrics configuration with {len(metrics_config.get('metrics', []))} metrics")
        
        validator = get_metric_validator()
        is_valid, errors = validator.validate_metrics_config(metrics_config)
        
        return {
            "is_valid": is_valid,
            "errors": errors,
            "metrics_count": len(metrics_config.get('metrics', []))
        }
        
    except Exception as e:
        logger.error(f"Error validating metrics configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate metrics configuration: {str(e)}"
        )


@router.post("/metrics/preview", response_model=MetricPreviewResponse)
async def preview_metric(
    preview_request: MetricPreviewRequest
):
    """Preview a metric with sample data."""
    try:
        logger.info(f"Previewing metric: {preview_request.metric_name} with {len(preview_request.sample_data)} samples")
        
        registry = get_metric_registry()
        
        # Check if metric exists
        metric = registry.get_metric(preview_request.metric_name)
        if not metric:
            return MetricPreviewResponse(
                metric_name=preview_request.metric_name,
                is_valid=False,
                errors=[f"Unknown metric: {preview_request.metric_name}"],
                preview_results=None,
                summary_stats=None
            )
        
        # Validate configuration
        is_valid, errors = registry.validate_config(
            preview_request.metric_name, 
            preview_request.parameters
        )
        
        if not is_valid:
            return MetricPreviewResponse(
                metric_name=preview_request.metric_name,
                is_valid=False,
                errors=errors,
                preview_results=None,
                summary_stats=None
            )
        
        # Run metric preview (simplified simulation)
        preview_results = []
        scores = []
        
        for i, sample in enumerate(preview_request.sample_data):
            # Simulate metric calculation based on metric type
            score = _simulate_metric_score(metric, sample, preview_request.parameters)
            
            preview_results.append({
                "sample_index": i,
                "input": sample.get("input", ""),
                "expected_output": sample.get("expected_output", ""),
                "actual_output": sample.get("actual_output", sample.get("expected_output", "")),
                "score": score,
                "explanation": f"Simulated {metric.display_name} calculation"
            })
            
            if score is not None:
                scores.append(score)
        
        # Calculate summary statistics
        summary_stats = None
        if scores:
            import numpy as np
            summary_stats = {
                "mean": float(np.mean(scores)),
                "median": float(np.median(scores)),
                "std": float(np.std(scores)),
                "min": float(np.min(scores)),
                "max": float(np.max(scores)),
                "count": len(scores)
            }
        
        return MetricPreviewResponse(
            metric_name=preview_request.metric_name,
            is_valid=True,
            errors=[],
            preview_results=preview_results,
            summary_stats=summary_stats
        )
        
    except Exception as e:
        logger.error(f"Error previewing metric: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview metric: {str(e)}"
        )


def _simulate_metric_score(metric, sample: Dict[str, Any], parameters: Dict[str, Any]) -> Optional[float]:
    """Simulate metric calculation for preview purposes."""
    try:
        import random
        import hashlib
        
        # Create deterministic randomness based on sample content
        content = str(sample.get("input", "")) + str(sample.get("expected_output", ""))
        seed = int(hashlib.md5(content.encode()).hexdigest()[:8], 16)
        random.seed(seed)
        
        # Simulate different metric types
        if metric.name == "exact_match":
            expected = str(sample.get("expected_output", "")).strip()
            actual = str(sample.get("actual_output", expected)).strip()
            
            if not parameters.get("case_sensitive", False):
                expected = expected.lower()
                actual = actual.lower()
            
            return 1.0 if expected == actual else 0.0
            
        elif metric.name in ["bleu", "rouge"]:
            # Simulate text similarity score
            return random.uniform(0.3, 0.9)
            
        elif metric.name == "semantic_similarity":
            # Simulate semantic similarity
            threshold = parameters.get("threshold", 0.8)
            score = random.uniform(0.4, 0.95)
            return score
            
        elif metric.name == "answer_relevance":
            # Simulate relevance scoring
            return random.uniform(0.6, 0.95)
            
        elif metric.name == "toxicity":
            # Simulate toxicity detection (lower is better)
            return random.uniform(0.0, 0.3)
            
        elif metric.name == "bias_detection":
            # Simulate bias detection (lower is better)
            return random.uniform(0.0, 0.4)
            
        else:
            # Default simulation for unknown metrics
            if metric.min_score is not None and metric.max_score is not None:
                return random.uniform(metric.min_score, metric.max_score)
            else:
                return random.uniform(0.0, 1.0)
                
    except Exception as e:
        logger.warning(f"Error simulating metric {metric.name}: {e}")
        return None