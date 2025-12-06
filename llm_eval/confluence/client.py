"""Confluence client for publishing evaluation runs.

This module provides both a mock filesystem-based client for development/testing
and a real Confluence API client for production use.
"""

import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class User:
    """Confluence user."""
    username: str
    display_name: str


@dataclass
class Project:
    """Confluence project (folder)."""
    project_id: str
    name: str
    description: str
    owner: str


@dataclass
class TaskPage:
    """Confluence task page."""
    page_id: str
    title: str
    project: str


@dataclass
class PublishRequest:
    """Request to publish an evaluation run to Confluence."""
    project_name: str
    task_name: str
    run_id: str
    published_by: str
    description: str
    metrics: Dict[str, float]
    model: str
    dataset: str
    total_items: int
    success_count: int
    error_count: int
    avg_latency_ms: float
    branch: Optional[str] = None
    commit: Optional[str] = None
    trace_url: Optional[str] = None


@dataclass
class MetricThreshold:
    """Threshold configuration for a metric in aggregate publish."""
    metric_name: str
    threshold: float  # 0.0 to 1.0


@dataclass
class AggregateMetricResult:
    """Calculated aggregate metrics for a single metric."""
    metric_name: str
    threshold: float
    pass_at_k: float  # Fraction of items where at least one run passed
    pass_k: float  # Fraction of items where all runs passed
    max_at_k: float  # Average of best score per item across K runs
    consistency: float  # How often runs agree on pass/fail (0% = 50/50 split, 100% = all agree)
    reliability: float  # Average pass rate per item across K runs
    avg_score: float
    min_score: float
    max_score: float
    runs_passed: int
    total_runs: int


@dataclass
class RunMetricDetail:
    """Metric details for a single run in aggregate publish."""
    run_id: str
    langfuse_url: Optional[str]
    metrics: Dict[str, float]  # metric_name -> score
    latency_ms: float


@dataclass
class AggregatePublishRequest:
    """Request to publish aggregate metrics for K runs to Confluence."""
    project_name: str
    task_name: str
    run_name: str  # User-editable name for this aggregate publish
    published_by: str
    description: str
    model: str
    dataset: str
    task: str  # The eval task name
    k_runs: int  # Number of runs
    run_details: List[RunMetricDetail]  # Per-run metrics and details
    metric_results: List[AggregateMetricResult]  # Aggregate results per metric with thresholds
    total_items_per_run: int  # Average items per run
    avg_latency_ms: float
    branch: Optional[str] = None
    commit: Optional[str] = None


@dataclass
class PublishResult:
    """Result of publishing to Confluence."""
    success: bool
    page_id: Optional[str] = None
    page_url: Optional[str] = None
    error: Optional[str] = None


def get_git_info() -> Dict[str, Optional[str]]:
    """Get current git branch and commit hash."""
    info = {"branch": None, "commit": None}

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()

        # Get current commit (short hash)
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            info["commit"] = result.stdout.strip()
    except Exception:
        pass

    return info


class ConfluenceClient(ABC):
    """Abstract base class for Confluence clients."""

    @abstractmethod
    def list_projects(self) -> List[Project]:
        """List all projects (folders) in the space."""
        pass

    @abstractmethod
    def list_tasks(self, project_name: str) -> List[TaskPage]:
        """List all task pages in a project."""
        pass

    @abstractmethod
    def search_users(self, query: str) -> List[User]:
        """Search for users by name or username."""
        pass

    @abstractmethod
    def list_users(self) -> List[User]:
        """List all available users."""
        pass

    @abstractmethod
    def publish_run(self, request: PublishRequest) -> PublishResult:
        """Publish an evaluation run to a task page."""
        pass

    @abstractmethod
    def create_project(self, name: str, description: str, owner: str) -> Project:
        """Create a new project folder."""
        pass

    @abstractmethod
    def create_task(self, project_name: str, task_name: str) -> TaskPage:
        """Create a new task page in a project."""
        pass

    @abstractmethod
    def publish_aggregate_run(self, request: AggregatePublishRequest) -> PublishResult:
        """Publish aggregate metrics for K runs to a task page."""
        pass


