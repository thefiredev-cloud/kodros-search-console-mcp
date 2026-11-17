"""Google Search Console property tools and read-only Cloud Resource Manager MCP.

Local settings:
- GOOGLE_API_MCP_TOKEN_FILE: OAuth token JSON path; defaults to
  ~/.config/google-api-mcp/token.json.
- GOOGLE_API_MCP_CLIENT_FILE: Desktop OAuth client JSON path used by
  authorize.py; defaults to ~/.config/google-api-mcp/client_secret.json.

The server exposes Search Console reads and explicit site-property add/remove
tools, plus read-only Cloud Resource Manager project search and lookup. It
does not write to Google Cloud. Confirm each exact Search Console property
change with the user before calling a write tool.
Google's Resource Manager v3 requires the broad cloud-platform.read-only
scope; this server only calls project search/get.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

API_SCOPES = (
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/cloud-platform.read-only",
)
# Google returns "email" as its canonical userinfo.email name; requesting the
# canonical name keeps oauthlib's requested-vs-granted scope check equal.
OAUTH_SCOPES = (
    *API_SCOPES,
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)
CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
).expanduser() / "google-api-mcp"
TOKEN_FILE = Path(
    os.environ.get("GOOGLE_API_MCP_TOKEN_FILE", str(CONFIG_DIR / "token.json"))
).expanduser()
CLIENT_FILE = Path(
    os.environ.get("GOOGLE_API_MCP_CLIENT_FILE", str(CONFIG_DIR / "client_secret.json"))
).expanduser()

SEARCH_DIMENSIONS = frozenset(
    {"country", "date", "device", "page", "query", "searchAppearance"}
)
SEARCH_TYPES = Literal["web", "image", "video", "news", "googleNews", "discover"]

mcp = FastMCP(
    "Google Search Console and Cloud",
    instructions=(
        "Search Console reads and site-property add/delete plus read-only Cloud "
        "Resource Manager tools. Get direct user confirmation for the exact "
        "property before adding or deleting. Use list_search_console_sites to "
        "find Search Console properties first."
    ),
)


def save_credentials(credentials: Credentials) -> None:
    """Atomically save OAuth credentials with owner-only file permissions."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(TOKEN_FILE.parent, 0o700)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{TOKEN_FILE.name}.", dir=TOKEN_FILE.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as token_file:
            os.fchmod(token_file.fileno(), 0o600)
            token_file.write(credentials.to_json())
            token_file.flush()
            os.fsync(token_file.fileno())
        os.replace(temporary_name, TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _credentials() -> Credentials:
    if not TOKEN_FILE.is_file():
        raise RuntimeError(
            "Google OAuth is not configured. Run `uv run python authorize.py "
            "--client-secret <Desktop OAuth JSON>` after creating a Desktop OAuth client."
        )
    try:
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), scopes=list(OAUTH_SCOPES)
        )
    except (OSError, ValueError):
        raise RuntimeError(
            "Google OAuth token file is unreadable. Reauthorize with authorize.py."
        ) from None

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise RuntimeError(
                "Google OAuth refresh failed. Reauthorize with authorize.py."
            ) from None
        save_credentials(credentials)
    # Google can return access tokens with a lifetime shorter than google-auth's
    # clock-skew margin, so valid is False right after a successful refresh.
    if not credentials.token:
        raise RuntimeError(
            "Google OAuth credentials are invalid. Reauthorize with authorize.py."
        )
    return credentials


def _service(api_name: str, version: str) -> Any:
    return build(
        api_name,
        version,
        credentials=_credentials(),
        cache_discovery=False,
    )


def _execute(request: Any, api_label: str) -> dict[str, Any]:
    try:
        return request.execute(num_retries=0) or {}
    except HttpError as error:
        status = getattr(error.resp, "status", "unknown")
        if status == 401:
            detail = "Reauthorize the Google account and retry."
        elif status == 403:
            detail = (
                "Confirm the API is enabled in the OAuth client project and the "
                "authorized account has access to this property or project."
            )
        elif status == 404:
            detail = "Check the supplied property or project identifier."
        else:
            detail = "Check the request values and retry."
        raise RuntimeError(f"{api_label} request failed with HTTP {status}. {detail}") from None


def _validate_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
    return parsed


