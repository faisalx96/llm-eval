from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = REPO_ROOT / "packages" / "sdk"
PLATFORM_SRC = REPO_ROOT / "packages" / "platform"
DOCS_PORTAL_ROOT = REPO_ROOT / "docs_portal"
PORTAL_STATIC_ROOT = PLATFORM_SRC / "qym_platform" / "_static" / "docs"
CONTENT_ROOT = Path(__file__).with_name("content")


def _ensure_repo_imports() -> None:
    for path in (str(SDK_SRC), str(PLATFORM_SRC), str(REPO_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)


_ensure_repo_imports()

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "none")
os.environ.setdefault("QYM_LLM_CONFIG_ENCRYPTION_KEY", "dev-key")

from typer.main import get_command  # noqa: E402

from qym.cli._exit_codes import ExitCode  # noqa: E402
from qym.cli.app import app as qym_cli_app  # noqa: E402
from qym_platform.app import create_app  # noqa: E402
from qym_platform.settings import PlatformSettings  # noqa: E402


@dataclass
class Page:
    slug: str
    title: str
    section: str
    summary: str
    keywords: list[str]
    body_mdx: str


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _slugify(value: str) -> str:
    return (
        value.lower()
        .replace("/", "-")
        .replace("_", "-")
        .replace(" ", "-")
        .replace(".", "-")
        .replace(":", "-")
        .replace("{", "")
        .replace("}", "")
        .strip("-")
    )


def _frontmatter_escape(value: str) -> str:
    return value.replace('"', '\\"')


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br/>")


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(_md_cell(item) for item in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(_md_cell(item) for item in row) + " |" for row in rows)
    return "\n".join([header, separator, body])


def _bullets(items: list[str]) -> str:
    filtered = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"- {item}" for item in filtered)


def _numbered(items: list[str]) -> str:
    filtered = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(filtered, start=1))


def _code_block(text: str, language: str = "") -> str:
    fence = "```"
    if "```" in text:
        fence = "````"
    info = language if language else ""
    return f"{fence}{info}\n{text.rstrip()}\n{fence}"


def _admonition(kind: str, title: str, body: str) -> str:
    return f":::{kind} {title}\n{body.rstrip()}\n:::"


def _discover_openapi() -> dict[str, Any]:
    app = create_app()
    return app.openapi()


def _click_default_repr(param: Any) -> str:
    if param.default is None:
        return ""
    if isinstance(param.default, (list, tuple)):
        return ", ".join(str(v) for v in param.default)
    return str(param.default)


def _command_usage(parts: list[str]) -> str:
    return "qym" if not parts else "qym " + " ".join(parts)


