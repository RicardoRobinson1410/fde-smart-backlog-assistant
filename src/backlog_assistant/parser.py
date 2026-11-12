"""Document ingestion (.txt, .md, .pdf), PII redaction, and local JSON backlog integration."""

from __future__ import annotations
import json, logging, re
from pathlib import Path
from pypdf import PdfReader
from backlog_assistant.models import ExistingBacklogItem

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{16,}|ghp_[A-Za-z0-9]{16,})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_PAN]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
]


def redact_pii_and_secrets(text: str) -> tuple[str, int]:
    """Scrub emails, API keys/tokens, PANs, and SSNs prior to external LLM API calls."""
    redacted_count = 0
    sanitized = text
    for pattern, replacement in _PII_PATTERNS:
        sanitized, count = pattern.subn(replacement, sanitized)
        redacted_count += count
    return sanitized, redacted_count


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


def load_existing_backlog(backlog_path: str | Path | None = None) -> list[ExistingBacklogItem]:
    """Load baseline backlog items from local JSON."""
    items: list[ExistingBacklogItem] = []
    if backlog_path:
        path = Path(backlog_path)
        if not path.exists():
            raise FileNotFoundError(f"Existing backlog JSON file not found: {path}")
        raw_list = json.loads(path.read_text(encoding="utf-8"))
        items.extend(ExistingBacklogItem.model_validate(entry) for entry in raw_list)
    return items