def _project_fields(project: dict[str, Any]) -> dict[str, Any]:
    return {
        key: project[key]
        for key in (
            "name",
            "projectId",
            "displayName",
            "state",
            "parent",
            "createTime",
            "updateTime",
        )
        if key in project
    }


@mcp.tool
def list_search_console_sites() -> dict[str, Any]:
    """List Search Console properties available to the authorized Google account."""
    response = _execute(
        _service("searchconsole", "v1").sites().list(), "Search Console"
    )
    sites = [
        {
            "site_url": entry.get("siteUrl"),
            "permission_level": entry.get("permissionLevel"),
        }
        for entry in response.get("siteEntry", [])
    ]
    sites.sort(key=lambda site: site["site_url"] or "")
    return {"sites": sites}


def _confirmed_site_url(site_url: str, confirm_site_url: str) -> str:
    value = site_url.strip()
    if not value:
        raise ValueError("site_url is required.")
    if confirm_site_url.strip() != value:
        raise ValueError(
            "confirm_site_url must exactly match site_url after user confirmation."
        )
    return value


@mcp.tool
def add_search_console_site(
    site_url: str,
    confirm_site_url: str,
) -> dict[str, str]:
    """Add a property after direct user confirmation of its exact URL."""
    value = _confirmed_site_url(site_url, confirm_site_url)
    _execute(
        _service("searchconsole", "v1").sites().add(siteUrl=value),
        "Search Console",
    )
    return {"status": "added_to_account", "site_url": value}


@mcp.tool
def delete_search_console_site(
    site_url: str,
    confirm_site_url: str,
) -> dict[str, str]:
    """Remove a property from the account, not the website, after user confirmation."""
    value = _confirmed_site_url(site_url, confirm_site_url)
    _execute(
        _service("searchconsole", "v1").sites().delete(siteUrl=value),
        "Search Console",
    )
    return {"status": "removed_from_account", "site_url": value}


@mcp.tool

def query_search_analytics(
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: list[str] | None = None,
    search_type: SEARCH_TYPES = "web",
    row_limit: int = 1000,
    start_row: int = 0,
) -> dict[str, Any]:
    """Query Search Console clicks, impressions, CTR, and position by dimension."""
    if not site_url.strip():
        raise ValueError("site_url is required; use a property URL from list_search_console_sites.")
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date.")
    if not 1 <= row_limit <= 25_000:
        raise ValueError("row_limit must be between 1 and 25000.")
    if start_row < 0:
        raise ValueError("start_row must be zero or greater.")

    requested_dimensions = dimensions or []
    unsupported = sorted(set(requested_dimensions) - SEARCH_DIMENSIONS)
    if unsupported:
        raise ValueError(
            "Unsupported Search Console dimensions: " + ", ".join(unsupported)
        )
    if len(set(requested_dimensions)) != len(requested_dimensions):
        raise ValueError("dimensions must not contain duplicates.")

    body: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "type": search_type,
        "rowLimit": row_limit,
        "startRow": start_row,
    }
    if requested_dimensions:
        body["dimensions"] = requested_dimensions

    response = _execute(
        _service("searchconsole", "v1")
        .searchanalytics()
        .query(siteUrl=site_url.strip(), body=body),
        "Search Console",
    )
    rows = response.get("rows", [])
    return {
        "site_url": site_url.strip(),
        "start_date": start_date,
        "end_date": end_date,
        "row_count": len(rows),
        "rows": rows,
    }


@mcp.tool

def list_search_console_sitemaps(site_url: str) -> dict[str, Any]:
    """List submitted sitemaps and processing status for a Search Console property."""
    if not site_url.strip():
        raise ValueError("site_url is required; use a property URL from list_search_console_sites.")
    response = _execute(
        _service("searchconsole", "v1").sitemaps().list(siteUrl=site_url.strip()),
        "Search Console",
    )
    return {
        "site_url": site_url.strip(),
        "sitemaps": response.get("sitemap", []),
    }


@mcp.tool