def _command_params(command: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for param in getattr(command, "params", []):
        opts = getattr(param, "opts", None) or getattr(param, "secondary_opts", None) or []
        names = ", ".join(opts) if opts else (param.name or "")
        rows.append(
            {
                "name": names,
                "required": "yes" if getattr(param, "required", False) else "no",
                "default": _click_default_repr(param),
                "help": getattr(param, "help", "") or "",
            }
        )
    return rows


def _load_content_files() -> dict[str, Any]:
    names = [
        "commands",
        "config_groups",
        "examples",
        "api_groups",
        "workflows",
        "concepts",
        "troubleshooting",
    ]
    content: dict[str, Any] = {}
    for name in names:
        path = CONTENT_ROOT / f"{name}.json"
        content[name] = _load_json(path)
    return content


def _require_fields(item: dict[str, Any], required: list[str], label: str) -> None:
    missing = [field for field in required if field not in item]
    if missing:
        raise ValueError(f"Malformed docs content for {label}: missing {', '.join(missing)}")


def _validate_content(content: dict[str, Any]) -> None:
    for command, item in content["commands"].items():
        _require_fields(item, ["summary"], f"command {command}")
    for item in content["config_groups"]:
        _require_fields(item, ["title", "summary", "fields"], f"config group {item!r}")
    for example, item in content["examples"].items():
        _require_fields(item, ["title", "summary"], f"example {example}")
    for item in content["api_groups"]:
        _require_fields(item, ["id", "title", "summary", "prefixes", "auth"], f"api group {item!r}")
    for item in content["workflows"]:
        _require_fields(item, ["slug", "title", "summary", "steps"], f"workflow {item!r}")
    for item in content["concepts"]:
        _require_fields(item, ["slug", "title", "summary", "points"], f"concept {item!r}")
    for item in content["troubleshooting"]:
        _require_fields(item, ["slug", "title", "summary", "symptoms", "checks"], f"troubleshooting {item!r}")


def _clean_generated_docs(docs_root: Path) -> None:
    generated_roots = [
        docs_root / "cli" / "reference",
        docs_root / "api" / "reference",
        docs_root / "deploy-operate" / "reference",
        docs_root / "examples" / "catalog",
        docs_root / "overview" / "workflows",
        docs_root / "concepts" / "generated",
        docs_root / "troubleshooting" / "generated",
    ]
    for root in generated_roots:
        if root.exists():
            shutil.rmtree(root)


def _api_group_for_path(path: str, api_groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in api_groups:
        for prefix in item["prefixes"]:
            if path.startswith(prefix):
                matches.append((len(prefix), item))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _resolve_schema(schema: dict[str, Any] | None, components: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {}
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return _resolve_schema(components.get(ref, {}), components)
    for key in ("allOf", "oneOf", "anyOf"):
        if key in schema and schema[key]:
            return _resolve_schema(schema[key][0], components)
    return schema


def _sample_from_schema(schema: dict[str, Any] | None, components: dict[str, Any], depth: int = 0) -> Any:
    resolved = _resolve_schema(schema, components)
    if not resolved or depth > 3:
        return {}
    if "example" in resolved:
        return resolved["example"]
    if "default" in resolved:
        return resolved["default"]
    if resolved.get("enum"):
        return resolved["enum"][0]
    schema_type = resolved.get("type")
    if schema_type == "object" or "properties" in resolved:
        properties = resolved.get("properties", {})
        return {
            key: _sample_from_schema(value, components, depth + 1)
            for key, value in properties.items()
        }
    if schema_type == "array":
        return [_sample_from_schema(resolved.get("items", {}), components, depth + 1)]
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "boolean":
        return True
    if resolved.get("format") == "date-time":
        return "2026-01-01T00:00:00Z"
    if resolved.get("format") == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    if resolved.get("format") == "email":
        return "user@example.com"
    return "string"


def _schema_rows(schema: dict[str, Any] | None, components: dict[str, Any]) -> list[list[str]]:
    resolved = _resolve_schema(schema, components)
    properties = resolved.get("properties", {})
    required = set(resolved.get("required", []))
    rows: list[list[str]] = []
    for name, prop in properties.items():
        prop_schema = _resolve_schema(prop, components)
        prop_type = prop_schema.get("type") or ("object" if prop_schema.get("properties") else "value")
        description = prop_schema.get("description", "")
        rows.append(
            [
                f"`{name}`",
                prop_type,
                "yes" if name in required else "no",
                description,
            ]
        )
    return rows


def _path_parameters_table(operation: dict[str, Any]) -> str:
    parameters = operation.get("parameters", [])
    rows = []
    for parameter in parameters:
        schema = parameter.get("schema", {})
        rows.append(
            [
                f"`{parameter.get('name', '')}`",
                parameter.get("in", ""),
                "yes" if parameter.get("required") else "no",
                schema.get("type", ""),
                parameter.get("description", ""),
            ]
        )
    return _md_table(["Name", "In", "Required", "Type", "Description"], rows)


def _request_body_section(operation: dict[str, Any], components: dict[str, Any]) -> str:
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    media_type, payload = next(iter(content.items()), (None, None))
    if not media_type or not payload:
        return ""
    schema = payload.get("schema", {})
    rows = _schema_rows(schema, components)
    sample = _sample_from_schema(schema, components)
    sections = [f"Request media type: `{media_type}`"]
    if rows:
        sections.append(_md_table(["Field", "Type", "Required", "Description"], rows))
    if sample:
        sections.append(_code_block(json.dumps(sample, indent=2, ensure_ascii=False), "json"))
    return "\n\n".join(section for section in sections if section)


def _response_section(operation: dict[str, Any], components: dict[str, Any]) -> str:
    responses = operation.get("responses", {})
    status = next((code for code in ("200", "201", "202") if code in responses), None)
    if not status:
        return ""
    response = responses[status]
    content = response.get("content", {})
    media_type, payload = next(iter(content.items()), (None, None))
    sample = None
    rows: list[list[str]] = []
    if payload:
        schema = payload.get("schema", {})
        rows = _schema_rows(schema, components)
        sample = _sample_from_schema(schema, components)
    sections = [f"Success status: `{status}`"]
    if media_type:
        sections.append(f"Response media type: `{media_type}`")
    if rows:
        sections.append(_md_table(["Field", "Type", "Required", "Description"], rows))
    if sample:
        sections.append(_code_block(json.dumps(sample, indent=2, ensure_ascii=False), "json"))
    return "\n\n".join(section for section in sections if section)


def _error_rows(operation: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for status, response in sorted(operation.get("responses", {}).items()):
        if not str(status).startswith(("4", "5")):
            continue
        rows.append([str(status), response.get("description", "") or "No description"])
    return rows


def _request_example(method: str, path: str, operation: dict[str, Any], components: dict[str, Any], auth_note: str) -> str:
    lines = [f'curl -X {method.upper()} "$QYM_BASE_URL{path}"']
    if "public" not in auth_note.lower():
        lines.append('  -H "Authorization: Bearer $QYM_API_KEY"')
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    json_body = content.get("application/json")
    if json_body:
        sample = _sample_from_schema(json_body.get("schema", {}), components)
        lines.append('  -H "Content-Type: application/json"')
        lines.append(f"  -d '{json.dumps(sample, ensure_ascii=False)}'")
    return " \\\n".join(lines)


def _extract_docstring(path: Path) -> str:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return ""
    return ast.get_docstring(module) or ""


def _trim_paragraph(value: str) -> str:
    paragraphs = [part.strip() for part in value.split("\n\n") if part.strip()]
    return paragraphs[0] if paragraphs else value.strip()


def _write_docusaurus_docs(pages: list[Page], docs_root: Path) -> None:
    for page in pages:
        target = docs_root / f"{page.slug}.mdx"
        content = (
            "---\n"
            f'title: "{_frontmatter_escape(page.title)}"\n'
            f'description: "{_frontmatter_escape(page.summary)}"\n'
            "---\n\n"
            f"{page.body_mdx.rstrip()}\n"
        )
        _write_text(target, content)


def _build_portal_payload(pages: list[Page], openapi: dict[str, Any]) -> dict[str, Any]:
    sections: dict[str, list[dict[str, str]]] = {}
    for page in pages:
        sections.setdefault(page.section, []).append(
            {"title": page.title, "slug": page.slug, "summary": page.summary}
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": [{"title": key, "pages": value} for key, value in sections.items()],
        "pages": [
            {
                "slug": page.slug,
                "title": page.title,
                "section": page.section,
                "summary": page.summary,
                "keywords": page.keywords,
                "body_mdx": page.body_mdx,
            }
            for page in pages
        ],
        "openapi": {
            "version": openapi.get("openapi"),
            "title": openapi.get("info", {}).get("title"),
            "paths": len(openapi.get("paths", {})),
        },
    }


def _cli_reference_pages(command_overlays: dict[str, Any]) -> list[Page]:
    pages: list[Page] = []
    root = get_command(qym_cli_app)

    def walk(group: Any, parents: list[str] | None = None) -> None:
        local_parents = parents or []
        for name, command in getattr(group, "commands", {}).items():
            parts = local_parents + [name]
            key = " ".join(parts)
            overlay = command_overlays.get(key, {})
            summary = overlay.get("summary") or (getattr(command, "help", "") or "").strip() or f"Reference for `{_command_usage(parts)}`."

            sections = [f"`{_command_usage(parts)}`"]
            body = [
                summary,
                "",
                "## Usage",
                "",
                _code_block(_command_usage(parts), "bash"),
            ]

            when_to_use = overlay.get("when_to_use")
            if when_to_use:
                body.extend(["", "## When To Use It", "", when_to_use])

            examples = overlay.get("examples") or []
            if examples:
                body.extend(["", "## Examples", ""])
                for example in examples:
                    body.append(_code_block(example, "bash"))
                    body.append("")

            common_flags = overlay.get("common_flags") or []
            if common_flags:
                rows = [[f"`{item['flag']}`", item.get("purpose", ""), item.get("when", "")] for item in common_flags]
                body.extend(["", "## Common Flags", "", _md_table(["Flag", "Purpose", "Use It When"], rows)])

            failures = overlay.get("failure_modes") or overlay.get("pitfalls") or []
            if failures:
                body.extend(["", "## Common Failure Modes", "", _bullets(failures)])

            params = _command_params(command)
            if params:
                rows = [
                    [f"`{item['name']}`", item["required"], f"`{item['default']}`" if item["default"] else "", item["help"]]
                    for item in params
                ]
                body.extend(["", "## Option Reference", "", _md_table(["Option", "Required", "Default", "Description"], rows)])

            subcommands = getattr(command, "commands", None) or {}
            if subcommands:
                rows = []
                for sub_name, sub_command in subcommands.items():
                    sub_key = " ".join(parts + [sub_name])
                    sub_overlay = command_overlays.get(sub_key, {})
                    sub_summary = sub_overlay.get("summary") or (getattr(sub_command, "help", "") or "").strip()
                    link = f"[`qym {' '.join(parts + [sub_name])}`](./{sub_name})"
                    rows.append([link, sub_summary])
                body.extend(["", "## Subcommands", "", _md_table(["Command", "Summary"], rows)])

            exit_codes = overlay.get("exit_codes") or []
            if exit_codes:
                body.extend(["", "## Exit Codes", "", _md_table(["Code", "Meaning"], exit_codes)])

            next_steps = overlay.get("next_steps") or []
            if next_steps:
                body.extend(["", _admonition("tip", "Recommended Next Step", _bullets(next_steps))])

            pages.append(
                Page(
                    slug="cli/reference/" + "/".join(parts),
                    title=" ".join(part.capitalize() for part in parts),
                    section="CLI Reference",
                    summary=summary,
                    keywords=["cli", *parts],
                    body_mdx="\n".join(line for line in body if line is not None),
                )
            )
            if subcommands:
                walk(command, parts)

    index_rows = []
    for name, command in root.commands.items():
        overlay = command_overlays.get(name, {})
        summary = overlay.get("summary") or (getattr(command, "help", "") or "").strip()
        index_rows.append([f"[`qym {name}`](./{name})", summary])
    pages.append(
        Page(
            slug="cli/reference/index",
            title="CLI Reference",
            section="CLI Reference",
            summary="Generated command and flag reference for the qym CLI.",
            keywords=["cli", "reference"],
            body_mdx="\n".join(
                [
                    "Use this section for the authoritative command tree, flags, exit behavior, and examples that are generated from the Typer application.",
                    "",
                    _admonition(
                        "info",
                        "Task-Oriented CLI Guides",
                        "Start with [/cli](/cli) if you want recommended workflows for running evaluations, inspecting runs, and wiring automation.",
                    ),
                    "",
                    "## Command Groups",
                    "",
                    _md_table(["Command", "Summary"], index_rows),
                    "",
                    "## Standard Exit Codes",
                    "",
                    _md_table(
                        ["Code", "Meaning"],
                        [[str(int(code.value)), code.name.lower().replace("_", " ")] for code in ExitCode],
                    ),
                ]
            ),
        )
    )
    walk(root)
    return pages


def _platform_config_pages(config_groups: list[dict[str, Any]], sdk_manifest: dict[str, Any]) -> list[Page]:
    fields = PlatformSettings.model_fields
    pages: list[Page] = []

    for group in config_groups:
        rows = []
        for field_name in group["fields"]:
            field = fields.get(field_name)
            if field is None:
                continue
            env_name = "QYM_" + field_name.upper()
            type_name = getattr(field.annotation, "__name__", str(field.annotation))
            default = "required" if field.is_required() else str(field.default)
            rows.append([f"`{env_name}`", type_name, default, field.description or ""])
        body = "\n".join(
            [
                group["summary"],
                "",
                "## Variables",
                "",
                _md_table(["Env Var", "Type", "Default", "Description"], rows),
            ]
        )
        pages.append(
            Page(
                slug="deploy-operate/reference/" + _slugify(group["title"]),
                title=group["title"],
                section="Config Reference",
                summary=group["summary"],
                keywords=["config", *group["fields"]],
                body_mdx=body,
            )
        )

    sdk_rows = []
    for item in sdk_manifest["variables"]:
        aliases = ", ".join(f"`{alias}`" for alias in item.get("aliases", []))
        sdk_rows.append(
            [
                f"`{item['name']}`",
                item.get("category", ""),
                "yes" if item.get("required") else "no",
                item.get("description", ""),
                aliases,
                f"`{item['example']}`" if item.get("example") else "",
            ]
        )
    pages.append(
        Page(
            slug="deploy-operate/reference/sdk-environment",
            title="SDK Environment Variables",
            section="Config Reference",
            summary="Environment variables used by the qym SDK and CLI.",
            keywords=["sdk", "env", "config"],
            body_mdx="\n".join(
                [
                    "This reference is generated from the checked-in SDK environment manifest so CLI and SDK configuration guidance stays aligned with the package.",
                    "",
                    "## Variables",
                    "",
                    _md_table(["Env Var", "Category", "Required", "Description", "Aliases", "Example"], sdk_rows),
                ]
            ),
        )
    )

    overview_rows = [
        [f"[{group['title']}](./{_slugify(group['title'])})", group["summary"]]
        for group in config_groups
    ]
    overview_rows.append(["[SDK environment](./sdk-environment)", "SDK and CLI environment variables."])
    pages.append(
        Page(
            slug="deploy-operate/reference/index",
            title="Environment Reference",
            section="Config Reference",
            summary="Generated environment and runtime reference for the qym platform, SDK, and CLI.",
            keywords=["config", "environment", "reference"],
            body_mdx="\n".join(
                [
                    "Use this section for the exact environment variables and defaults derived from the platform settings model and SDK metadata manifest.",
                    "",
                    _md_table(["Reference Page", "Summary"], overview_rows),
                ]
            ),
        )
    )
    return pages


def _api_reference_pages(openapi: dict[str, Any], api_groups: list[dict[str, Any]]) -> list[Page]:
    components = openapi.get("components", {}).get("schemas", {})
    grouped_operations: dict[str, list[tuple[str, str, dict[str, Any]]]] = {item["id"]: [] for item in api_groups}

    for path, methods in sorted(openapi.get("paths", {}).items()):
        if not (path.startswith("/v1/") or path.startswith("/api/") or path == "/healthz"):
            continue
        group = _api_group_for_path(path, api_groups)
        if group is None:
            continue
        for method, operation in sorted(methods.items()):
            if not isinstance(operation, dict):
                continue
            grouped_operations[group["id"]].append((path, method, operation))

    pages: list[Page] = []
    group_rows = []

    for group in api_groups:
        operations = grouped_operations.get(group["id"], [])
        endpoint_rows = []
        for path, method, operation in operations:
            summary = operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}"
            endpoint_slug = _slugify(f"{method}-{path}")
            endpoint_rows.append(
                [
                    f"`{method.upper()}`",
                    f"[`{path}`](./{endpoint_slug})",
                    summary,
                ]
            )

            body = [
                summary,
                "",
                "## Endpoint",
                "",
                f"- Method: `{method.upper()}`",
                f"- Path: `{path}`",
                f"- Auth: {group['auth']}",
                '- OpenAPI: <a href="/openapi.json">/openapi.json</a>',
                '- Interactive explorer: <a href="/api-docs">/api-docs</a>',
            ]

            if group.get("purpose"):
                body.extend(["", "## Purpose", "", group["purpose"]])

            parameter_table = _path_parameters_table(operation)
            if parameter_table:
                body.extend(["", "## Parameters", "", parameter_table])

            request_body = _request_body_section(operation, components)
            if request_body:
                body.extend(["", "## Request Body", "", request_body])

            body.extend(
                [
                    "",
                    "## Request Example",
                    "",
                    _code_block(_request_example(method, path, operation, components, group["auth"]), "bash"),
                ]
            )

            response_section = _response_section(operation, components)
            if response_section:
                body.extend(["", "## Response", "", response_section])

            errors = _error_rows(operation)
            if errors:
                body.extend(["", "## Error Responses", "", _md_table(["Status", "Meaning"], errors)])

            pages.append(
                Page(
                    slug=f"api/reference/{group['id']}/{endpoint_slug}",
                    title=f"{method.upper()} {path}",
                    section="API Reference",
                    summary=summary,
                    keywords=["api", group["id"], method, path],
                    body_mdx="\n".join(body),
                )
            )

        group_rows.append([f"[{group['title']}](./{group['id']})", group["summary"], str(len(operations))])
        group_body = [group["summary"], "", "## Auth Expectations", "", group["auth"]]
        overview_points = group.get("overview_points") or []
        if overview_points:
            group_body.extend(["", "## What Lives Here", "", _bullets(overview_points)])
        group_body.extend(["", "## Endpoints", "", _md_table(["Method", "Path", "Summary"], endpoint_rows)])
        pages.append(
            Page(
                slug=f"api/reference/{group['id']}",
                title=group["title"],
                section="API Reference",
                summary=group["summary"],
                keywords=["api", group["id"]],
                body_mdx="\n".join(group_body),
            )
        )

    pages.append(
        Page(
            slug="api/reference/index",
            title="API Reference",
            section="API Reference",
            summary="Generated API reference grouped into stable sections for auth, runs, projects, analysis, admin, and ingestion.",
            keywords=["api", "reference"],
            body_mdx="\n".join(
                [
                    "The platform API reference is generated from the FastAPI OpenAPI document and grouped into stable sections so it stays usable as the surface expands.",
                    "",
                    "## Groups",
                    "",
                    _md_table(["Group", "Summary", "Endpoints"], group_rows),
                    "",
                    _admonition(
                        "tip",
                        "Learning Before Reference",
                        "Start with [/api](/api) for auth flow, pagination, scoping, and common workflows. Use this reference when you need an exact path or request shape.",
                    ),
                ]
            ),
        )
    )
    return pages


def _example_catalog_pages(example_overlays: dict[str, Any]) -> list[Page]:
    examples_root = REPO_ROOT / "examples"
    pages: list[Page] = []
    rows = []

    for path in sorted(examples_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(examples_root).as_posix()
        overlay = example_overlays.get(rel) or example_overlays.get(path.name, {})
        docstring = _extract_docstring(path)
        summary = overlay.get("summary") or _trim_paragraph(docstring) or "Runnable qym example from the repository."
        title = overlay.get("title") or rel
        slug = _slugify(rel.removesuffix(".py"))
        tags = overlay.get("tags") or []
        source = path.read_text(encoding="utf-8")
        snippet = "\n".join(source.splitlines()[:80])

        body = [summary]
        prerequisites = overlay.get("prerequisites") or []
        if prerequisites:
            body.extend(["", "## Prerequisites", "", _bullets(prerequisites)])

        what_it_shows = overlay.get("what_it_shows") or []
        if what_it_shows:
            body.extend(["", "## What It Demonstrates", "", _bullets(what_it_shows)])

        if overlay.get("run"):
            body.extend(["", "## Run It", "", _code_block(overlay["run"], "bash")])

        if overlay.get("expected_outcome"):
            body.extend(["", "## Expected Outcome", "", overlay["expected_outcome"]])

        if tags:
            body.extend(["", "## Tags", "", " ".join(f"`{tag}`" for tag in tags)])

        body.extend(
            [
                "",
                "## Source",
                "",
                f"- Repository file: `examples/{rel}`",
                "",
                _code_block(snippet, "python"),
            ]
        )

        related_docs = overlay.get("related_docs") or []
        if related_docs:
            body.extend(["", _admonition("tip", "Related Docs", _bullets(related_docs))])

        pages.append(
            Page(
                slug=f"examples/catalog/{slug}",
                title=title,
                section="Examples Catalog",
                summary=summary,
                keywords=["examples", rel, *tags],
                body_mdx="\n".join(body),
            )
        )
        rows.append([f"[{title}](./{slug})", summary, ", ".join(tags)])

    pages.append(
        Page(
            slug="examples/catalog/index",
            title="Full Example Catalog",
            section="Examples Catalog",
            summary="Generated inventory of every runnable example found in the repository.",
            keywords=["examples", "catalog"],
            body_mdx="\n".join(
                [
                    "This catalog is generated from the `examples/` tree so new examples automatically appear in the portal. Start with [/examples](/examples) if you want the curated canonical set.",
                    "",
                    _md_table(["Example", "Summary", "Tags"], rows),
                ]
            ),
        )
    )
    return pages


def _workflow_pages(workflows: list[dict[str, Any]]) -> list[Page]:
    pages: list[Page] = []
    rows = []
    for item in workflows:
        body = [item["summary"]]
        if item.get("paragraphs"):
            body.extend(["", "## Overview", "", "\n\n".join(item["paragraphs"])])
        if item.get("steps"):
            body.extend(["", "## Recommended Sequence", "", _numbered(item["steps"])])
        if item.get("common_mistakes"):
            body.extend(["", _admonition("warning", "Common Mistakes", _bullets(item["common_mistakes"]))])
        if item.get("next_steps"):
            body.extend(["", _admonition("tip", "Next Steps", _bullets(item["next_steps"]))])

        pages.append(
            Page(
                slug=f"overview/workflows/{item['slug']}",
                title=item["title"],
                section="Overview",
                summary=item["summary"],
                keywords=["workflow", item["slug"]],
                body_mdx="\n".join(body),
            )
        )
        rows.append([f"[{item['title']}](./{item['slug']})", item["summary"]])

    pages.append(
        Page(
            slug="overview/workflows/index",
            title="Workflow Guides",
            section="Overview",
            summary="Generated workflow guides backed by structured editorial content.",
            keywords=["workflow", "guides"],
            body_mdx="\n".join(["Use these guides when you want recommended operating sequences instead of raw reference pages.", "", _md_table(["Guide", "Summary"], rows)]),
        )
    )
    return pages


def _concept_pages(items: list[dict[str, Any]]) -> list[Page]:
    pages: list[Page] = []
    rows = []
    for item in items:
        body = [item["summary"], "", "## Key Points", "", _bullets(item["points"])]
        if item.get("related_docs"):
            body.extend(["", _admonition("tip", "Related Docs", _bullets(item["related_docs"]))])
        pages.append(
            Page(
                slug=f"concepts/generated/{item['slug']}",
                title=item["title"],
                section="Concepts",
                summary=item["summary"],
                keywords=["concept", item["slug"]],
                body_mdx="\n".join(body),
            )
        )
        rows.append([f"[{item['title']}](./{item['slug']})", item["summary"]])

    pages.append(
        Page(
            slug="concepts/generated/index",
            title="Concept Reference",
            section="Concepts",
            summary="Generated concept pages backed by curated editorial points.",
            keywords=["concepts"],
            body_mdx="\n".join(["Use these pages to align on the qym mental model before going deep into SDK, CLI, or platform operations.", "", _md_table(["Concept", "Summary"], rows)]),
        )
    )
    return pages


def _troubleshooting_pages(items: list[dict[str, Any]]) -> list[Page]:
    pages: list[Page] = []
    rows = []
    for item in items:
        body = [
            item["summary"],
            "",
            "## Symptoms",
            "",
            _bullets(item["symptoms"]),
            "",
            "## Checks",
            "",
            _numbered(item["checks"]),
        ]
        if item.get("fixes"):
            body.extend(["", "## Fixes", "", _bullets(item["fixes"])])
        if item.get("related_docs"):
            body.extend(["", _admonition("tip", "Related Docs", _bullets(item["related_docs"]))])
        pages.append(
            Page(
                slug=f"troubleshooting/generated/{item['slug']}",
                title=item["title"],
                section="Troubleshooting",
                summary=item["summary"],
                keywords=["troubleshooting", item["slug"]],
                body_mdx="\n".join(body),
            )
        )
        rows.append([f"[{item['title']}](./{item['slug']})", item["summary"]])

    pages.append(
        Page(
            slug="troubleshooting/generated/index",
            title="Troubleshooting Reference",
            section="Troubleshooting",
            summary="Generated troubleshooting guides backed by structured editorial checks.",
            keywords=["troubleshooting"],
            body_mdx="\n".join(["Start with the symptom that matches what you see in the SDK, CLI, platform, or deployment environment.", "", _md_table(["Issue", "Summary"], rows)]),
        )
    )
    return pages


def generate(
    docs_portal_root: Path = DOCS_PORTAL_ROOT,
    portal_static_root: Path = PORTAL_STATIC_ROOT,
) -> dict[str, Any]:
    content = _load_content_files()
    _validate_content(content)
    sdk_manifest = _load_json(Path(__file__).with_name("sdk_env_manifest.json"))
    openapi = _discover_openapi()

    docs_root = docs_portal_root / "docs"
    _clean_generated_docs(docs_root)

    pages: list[Page] = []
    pages.extend(_cli_reference_pages(content["commands"]))
    pages.extend(_platform_config_pages(content["config_groups"], sdk_manifest))
    pages.extend(_api_reference_pages(openapi, content["api_groups"]))
    pages.extend(_example_catalog_pages(content["examples"]))
    pages.extend(_workflow_pages(content["workflows"]))
    pages.extend(_concept_pages(content["concepts"]))
    pages.extend(_troubleshooting_pages(content["troubleshooting"]))

    _write_docusaurus_docs(pages, docs_root)
    _write_json(docs_portal_root / "static" / "openapi.json", openapi)
    _write_json(portal_static_root / "openapi.json", openapi)
    payload = _build_portal_payload(pages, openapi)
    _write_json(portal_static_root / "portal-data.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate qym developer portal source and payload files.")
    _ = parser.parse_args()
    generate()


if __name__ == "__main__":
    main()
