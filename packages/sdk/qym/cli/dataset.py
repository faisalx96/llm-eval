"""qym dataset commands."""

from __future__ import annotations

import json
import os
from typing import Optional
from urllib import parse, request

import typer

from ._exit_codes import ExitCode
from ._output import is_json_mode, output, output_error, err_console
from ..platform.client import PlatformClient
from ..utils.env import get_platform_url_env


dataset_app = typer.Typer(help="Manage qym platform datasets.")
version_app = typer.Typer(help="Manage dataset versions.")
alias_app = typer.Typer(help="Manage dataset aliases.")
item_app = typer.Typer(help="Manage dataset items.")
dataset_app.add_typer(version_app, name="version")
dataset_app.add_typer(alias_app, name="alias")
dataset_app.add_typer(item_app, name="item")


def _client(api_key: Optional[str] = None, platform_url: Optional[str] = None) -> PlatformClient:
    key = api_key or os.getenv("QYM_API_KEY")
    if not key:
        output_error("auth_denied", "Missing API key. Provide --api-key or set QYM_API_KEY.")
        raise typer.Exit(code=ExitCode.AUTH_DENIED)
    return PlatformClient(platform_url=platform_url or get_platform_url_env(), api_key=key)


def _get(client: PlatformClient, path: str) -> dict:
    req = request.Request(f"{client.platform_url.rstrip('/')}{path}", headers={"Authorization": f"Bearer {client.api_key}"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except Exception as exc:
        output_error("failure", str(exc))
        raise typer.Exit(code=ExitCode.FAILURE)


def _post(client: PlatformClient, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{client.platform_url.rstrip('/')}{path}",
        data=data,
        headers={"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except Exception as exc:
        output_error("failure", str(exc))
        raise typer.Exit(code=ExitCode.FAILURE)


def _emit(data: dict) -> None:
    if is_json_mode():
        output(data)
    else:
        err_console.print(json.dumps(data, indent=2, ensure_ascii=False))


@dataset_app.command("list")
def list_datasets(
    project_slug: Optional[str] = typer.Option(None, "--project"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    platform_url: Optional[str] = typer.Option(None, "--platform-url"),
) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_get(client, f"/v1/datasets{qs}"))


@dataset_app.command("get")
def get_dataset(
    dataset: str,
    project_slug: Optional[str] = typer.Option(None, "--project"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    platform_url: Optional[str] = typer.Option(None, "--platform-url"),
) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_get(client, f"/v1/datasets/{parse.quote(dataset, safe='')}{qs}"))


@dataset_app.command("upload")
def upload_dataset(
    name: str = typer.Option(..., "--name"),
    file: str = typer.Option(..., "--file"),
    version: str = typer.Option("v1", "--version"),
    publish: bool = typer.Option(False, "--publish"),
    production: bool = typer.Option(False, "--production"),
    input_col: str = typer.Option("input", "--input-col"),
    expected_col: str = typer.Option("expected_output", "--expected-col"),
    id_col: Optional[str] = typer.Option(None, "--id-col"),
    metadata_cols: Optional[str] = typer.Option(None, "--metadata-cols"),
    labels: Optional[str] = typer.Option(None, "--labels"),
    project_slug: Optional[str] = typer.Option(None, "--project"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    platform_url: Optional[str] = typer.Option(None, "--platform-url"),
) -> None:
    client = _client(api_key, platform_url)
    data = client.upload_dataset(
        path=file,
        name=name,
        version=version,
        publish=publish,
        set_alias="production" if production else None,
        input_col=input_col,
        expected_col=expected_col,
        id_col=id_col,
        metadata_cols=metadata_cols,
        labels=labels,
        project_slug=project_slug,
    )
    _emit(data)


@dataset_app.command("download")
def download_dataset(
    dataset: str,
    output_file: str = typer.Option(..., "--output"),
    version: str = typer.Option("production", "--version"),
    project_slug: Optional[str] = typer.Option(None, "--project"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    platform_url: Optional[str] = typer.Option(None, "--platform-url"),
) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    url = f"{client.platform_url.rstrip('/')}/v1/datasets/{parse.quote(dataset, safe='')}/versions/{parse.quote(version, safe='')}:download{qs}"
    req = request.Request(url, headers={"Authorization": f"Bearer {client.api_key}"})
    with request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    with open(output_file, "wb") as f:
        f.write(raw)
    _emit({"output": output_file})


@version_app.command("list")
def version_list(dataset: str, project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_get(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions{qs}"))


@version_app.command("create")
def version_create(dataset: str, version: Optional[str] = typer.Option(None, "--version"), from_ref: str = typer.Option("production", "--from"), project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    payload = {"from_alias": from_ref}
    if version:
        payload["version"] = version
    _emit(_post(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions{qs}", payload))


@version_app.command("publish")
def version_publish(dataset: str, version: str, production: bool = typer.Option(False, "--production"), project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_post(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions/{parse.quote(version, safe='')}:publish{qs}", {"set_alias": "production" if production else None}))


@version_app.command("compare")
def version_compare(dataset: str, version: str, base: str = typer.Option(..., "--base"), project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    params = {"base": base}
    if project_slug:
        params["project_slug"] = project_slug
    _emit(_get(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions/{parse.quote(version, safe='')}:compare?" + parse.urlencode(params)))


@alias_app.command("set")
def alias_set(dataset: str, alias: str, version: str, project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_post(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/aliases/{parse.quote(alias, safe='')}{qs}", {"version": version}))


@item_app.command("list")
def item_list(dataset: str, version: str = typer.Option("production", "--version"), limit: int = typer.Option(100, "--limit"), project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    params = {"limit": str(limit)}
    if project_slug:
        params["project_slug"] = project_slug
    _emit(_get(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions/{parse.quote(version, safe='')}/items?" + parse.urlencode(params)))


@item_app.command("runs")
def item_runs(dataset: str, item_id: str, version: str = typer.Option("production", "--version"), project_slug: Optional[str] = typer.Option(None, "--project"), api_key: Optional[str] = typer.Option(None, "--api-key"), platform_url: Optional[str] = typer.Option(None, "--platform-url")) -> None:
    client = _client(api_key, platform_url)
    qs = "?" + parse.urlencode({"project_slug": project_slug}) if project_slug else ""
    _emit(_get(client, f"/v1/datasets/{parse.quote(dataset, safe='')}/versions/{parse.quote(version, safe='')}/items/{parse.quote(item_id, safe='')}/runs{qs}"))