class MockConfluenceClient(ConfluenceClient):
    """Mock Confluence client using filesystem for development/testing."""

    def __init__(self, base_path: str = "confluence_mock"):
        self.base_path = Path(base_path)
        self.projects_path = self.base_path / "projects"

        # Ensure directories exist
        self.projects_path.mkdir(parents=True, exist_ok=True)

        # Load config
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load space configuration."""
        config_path = self.base_path / "_config.json"
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
        return {"users": [], "settings": {}}

    def _save_config(self) -> None:
        """Save space configuration."""
        config_path = self.base_path / "_config.json"
        with open(config_path, "w") as f:
            json.dump(self._config, f, indent=2)

    def _sanitize_name(self, name: str) -> str:
        """Convert name to filesystem-safe format."""
        # Replace spaces and special chars with hyphens
        sanitized = re.sub(r'[^\w\s-]', '', name.lower())
        sanitized = re.sub(r'[-\s]+', '-', sanitized).strip('-')
        return sanitized

    def list_projects(self) -> List[Project]:
        """List all projects from filesystem."""
        projects = []

        if not self.projects_path.exists():
            return projects

        for project_dir in self.projects_path.iterdir():
            if not project_dir.is_dir():
                continue

            project_file = project_dir / "_project.json"
            if project_file.exists():
                with open(project_file) as f:
                    data = json.load(f)
                    projects.append(Project(
                        project_id=data.get("project_id", project_dir.name),
                        name=data.get("name", project_dir.name),
                        description=data.get("description", ""),
                        owner=data.get("owner", "")
                    ))

        return sorted(projects, key=lambda p: p.name)

    def list_tasks(self, project_name: str) -> List[TaskPage]:
        """List all task pages in a project."""
        tasks = []

        # Find project directory
        project_dir = self._find_project_dir(project_name)
        if not project_dir:
            return tasks

        for task_file in project_dir.glob("*.md"):
            if task_file.name.startswith("_"):
                continue

            # Extract title from filename (convert kebab-case to title case)
            title = task_file.stem.replace("-", " ").title()

            # Try to extract title from first line if it's a markdown heading
            try:
                with open(task_file) as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("# "):
                        title = first_line[2:].strip()
            except Exception:
                pass

            tasks.append(TaskPage(
                page_id=task_file.stem,
                title=title,
                project=project_name
            ))

        return sorted(tasks, key=lambda t: t.title)

    def _find_project_dir(self, project_name: str) -> Optional[Path]:
        """Find project directory by name."""
        # First try exact match with sanitized name
        sanitized = self._sanitize_name(project_name)
        direct_path = self.projects_path / sanitized
        if direct_path.exists():
            return direct_path

        # Search through all projects
        for project_dir in self.projects_path.iterdir():
            if not project_dir.is_dir():
                continue
            project_file = project_dir / "_project.json"
            if project_file.exists():
                with open(project_file) as f:
                    data = json.load(f)
                    if data.get("name") == project_name:
                        return project_dir

        return None

    def search_users(self, query: str) -> List[User]:
        """Search users by query string."""
        query = query.lower()
        users = []

        for user_data in self._config.get("users", []):
            if (query in user_data["username"].lower() or
                query in user_data["display_name"].lower()):
                users.append(User(
                    username=user_data["username"],
                    display_name=user_data["display_name"]
                ))

        return users

    def list_users(self) -> List[User]:
        """List all available users."""
        return [
            User(username=u["username"], display_name=u["display_name"])
            for u in self._config.get("users", [])
        ]

    def publish_run(self, request: PublishRequest) -> PublishResult:
        """Publish a run to the mock filesystem as markdown."""
        # Find or create project directory
        project_dir = self._find_project_dir(request.project_name)
        if not project_dir:
            return PublishResult(
                success=False,
                error=f"Project not found: {request.project_name}"
            )

        # Find or create task file
        task_file = self._find_task_file(project_dir, request.task_name)
        if not task_file:
            # Create new task page
            task_file = project_dir / f"{self._sanitize_name(request.task_name)}.md"
            existing_content = ""
        else:
            with open(task_file) as f:
                existing_content = f.read()

        # Format the run section as markdown
        published_at = datetime.now().strftime("%B %d, %Y at %H:%M")
        success_rate = (request.success_count / request.total_items * 100) if request.total_items > 0 else 0

        # Format latency as human readable
        latency_ms = request.avg_latency_ms
        if latency_ms >= 60000:
            minutes = int(latency_ms // 60000)
            seconds = (latency_ms % 60000) / 1000
            latency_str = f"{minutes}m {seconds:.0f}s"
        elif latency_ms >= 1000:
            latency_str = f"{latency_ms / 1000:.1f}s"
        else:
            latency_str = f"{latency_ms:.0f}ms"

        # Format metrics as a table (including latency)
        metrics_rows = []
        for name, value in request.metrics.items():
            if isinstance(value, (int, float)):
                pct = value * 100
                metrics_rows.append(f"| {name.replace('_', ' ').title()} | {pct:.1f}% |")

        # Add latency as a metric row
        metrics_rows.append(f"| Latency | {latency_str} |")

        if metrics_rows:
            metrics_table = "| Metric | Score |\n|:-------|------:|\n" + "\n".join(metrics_rows)
        else:
            metrics_table = "_No metrics recorded_"

        # Create anchor-friendly ID for the run
        run_anchor = self._sanitize_name(request.run_id)

        # Format trace link if available
        trace_row = f"| **Traces** | [View in Langfuse]({request.trace_url}) |" if request.trace_url else ""

        run_section = f"""
