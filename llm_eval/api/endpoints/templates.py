"""Template Management API endpoints.

This module provides REST API endpoints for managing evaluation templates
including storage, retrieval, usage tracking, versioning, and import/export.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from ...templates.registry import (
    TEMPLATE_REGISTRY, 
    list_templates, 
    get_template, 
    recommend_template
)
from ...metrics.configuration import get_metric_registry

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for template management
class TemplateInfoResponse(BaseModel):
    """Response model for template information."""
    
    name: str
    display_name: str
    description: str
    use_cases: List[str]
    metrics: List[str]
    aliases: List[str]
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    sample_data: Optional[Dict[str, Any]] = None
    usage_count: int = 0
    last_used: Optional[str] = None
    is_builtin: bool = True


class TemplateUsageStats(BaseModel):
    """Template usage statistics."""
    
    template_name: str
    usage_count: int
    last_used: Optional[str]
    first_used: Optional[str]
    users: List[str]
    projects: List[str]


class TemplateRecommendationRequest(BaseModel):
    """Request for template recommendations."""
    
    description: str = Field(..., min_length=10, description="Description of the evaluation task")
    sample_data: Optional[Dict[str, Any]] = Field(None, description="Sample input/output data")
    use_case: Optional[str] = Field(None, description="Specific use case or domain")
    dataset_name: Optional[str] = Field(None, description="Name of the dataset being evaluated")


class TemplateRecommendationResponse(BaseModel):
    """Response model for template recommendations."""
    
    template_name: str
    confidence: float
    display_name: str
    description: str
    metrics: List[str]
    reason: str
    use_cases: List[str]
    sample_configuration: Dict[str, Any]


class CustomTemplateRequest(BaseModel):
    """Request for creating custom templates."""
    
    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    display_name: str = Field(..., min_length=1, max_length=200, description="Display name")
    description: str = Field(..., min_length=10, description="Template description")
    use_cases: List[str] = Field(..., min_items=1, description="List of use cases")
    metrics: List[str] = Field(..., min_items=1, description="List of metric names")
    category: str = Field("custom", description="Template category")
    tags: Optional[List[str]] = Field(None, description="Template tags")
    sample_data: Optional[Dict[str, Any]] = Field(None, description="Sample input/output data")
    configuration_schema: Optional[Dict[str, Any]] = Field(None, description="Configuration schema")
    
    @validator('name')
    def validate_name(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("Template name must contain only letters, numbers, hyphens, and underscores")
        return v.lower()
    
    @validator('metrics')
    def validate_metrics(cls, v):
        # Validate metrics exist
        registry = get_metric_registry()
        invalid_metrics = [metric for metric in v if not registry.get_metric(metric)]
        if invalid_metrics:
            raise ValueError(f"Unknown metrics: {', '.join(invalid_metrics)}")
        return v


class TemplateExportResponse(BaseModel):
    """Response for template export."""
    
    template_name: str
    export_format: str
    exported_at: str
    data: Dict[str, Any]


# In-memory storage for custom templates and usage stats
# In a real implementation, this would be stored in a database
_custom_templates: Dict[str, Dict[str, Any]] = {}
_template_usage_stats: Dict[str, TemplateUsageStats] = {}


# API Endpoints

@router.get("/", response_model=List[TemplateInfoResponse])
async def list_available_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    include_custom: bool = Query(True, description="Include custom templates"),
    include_usage_stats: bool = Query(True, description="Include usage statistics")
):
    """List all available evaluation templates."""
    try:
        logger.info(f"Listing templates - category: {category}, tags: {tags}")
        
        # Get built-in templates
        builtin_templates = list_templates()
        templates = []
        
        # Parse tags filter
        tag_filter = None
        if tags:
            tag_filter = [tag.strip().lower() for tag in tags.split(',') if tag.strip()]
        
        # Process built-in templates
        for template_name, info in builtin_templates.items():
            # Apply filters
            if category and info.get('category', 'general').lower() != category.lower():
                continue
            
            if tag_filter:
                template_tags = [tag.lower() for tag in info.get('tags', [])]
                if not any(filter_tag in template_tags for filter_tag in tag_filter):
                    continue
            
            # Get usage stats
            usage_stats = _template_usage_stats.get(template_name)
            usage_count = usage_stats.usage_count if usage_stats else 0
            last_used = usage_stats.last_used if usage_stats else None
            
            template_response = TemplateInfoResponse(
                name=template_name,
                display_name=info['name'],
                description=info['description'],
                use_cases=info['use_cases'],
                metrics=info['metrics'],
                aliases=info['aliases'],
                category=info.get('category', 'general'),
                tags=info.get('tags', []),
                usage_count=usage_count,
                last_used=last_used,
                is_builtin=True
            )
            templates.append(template_response)
        
        # Add custom templates if requested
        if include_custom:
            for template_name, custom_info in _custom_templates.items():
                # Apply filters
                if category and custom_info.get('category', 'custom').lower() != category.lower():
                    continue
                
                if tag_filter:
                    template_tags = [tag.lower() for tag in custom_info.get('tags', [])]
                    if not any(filter_tag in template_tags for filter_tag in tag_filter):
                        continue
                
                # Get usage stats
                usage_stats = _template_usage_stats.get(template_name)
                usage_count = usage_stats.usage_count if usage_stats else 0
                last_used = usage_stats.last_used if usage_stats else None
                
                template_response = TemplateInfoResponse(
                    name=template_name,
                    display_name=custom_info['display_name'],
                    description=custom_info['description'],
                    use_cases=custom_info['use_cases'],
                    metrics=custom_info['metrics'],
                    aliases=[template_name],
                    category=custom_info.get('category', 'custom'),
                    tags=custom_info.get('tags', []),
                    sample_data=custom_info.get('sample_data'),
                    usage_count=usage_count,
                    last_used=last_used,
                    is_builtin=False
                )
                templates.append(template_response)
        
        # Sort by usage count (desc) then by name
        templates.sort(key=lambda t: (-t.usage_count, t.name))
        
        logger.info(f"Returning {len(templates)} templates")
        return templates
        
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list templates: {str(e)}"
        )


@router.get("/{template_name}", response_model=TemplateInfoResponse)
async def get_template_details(template_name: str):
    """Get detailed information about a specific template."""
    try:
        logger.info(f"Getting template details: {template_name}")
        
        # Check built-in templates first
        builtin_templates = list_templates()
        if template_name in builtin_templates:
            info = builtin_templates[template_name]
            
            # Get usage stats
            usage_stats = _template_usage_stats.get(template_name)
            usage_count = usage_stats.usage_count if usage_stats else 0
            last_used = usage_stats.last_used if usage_stats else None
            
            return TemplateInfoResponse(
                name=template_name,
                display_name=info['name'],
                description=info['description'],
                use_cases=info['use_cases'],
                metrics=info['metrics'],
                aliases=info['aliases'],
                category=info.get('category', 'general'),
                tags=info.get('tags', []),
                usage_count=usage_count,
                last_used=last_used,
                is_builtin=True
            )
        
        # Check custom templates
        if template_name in _custom_templates:
            custom_info = _custom_templates[template_name]
            
            # Get usage stats
            usage_stats = _template_usage_stats.get(template_name)
            usage_count = usage_stats.usage_count if usage_stats else 0
            last_used = usage_stats.last_used if usage_stats else None
            
            return TemplateInfoResponse(
                name=template_name,
                display_name=custom_info['display_name'],
                description=custom_info['description'],
                use_cases=custom_info['use_cases'],
                metrics=custom_info['metrics'],
                aliases=[template_name],
                category=custom_info.get('category', 'custom'),
                tags=custom_info.get('tags', []),
                sample_data=custom_info.get('sample_data'),
                usage_count=usage_count,
                last_used=last_used,
                is_builtin=False
            )
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_name}' not found"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {template_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get template: {str(e)}"
        )


@router.post("/recommend", response_model=List[TemplateRecommendationResponse])
async def recommend_templates(request: TemplateRecommendationRequest):
    """Get template recommendations based on description and context."""
    try:
        logger.info(f"Recommending templates for: {request.description[:100]}...")
        
        # Get recommendations from the template registry
        recommendations = recommend_template(
            input_description=request.description,
            sample_data=request.sample_data,
            use_case=request.use_case
        )
        
        # Convert to response format with enhanced information
        response_recommendations = []
        
        for rec in recommendations[:5]:  # Limit to top 5
            template = get_template(rec['template_name'])
            
            # Create sample configuration
            sample_config = {
                "task_type": rec['template_name'],
                "template_name": rec['template_name'],
                "metrics": rec['metrics'][:3],  # Limit to top 3 metrics
                "dataset_config": {
                    "dataset_name": request.dataset_name or "your_dataset",
                    "filters": {}
                },
                "task_config": {
                    "description": request.description[:200] + "..." if len(request.description) > 200 else request.description
                }
            }
            
            response_rec = TemplateRecommendationResponse(
                template_name=rec['template_name'],
                confidence=rec['confidence'],
                display_name=rec['name'],
                description=rec['description'],
                metrics=rec['metrics'],
                reason=rec['reason'],
                use_cases=template.config.use_cases if template else [],
                sample_configuration=sample_config
            )
            response_recommendations.append(response_rec)
        
        return response_recommendations
        
    except Exception as e:
        logger.error(f"Error recommending templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recommend templates: {str(e)}"
        )


@router.post("/custom", response_model=TemplateInfoResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_template(request: CustomTemplateRequest):
    """Create a new custom template."""
    try:
        logger.info(f"Creating custom template: {request.name}")
        
        # Check if template already exists
        if request.name in TEMPLATE_REGISTRY or request.name in _custom_templates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Template '{request.name}' already exists"
            )
        
        # Store custom template
        template_data = {
            "name": request.name,
            "display_name": request.display_name,
            "description": request.description,
            "use_cases": request.use_cases,
            "metrics": request.metrics,
            "category": request.category,
            "tags": request.tags or [],
            "sample_data": request.sample_data,
            "configuration_schema": request.configuration_schema,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1
        }
        
        _custom_templates[request.name] = template_data
        
        # Initialize usage stats
        _template_usage_stats[request.name] = TemplateUsageStats(
            template_name=request.name,
            usage_count=0,
            last_used=None,
            first_used=None,
            users=[],
            projects=[]
        )
        
        logger.info(f"Created custom template: {request.name}")
        
        return TemplateInfoResponse(
            name=request.name,
            display_name=request.display_name,
            description=request.description,
            use_cases=request.use_cases,
            metrics=request.metrics,
            aliases=[request.name],
            category=request.category,
            tags=request.tags or [],
            sample_data=request.sample_data,
            usage_count=0,
            last_used=None,
            is_builtin=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating custom template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create custom template: {str(e)}"
        )


@router.put("/custom/{template_name}", response_model=TemplateInfoResponse)
async def update_custom_template(template_name: str, request: CustomTemplateRequest):
    """Update an existing custom template."""
    try:
        logger.info(f"Updating custom template: {template_name}")
        
        if template_name not in _custom_templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Custom template '{template_name}' not found"
            )
        
        # Update template data
        template_data = _custom_templates[template_name]
        template_data.update({
            "display_name": request.display_name,
            "description": request.description,
            "use_cases": request.use_cases,
            "metrics": request.metrics,
            "category": request.category,
            "tags": request.tags or [],
            "sample_data": request.sample_data,
            "configuration_schema": request.configuration_schema,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "version": template_data.get("version", 1) + 1
        })
        
        # Get usage stats
        usage_stats = _template_usage_stats.get(template_name)
        usage_count = usage_stats.usage_count if usage_stats else 0
        last_used = usage_stats.last_used if usage_stats else None
        
        logger.info(f"Updated custom template: {template_name}")
        
        return TemplateInfoResponse(
            name=template_name,
            display_name=request.display_name,
            description=request.description,
            use_cases=request.use_cases,
            metrics=request.metrics,
            aliases=[template_name],
            category=request.category,
            tags=request.tags or [],
            sample_data=request.sample_data,
            usage_count=usage_count,
            last_used=last_used,
            is_builtin=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating custom template {template_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update custom template: {str(e)}"
        )


@router.delete("/custom/{template_name}")
async def delete_custom_template(template_name: str):
    """Delete a custom template."""
    try:
        logger.info(f"Deleting custom template: {template_name}")
        
        if template_name not in _custom_templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Custom template '{template_name}' not found"
            )
        
        # Remove template and stats
        del _custom_templates[template_name]
        if template_name in _template_usage_stats:
            del _template_usage_stats[template_name]
        
        logger.info(f"Deleted custom template: {template_name}")
        return {"message": f"Template '{template_name}' deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting custom template {template_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete custom template: {str(e)}"
        )


@router.post("/{template_name}/track-usage")
async def track_template_usage(
    template_name: str,
    user: Optional[str] = Query(None, description="User who used the template"),
    project: Optional[str] = Query(None, description="Project where template was used")
):
    """Track usage of a template."""
    try:
        logger.info(f"Tracking usage for template: {template_name}")
        
        # Verify template exists
        builtin_templates = list_templates()
        if template_name not in builtin_templates and template_name not in _custom_templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template '{template_name}' not found"
            )
        
        # Update usage stats
        now = datetime.now(timezone.utc).isoformat()
        
        if template_name not in _template_usage_stats:
            _template_usage_stats[template_name] = TemplateUsageStats(
                template_name=template_name,
                usage_count=0,
                last_used=None,
                first_used=None,
                users=[],
                projects=[]
            )
        
        stats = _template_usage_stats[template_name]
        stats.usage_count += 1
        stats.last_used = now
        
        if not stats.first_used:
            stats.first_used = now
        
        # Track user and project
        if user and user not in stats.users:
            stats.users.append(user)
        if project and project not in stats.projects:
            stats.projects.append(project)
        
        return {
            "message": "Usage tracked successfully",
            "usage_count": stats.usage_count,
            "last_used": stats.last_used
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking template usage: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to track template usage: {str(e)}"
        )


@router.get("/{template_name}/usage", response_model=TemplateUsageStats)
async def get_template_usage_stats(template_name: str):
    """Get usage statistics for a template."""
    try:
        logger.info(f"Getting usage stats for template: {template_name}")
        
        if template_name not in _template_usage_stats:
            # Return empty stats if no usage recorded
            return TemplateUsageStats(
                template_name=template_name,
                usage_count=0,
                last_used=None,
                first_used=None,
                users=[],
                projects=[]
            )
        
        return _template_usage_stats[template_name]
        
    except Exception as e:
        logger.error(f"Error getting template usage stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get template usage stats: {str(e)}"
        )


@router.get("/{template_name}/export", response_model=TemplateExportResponse)
async def export_template(
    template_name: str,
    format: str = Query("json", description="Export format (json, yaml)")
):
    """Export a template configuration."""
    try:
        logger.info(f"Exporting template: {template_name} as {format}")
        
        template_data = None
        
        # Get template data
        builtin_templates = list_templates()
        if template_name in builtin_templates:
            template_data = {
                "name": template_name,
                "type": "builtin",
                "info": builtin_templates[template_name],
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "export_version": "1.0"
            }
        elif template_name in _custom_templates:
            template_data = {
                "name": template_name,
                "type": "custom",
                "info": _custom_templates[template_name],
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "export_version": "1.0"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template '{template_name}' not found"
            )
        
        if format.lower() not in ["json", "yaml"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Export format must be 'json' or 'yaml'"
            )
        
        return TemplateExportResponse(
            template_name=template_name,
            export_format=format,
            exported_at=datetime.now(timezone.utc).isoformat(),
            data=template_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting template {template_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export template: {str(e)}"
        )


@router.post("/import")
async def import_template(file: UploadFile = File(...)):
    """Import a template from file."""
    try:
        logger.info(f"Importing template from file: {file.filename}")
        
        if not file.filename.endswith(('.json', '.yaml', '.yml')):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be JSON or YAML format"
            )
        
        # Read file content
        content = await file.read()
        
        # Parse content
        if file.filename.endswith('.json'):
            template_data = json.loads(content.decode('utf-8'))
        else:
            import yaml
            template_data = yaml.safe_load(content.decode('utf-8'))
        
        # Validate template structure
        if not all(key in template_data for key in ['name', 'type', 'info']):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid template file structure"
            )
        
        template_name = template_data['name']
        template_info = template_data['info']
        
        # Check if template already exists
        if template_name in TEMPLATE_REGISTRY or template_name in _custom_templates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Template '{template_name}' already exists"
            )
        
        # Import as custom template
        if template_data['type'] == 'custom':
            _custom_templates[template_name] = template_info
            
            # Initialize usage stats
            _template_usage_stats[template_name] = TemplateUsageStats(
                template_name=template_name,
                usage_count=0,
                last_used=None,
                first_used=None,
                users=[],
                projects=[]
            )
        
        logger.info(f"Successfully imported template: {template_name}")
        
        return {
            "message": f"Template '{template_name}' imported successfully",
            "template_name": template_name,
            "type": template_data['type']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import template: {str(e)}"
        )