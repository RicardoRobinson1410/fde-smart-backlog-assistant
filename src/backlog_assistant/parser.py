"""Document ingestion (.txt, .md, .pdf) and GitHub PAT REST API / JSON backlog integration."""

from __future__ import annotations
import json, logging, os, subprocess, urllib.request
from pathlib import Path
from pypdf import PdfReader
from backlog_assistant.models import BacklogAlignment, ExistingBacklogItem, GeneratedUserStory

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


_CACHED_PAT: str | None = None


def _resolve_github_pat() -> str:
    """Resolve GitHub Personal Access Token from GITHUB_PAT, GITHUB_TOKEN, or `gh auth token`."""
    global _CACHED_PAT
    token = (os.getenv("GITHUB_PAT") or os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        return token
    if _CACHED_PAT is not None:
        return _CACHED_PAT
    try:
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15, check=True)
        _CACHED_PAT = proc.stdout.strip()
        return _CACHED_PAT
    except Exception:
        return ""


def _github_api_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> list | dict:
    """Execute an authenticated GitHub REST API v3 request using a GitHub PAT."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FDE-Smart-Backlog-Assistant/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_document_text(file_path: str | Path) -> str:
    """Extract and normalize text from a .txt, .md, or .pdf requirement document."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Input document not found: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file format '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    if ext == ".pdf":
        reader = PdfReader(str(path))
        raw_text = "\n\n".join((p.extract_text() or "").strip() for p in reader.pages if (p.extract_text() or "").strip())
    else:
        raw_text = path.read_text(encoding="utf-8")

    cleaned = "\n".join(line.rstrip() for line in raw_text.splitlines()).strip()
    if not cleaned:
        raise ValueError(f"Input document '{path.name}' is empty or contains no extractable text.")
    return cleaned


def load_existing_backlog(backlog_path: str | Path | None = None, github_repo: str | None = None) -> list[ExistingBacklogItem]:
    """Load baseline backlog items from local JSON and/or live GitHub Issues via GitHub PAT REST API."""
    items: list[ExistingBacklogItem] = []
    if backlog_path:
        path = Path(backlog_path)
        if not path.exists():
            raise FileNotFoundError(f"Existing backlog JSON file not found: {path}")
        raw_list = json.loads(path.read_text(encoding="utf-8"))
        items.extend(ExistingBacklogItem.model_validate(entry) for entry in raw_list)

    if github_repo:
        try:
            token = _resolve_github_pat()
            url = f"https://api.github.com/repos/{github_repo}/issues?state=open&per_page=30"
            gh_issues = _github_api_request(url, token=token, method="GET")
            if isinstance(gh_issues, list):
                for issue in gh_issues:
                    if "pull_request" in issue:
                        continue
                    labels = [lbl.get("name", "") for lbl in issue.get("labels", []) if isinstance(lbl, dict)]
                    title = issue.get("title", "")
                    # Preserve [FIN-101] style IDs if present in the GitHub issue title
                    item_id = title.split("]")[0].lstrip("[") if title.startswith("[") and "]" in title else f"GH-{issue['number']}"
                    items.append(ExistingBacklogItem(
                        id=item_id, title=title, status=issue.get("state", "open").capitalize(),
                        priority=next((l for l in labels if l.startswith("P")), "P2 - Medium"),
                        category=next((l for l in labels if not l.startswith("P")), "Feature"),
                        summary=(issue.get("body") or "")[:300],
                    ))
            logger.info("Loaded %d live backlog issues from GitHub repo '%s' via PAT.", len(items), github_repo)
        except Exception as exc:
            logger.warning("GitHub PAT backlog sync skipped for '%s': %s", github_repo, exc)
    return items


def export_stories_to_github(stories: list[GeneratedUserStory], repo: str, labels: list[str] | None = None, dry_run: bool = True) -> list[str]:
    """Create GitHub Issues for NEW stories via GitHub PAT REST API (or return preview in dry_run mode)."""
    results: list[str] = []
    token = _resolve_github_pat()
    url = f"https://api.github.com/repos/{repo}/issues"
    for s in [st for st in stories if st.backlog_alignment == BacklogAlignment.NEW]:
        title = f"[{s.id}] {s.title}"
        body = (
            f"**User Story:** {s.user_story}\n\n"
            f"**Priority:** `{s.priority}` ({s.priority_rationale})\n"
            f"**Category:** `{s.category}` | **Story Points:** `{s.story_points}`\n"
            f"**Alignment:** `{s.backlog_alignment.value}` — {s.alignment_notes}\n\n"
            f"### Technical Description\n{s.technical_description}\n\n"
            f"### Acceptance Criteria\n" + "\n".join(f"- [ ] {ac}" for ac in s.acceptance_criteria)
        )
        if dry_run:
            results.append(f"[DRY-RUN] POST {url} -> '{title}'")
        else:
            created = _github_api_request(url, token=token, method="POST", payload={"title": title, "body": body, "labels": labels or []})
            results.append(str(created.get("html_url", title)) if isinstance(created, dict) else title)
    return results