def search_cloud_projects(
    query: str = "",
    page_size: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Search Google Cloud projects visible to the authorized account.

    Uses Cloud Resource Manager v3. Pass an optional Resource Manager query and
    the returned next_page_token to page through results. An empty query omits
    the filter and searches projects available to the caller.
    """
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100.")
    request_args: dict[str, Any] = {"pageSize": page_size}
    if query.strip():
        request_args["query"] = query.strip()
    if page_token:
        request_args["pageToken"] = page_token

    response = _execute(
        _service("cloudresourcemanager", "v3")
        .projects()
        .search(**request_args),
        "Cloud Resource Manager",
    )
    return {
        "projects": [
            _project_fields(project) for project in response.get("projects", [])
        ],
        "next_page_token": response.get("nextPageToken"),
    }


@mcp.tool

def get_cloud_project(project_name: str) -> dict[str, Any]:
    """Get Cloud Resource Manager metadata for a project resource name or ID.

    Use the `name` value returned by search_cloud_projects when available.
    """
    value = project_name.strip()
    if not value:
        raise ValueError("project_name is required.")
    resource_name = value if value.startswith("projects/") else f"projects/{value}"
    if resource_name.count("/") != 1:
        raise ValueError("Use a project ID, project number, or projects/{id} resource name.")

    project = _execute(
        _service("cloudresourcemanager", "v3").projects().get(name=resource_name),
        "Cloud Resource Manager",
    )
    return _project_fields(project)


def _require_property(site_url: str) -> str:
    value = site_url.strip()
    if not value:
        raise ValueError("site_url is required; use a property URL from list_search_console_sites.")
    return value


def _sitemap_url(site_url: str, feedpath: str) -> str:
    value = feedpath.strip()
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("feedpath must be a full http(s) sitemap URL.")
    if site_url.startswith("sc-domain:"):
        host = site_url[len("sc-domain:"):].lower()
        target = value.split("/", 3)[2].split(":")[0].lower()
        if target != host and not target.endswith("." + host):
            raise ValueError("feedpath host must belong to the sc-domain property.")
    elif not value.startswith(site_url):
        raise ValueError("feedpath must live under the url-prefix property.")
    return value


@mcp.tool
def get_search_console_sitemap(site_url: str, feedpath: str) -> dict[str, Any]:
    """Get processing status, errors, warnings and indexed counts for one submitted sitemap."""
    site = _require_property(site_url)
    return _execute(
        _service("searchconsole", "v1").sitemaps().get(siteUrl=site, feedpath=_sitemap_url(site, feedpath)),
        "Search Console",
    )


@mcp.tool
def submit_search_console_sitemap(
    site_url: str,
    feedpath: str,
    confirm_feedpath: str,
) -> dict[str, str]:
    """Submit or resubmit a sitemap after the user confirms the exact sitemap URL."""
    site = _require_property(site_url)
    value = _sitemap_url(site, feedpath)
    if confirm_feedpath.strip() != value:
        raise ValueError("confirm_feedpath must exactly match feedpath after user confirmation.")
    _execute(
        _service("searchconsole", "v1").sitemaps().submit(siteUrl=site, feedpath=value),
        "Search Console",
    )
    return {"status": "submitted", "site_url": site, "feedpath": value}


@mcp.tool
def delete_search_console_sitemap(
    site_url: str,
    feedpath: str,
    confirm_feedpath: str,
) -> dict[str, str]:
    """Remove a sitemap from Search Console, not from the website, after user confirmation."""
    site = _require_property(site_url)
    value = _sitemap_url(site, feedpath)
    if confirm_feedpath.strip() != value:
        raise ValueError("confirm_feedpath must exactly match feedpath after user confirmation.")
    _execute(
        _service("searchconsole", "v1").sitemaps().delete(siteUrl=site, feedpath=value),
        "Search Console",
    )
    return {"status": "removed_from_search_console", "site_url": site, "feedpath": value}


@mcp.tool
def inspect_url(
    site_url: str,
    inspection_url: str,
    language_code: str = "en-US",
) -> dict[str, Any]:
    """Read Google's indexed status for one URL: index verdict, coverage, last crawl, canonical, mobile and rich results. Read-only; it cannot request indexing."""
    site = _require_property(site_url)
    target = inspection_url.strip()
    if not target.lower().startswith(("http://", "https://")):
        raise ValueError("inspection_url must be a full http(s) URL inside the property.")
    body = {"inspectionUrl": target, "siteUrl": site, "languageCode": language_code}
    response = _execute(
        _service("searchconsole", "v1").urlInspection().index().inspect(body=body),
        "Search Console",
    )
    return response.get("inspectionResult", response)


if __name__ == "__main__":
    mcp.run()
