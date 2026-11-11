"""Utility to generate the sample PCI-DSS compliance PDF specification and build the OneDrive submission ZIP."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

PCI_SPEC_LINES = [
    "DOCUMENT: PCI-DSS v4.0 Mandatory Security & Audit Specification (Q4 Audit Gate)",
    "CLASSIFICATION: Mandatory Engineering Compliance Requirements",
    "",
    "Requirement 1: Envelope Encryption for Cached Checkout Payloads (CONFLICTS WITH FIN-106)",
    "- All cached merchant checkout and cardholder session payloads in Redis MUST use AES-256-GCM",
    "  envelope encryption backed by AWS KMS per-tenant data keys.",
    "- NOTE: This directly conflicts with existing backlog item FIN-106 (Plaintext Session Payload",
    "  Caching in Shared Redis Cluster), which must be superseded or blocked immediately.",
    "",
    "Requirement 2: Immutable Tamper-Evident Security Audit Trail (NEW)",
    "- Every administrative privilege escalation, API key rotation, and SSO configuration change",
    "  must emit a structured JSON audit event signed with HMAC-SHA256 to an append-only S3 Object",
    "  Lock bucket.",
    "- Retention window for cold archival storage (7 years vs 10 years) is pending Legal sign-off.",
]


def write_minimal_pdf(output_path: Path, lines: list[str]) -> None:
    """Create a valid, standards-compliant PDF document extractable by pypdf without external binaries."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    escaped_ops = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped_ops.append(f"({safe}) Tj T*")
    escaped_ops.append("ET")
    stream_bytes = "\n".join(escaped_ops).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf.extend(f"{idx} 0 obj\n".encode("ascii"))
        buf.extend(obj)
        buf.extend(b"\nendobj\n")

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    output_path.write_bytes(bytes(buf))


def package_submission_zip(root_dir: Path, zip_name: str = "Certified_RDE_Smart_Backlog_Assistant.zip") -> Path:
    """Create a clean OneDrive submission ZIP archive excluding virtualenvs, caches, and temp artifacts."""
    excluded_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "outputs"}
    zip_path = root_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(root_dir.rglob("*")):
            if file_path.is_dir() or file_path == zip_path:
                continue
            if any(part in excluded_dirs for part in file_path.parts):
                continue
            if file_path.suffix == ".pyc":
                continue
            zf.write(file_path, file_path.relative_to(root_dir))
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate sample PDF and optional OneDrive submission ZIP.")
    parser.add_argument("--pdf-out", default="data/samples/03_pci_compliance_spec.pdf")
    parser.add_argument("--package", action="store_true", help="Create clean OneDrive submission ZIP archive")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_out)
    write_minimal_pdf(pdf_path, PCI_SPEC_LINES)
    print(f"Generated sample PDF: {pdf_path}")

    if args.package:
        zip_path = package_submission_zip(Path.cwd())
        print(f"Packaged OneDrive submission archive: {zip_path} ({zip_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