---

## {request.run_id}

> **Published:** {published_at} | **Author:** @{request.published_by}

### Summary

{request.description}

### Performance Metrics

{metrics_table}

### Run Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | {request.model} |
| **Dataset** | {request.dataset} |
| **Total Samples** | {request.total_items:,} |
| **Success Rate** | {success_rate:.1f}% ({request.success_count:,}/{request.total_items:,}) |
| **Errors** | {request.error_count:,} |
{trace_row}

### Source Control

| | |
|:--|:--|
| **Branch** | `{request.branch or 'N/A'}` |
| **Commit** | `{request.commit or 'N/A'}` |
"""

        # Build content with TOC
        if not existing_content:
            # New file - create header and TOC with first entry
            header = f"""# {request.task_name}

**Project:** {request.project_name}

This page documents evaluation runs for the **{request.task_name}** task. Each run includes performance metrics, configuration details, and approval status.

## Evaluation History

"""
            toc_entry = f"| [{request.run_id}](#{run_anchor}) | {published_at} | @{request.published_by} |\n"
            toc_header = "| Run ID | Date | Author |\n|:-------|:-----|:-------|\n"
            content = header + toc_header + toc_entry + run_section
        else:
            # Existing file - update history table and append run
            toc_marker = "## Evaluation History\n\n"
            old_toc_marker = "## Table of Contents\n\n"

            # Check for new format first, then old format
            if toc_marker in existing_content:
                # Find the table and add new entry
                toc_start = existing_content.index(toc_marker)
                toc_content_start = toc_start + len(toc_marker)

                # Find where the table ends (first \n--- after table, or end of file)
                rest_of_content = existing_content[toc_content_start:]
                first_separator = rest_of_content.find("\n---")

                new_toc_entry = f"| [{request.run_id}](#{run_anchor}) | {published_at} | @{request.published_by} | Single |\n"

                if first_separator != -1:
                    # Insert new table row at the end of existing table
                    table_content = rest_of_content[:first_separator]
                    after_table = rest_of_content[first_separator:]

                    content = (existing_content[:toc_content_start] +
                              table_content + new_toc_entry +
                              after_table + run_section)
                else:
                    # No runs yet - table header exists but no separator
                    # Append entry to table and add run section
                    content = existing_content.rstrip() + "\n" + new_toc_entry + run_section
            elif old_toc_marker in existing_content:
                # Old format - just append
                content = existing_content + run_section
            else:
                # No TOC exists, just append
                content = existing_content + run_section

        # Save task file
        with open(task_file, "w") as f:
            f.write(content)

        return PublishResult(
            success=True,
            page_id=task_file.stem,
            page_url=f"file://{task_file.absolute()}"
        )

    def _find_task_file(self, project_dir: Path, task_name: str) -> Optional[Path]:
        """Find task file by name."""
        sanitized = self._sanitize_name(task_name)
        direct_path = project_dir / f"{sanitized}.md"
        if direct_path.exists():
            return direct_path

        # Search through all task files by checking title in first line
        for task_file in project_dir.glob("*.md"):
            if task_file.name.startswith("_"):
                continue
            try:
                with open(task_file) as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("# "):
                        title = first_line[2:].strip()
                        if title == task_name:
                            return task_file
            except Exception:
                pass

        return None

    def create_project(self, name: str, description: str, owner: str) -> Project:
        """Create a new project folder."""
        sanitized = self._sanitize_name(name)
        project_dir = self.projects_path / sanitized
        project_dir.mkdir(parents=True, exist_ok=True)

        project_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        project_data = {
            "project_id": project_id,
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "owner": owner
        }

        with open(project_dir / "_project.json", "w") as f:
            json.dump(project_data, f, indent=2)

        return Project(
            project_id=project_id,
            name=name,
            description=description,
            owner=owner
        )

    def create_task(self, project_name: str, task_name: str) -> TaskPage:
        """Create a new task page as markdown."""
        project_dir = self._find_project_dir(project_name)
        if not project_dir:
            raise ValueError(f"Project not found: {project_name}")

        page_id = self._sanitize_name(task_name)

        # Create markdown file with full header including evaluation history table
        content = f"""# {task_name}

