"""Document ingestion (.txt, .md, .pdf) and existing backlog loader (JSON file + GitHub Issues CLI)."""

from __future__ import annotations
import json, logging, subprocess
from pathlib import Path
from pypdf import PdfReader
from backlog_assistant.models import BacklogAlignment, ExistingBacklogItem, GeneratedUserStory

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


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
    """Load baseline backlog items from local JSON and optionally merge open GitHub Issues."""
    items: list[ExistingBacklogItem] = []
    if backlog_path:
        path = Path(backlog_path)
        if not path.exists():
            raise FileNotFoundError(f"Existing backlog JSON file not found: {path}")
        raw_list = json.loads(path.read_text(encoding="utf-8"))
        items.extend(ExistingBacklogItem.model_validate(entry) for entry in raw_list)

    if github_repo:
        try:
            cmd = ["gh", "issue", "list", "--repo", github_repo, "--state", "open", "--limit", "30", "--json", "number,title,state,labels,body"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
            for issue in json.loads(proc.stdout or "[]"):
                labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
                items.append(ExistingBacklogItem(
                    id=f"GH-{issue['number']}", title=issue.get("title", ""), status=issue.get("state", "OPEN"),
                    priority=next((l for l in labels if l.startswith("P")), "P2 - Medium"),
                    category=labels[0] if labels else "Feature", summary=(issue.get("body") or "")[:300],
                ))
        except Exception as exc:
            logger.warning("GitHub Issues sync skipped for '%s': %s", github_repo, exc)
    return items


def export_stories_to_github(stories: list[GeneratedUserStory], repo: str, labels: list[str] | None = None, dry_run: bool = True) -> list[str]:
    """Create GitHub Issues for NEW stories via `gh issue create` (or return commands in dry_run mode)."""
    results: list[str] = []
    for s in [st for st in stories if st.backlog_alignment == BacklogAlignment.NEW]:
        body = f"**{s.user_story}**\n\n### Technical\n{s.technical_description}\n\n### ACs\n" + "\n".join(f"- [ ] {ac}" for ac in s.acceptance_criteria)
        cmd = ["gh", "issue", "create", "--repo", repo, "--title", f"[{s.id}] {s.title}", "--body", body]
        for lbl in labels or []:
            cmd.extend(["--label", lbl])
        results.append(f"[DRY-RUN] gh issue create --repo {repo} --title '[{s.id}] {s.title}'" if dry_run else subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True).stdout.strip())
    return results