**Project:** {project_name}

This page documents evaluation runs for the **{task_name}** task. Each run includes performance metrics, configuration details, and approval status.

## Evaluation History

| Run ID | Date | Author | Type |
|:-------|:-----|:-------|:-----|
"""

        task_file = project_dir / f"{page_id}.md"
        with open(task_file, "w") as f:
            f.write(content)

        return TaskPage(
            page_id=page_id,
            title=task_name,
            project=project_name
        )

    def publish_aggregate_run(self, request: AggregatePublishRequest) -> PublishResult:
        """Publish aggregate metrics for K runs to the mock filesystem as markdown."""
        # Find or create project directory
        project_dir = self._find_project_dir(request.project_name)
        if not project_dir:
            return PublishResult(
                success=False,
                error=f"Project not found: {request.project_name}"
            )

        # Find or create task file
        task_file = self._find_task_file(project_dir, request.task_name)
        if not task_file:
            task_file = project_dir / f"{self._sanitize_name(request.task_name)}.md"
            existing_content = ""
        else:
            with open(task_file) as f:
                existing_content = f.read()

        # Format the aggregate run section as markdown
        published_at = datetime.now().strftime("%B %d, %Y at %H:%M")

        # Format latency as human readable
        latency_ms = request.avg_latency_ms
        if latency_ms >= 60000:
            minutes = int(latency_ms // 60000)
            seconds = (latency_ms % 60000) / 1000
            latency_str = f"{minutes}m {seconds:.0f}s"
        elif latency_ms >= 1000:
            latency_str = f"{latency_ms / 1000:.1f}s"
        else:
            latency_str = f"{latency_ms:.0f}ms"

        # Helper to format latency
        def format_latency(ms: float) -> str:
            if ms >= 60000:
                minutes = int(ms // 60000)
                seconds = (ms % 60000) / 1000
                return f"{minutes}m {seconds:.0f}s"
            elif ms >= 1000:
                return f"{ms / 1000:.1f}s"
            else:
                return f"{ms:.0f}ms"

        # Get all metric names from run details
        metric_names = list(request.run_details[0].metrics.keys()) if request.run_details else []

        # Build per-run details table
        # Header: Run ID | Metric1 | Metric2 | ... | Latency | Langfuse
        metric_headers = " | ".join(m.replace('_', ' ').title() for m in metric_names)
        run_table_header = f"| Run | {metric_headers} | Latency | Langfuse |"
        # Separator: one for Run (left-align), one for each metric (center), one for Latency (center), one for Langfuse (center)
        metric_separators = " | ".join(":---:" for _ in metric_names)
        run_table_separator = f"|:-----|{metric_separators}|:------:|:--------:|"

        run_table_rows = []
        for rd in request.run_details:
            metric_values = " | ".join(f"{rd.metrics.get(m, 0) * 100:.1f}%" for m in metric_names)
            latency_val = format_latency(rd.latency_ms)
            langfuse_link = f"[↗]({rd.langfuse_url})" if rd.langfuse_url else "—"
            run_table_rows.append(f"| {rd.run_id} | {metric_values} | {latency_val} | {langfuse_link} |")

        run_details_table = run_table_header + "\n" + run_table_separator + "\n" + "\n".join(run_table_rows)

        # Build aggregate metrics table (matching Models view indicators)
        K = request.k_runs
        aggregate_rows = []
        for mr in request.metric_results:
            pass_at_k_pct = mr.pass_at_k * 100
            pass_k_pct = mr.pass_k * 100
            max_at_k_pct = mr.max_at_k * 100
            consistency_pct = mr.consistency * 100
            reliability_pct = mr.reliability * 100
            avg_pct = mr.avg_score * 100
            threshold_pct = mr.threshold * 100

            aggregate_rows.append(
                f"| **{mr.metric_name.replace('_', ' ').title()}** | ≥{threshold_pct:.0f}% | "
                f"{pass_at_k_pct:.1f}% | {pass_k_pct:.1f}% | {max_at_k_pct:.1f}% | {consistency_pct:.1f}% | {reliability_pct:.1f}% | {avg_pct:.1f}% |"
            )

        aggregate_table = (
            f"| Metric | Threshold | Pass@{K} | Pass^{K} | Max@{K} | Consistency | Reliability | Avg Score |\n"
            "|:-------|:---------:|:------:|:------:|:-----:|:-----------:|:-----------:|:---------:|\n"
            + "\n".join(aggregate_rows)
        )

        # Create anchor-friendly ID for the run
        run_anchor = self._sanitize_name(request.run_name)

        run_section = f"""
---

## {request.run_name}

> **Published:** {published_at} | **Author:** @{request.published_by} | **Type:** Aggregate (K={request.k_runs} runs)

### Summary

{request.description}

### Individual Run Results

{run_details_table}

### Aggregate Metrics

{aggregate_table}

**Avg Latency:** {latency_str}

### Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | {request.model} |
| **Dataset** | {request.dataset} |
| **Task** | {request.task} |
| **Runs Evaluated** | {request.k_runs} |
| **Avg Items/Run** | {request.total_items_per_run:,} |

### Source Control

| | |
|:--|:--|
| **Branch** | `{request.branch or 'N/A'}` |
| **Commit** | `{request.commit or 'N/A'}` |
"""

        # Build content with TOC
        if not existing_content:
            header = f"""# {request.task_name}

**Project:** {request.project_name}

This page documents evaluation runs for the **{request.task_name}** task. Each run includes performance metrics, configuration details, and approval status.

## Evaluation History

"""
            toc_entry = f"| [{request.run_name}](#{run_anchor}) | {published_at} | @{request.published_by} | K={request.k_runs} |\n"
            toc_header = "| Run ID | Date | Author | Type |\n|:-------|:-----|:-------|:-----|\n"
            content = header + toc_header + toc_entry + run_section
        else:
            # Existing file - update history table and append run
            toc_marker = "## Evaluation History\n\n"
            old_toc_marker = "## Table of Contents\n\n"

            if toc_marker in existing_content:
                toc_start = existing_content.index(toc_marker)
                toc_content_start = toc_start + len(toc_marker)
                rest_of_content = existing_content[toc_content_start:]
                first_separator = rest_of_content.find("\n---")

                new_toc_entry = f"| [{request.run_name}](#{run_anchor}) | {published_at} | @{request.published_by} | K={request.k_runs} |\n"

                if first_separator != -1:
                    table_content = rest_of_content[:first_separator]
                    after_table = rest_of_content[first_separator:]

                    content = (existing_content[:toc_content_start] +
                              table_content + new_toc_entry +
                              after_table + run_section)
                else:
                    # No runs yet - table header exists but no separator
                    # Append entry to table and add run section
                    content = existing_content.rstrip() + "\n" + new_toc_entry + run_section
            elif old_toc_marker in existing_content:
                content = existing_content + run_section
            else:
                content = existing_content + run_section

        # Save task file
        with open(task_file, "w") as f:
            f.write(content)

        return PublishResult(
            success=True,
            page_id=task_file.stem,
            page_url=f"file://{task_file.absolute()}"
        )


class RealConfluenceClient(ConfluenceClient):
    """Real Confluence API client for production use.

    This is a placeholder for the actual Confluence REST API integration.
    It will use the Confluence REST API to interact with on-premise Confluence.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        api_token: str,
        space_key: str
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.api_token = api_token
        self.space_key = space_key
        # TODO: Initialize requests session with auth

    def list_projects(self) -> List[Project]:
        """List projects from Confluence API."""
        # TODO: Implement using Confluence REST API
        # GET /rest/api/content?type=page&spaceKey={space}&title=Projects
        raise NotImplementedError("Real Confluence API not yet implemented")

    def list_tasks(self, project_name: str) -> List[TaskPage]:
        """List task pages from Confluence API."""
        # TODO: Implement using Confluence REST API
        raise NotImplementedError("Real Confluence API not yet implemented")

    def search_users(self, query: str) -> List[User]:
        """Search users via Confluence API."""
        # TODO: Implement using Confluence REST API
        # GET /rest/api/user/search?query={query}
        raise NotImplementedError("Real Confluence API not yet implemented")

    def list_users(self) -> List[User]:
        """List users from Confluence."""
        # TODO: Implement using Confluence REST API
        raise NotImplementedError("Real Confluence API not yet implemented")

    def publish_run(self, request: PublishRequest) -> PublishResult:
        """Publish run to Confluence page."""
        # TODO: Implement using Confluence REST API
        # 1. Find or create page
        # 2. Get current page content
        # 3. Append new section using Confluence storage format
        # 4. PUT updated content
        raise NotImplementedError("Real Confluence API not yet implemented")

    def create_project(self, name: str, description: str, owner: str) -> Project:
        """Create project folder in Confluence."""
        # TODO: Implement using Confluence REST API
        raise NotImplementedError("Real Confluence API not yet implemented")

    def create_task(self, project_name: str, task_name: str) -> TaskPage:
        """Create task page in Confluence."""
        # TODO: Implement using Confluence REST API
        raise NotImplementedError("Real Confluence API not yet implemented")

    def publish_aggregate_run(self, request: AggregatePublishRequest) -> PublishResult:
        """Publish aggregate run to Confluence page."""
        # TODO: Implement using Confluence REST API
        raise NotImplementedError("Real Confluence API not yet implemented")
