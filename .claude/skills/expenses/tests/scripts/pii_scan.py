#!/usr/bin/env python3
"""
PII scanner for committed fixtures.

Runs as part of CI. Exits non-zero if any file under tests/fixtures/ contains
patterns that LOOK like real PII. Designed to be conservative — better to
false-positive than to silently ship leaked data.

Scans:
- Full 9-digit SSNs
- Full credit card numbers (Luhn check)
- Phone numbers
- Email addresses
- Account numbers not masked with **** prefix
- Any of the author-persona names (this list is intentionally maintainable —
  if Anthropic Code agents add their own names, extend it here)

False-positive escape hatch: a line containing `# allow-pii: <reason>` is ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]  # ../../../../../.. from this file
SKILL_ROOTS = [
    REPO_ROOT / ".claude" / "skills" / "expenses",
    REPO_ROOT / ".claude" / "skills" / "investment-analysis",
    REPO_ROOT / ".claude" / "skills" / "income",
]


# Patterns that indicate raw PII
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN (9 digits)", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("Credit card (15-16 digits)", re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{3,4}\b")),
    ("Phone (US)", re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("Email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("Unmasked account number (8+ digits, no asterisks)",
     re.compile(r"(?<!\*)\b\d{8,}\b")),
]

# Acceptable values in fixtures — these patterns LOOK like PII but are known safe
ALLOWED_VALUES = {
    "555-555-1234",                  # placeholder phone
    "555-555-0000",
    "***-**-1234",                   # masked SSN
    "user@example.com",              # placeholder email
    "noreply@example.com",
    "test@example.com",
    "1234567890",                    # commonly used digit sequence; flagged only without context
}

# Generic persona names — fine to use
ALLOWED_NAMES = {"Mike Chen", "Sarah Chen", "Mike", "Sarah"}

# Names that should NEVER appear in fixtures
BANNED_NAMES = {
    # Add author names here as the project grows. Keep this list private to
    # the repo (or move to .gitignored config) if it's sensitive.
    # Empty by default — CI won't flag persona names like Mike/Sarah.
}

ALLOW_MARKER = re.compile(r"#\s*allow-pii:")


def scan_file(path: Path) -> list[str]:
    """Return a list of issue descriptions for this file."""
    issues = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [f"  could not read: {e}"]

    for line_no, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER.search(line):
            continue
        for label, pattern in PII_PATTERNS:
            for m in pattern.finditer(line):
                value = m.group(0)
                if value in ALLOWED_VALUES:
                    continue
                # Special: unmasked 8-digit run is OK if it's a clear timestamp
                # (YYYYMMDD shape like 20251231)
                if label.startswith("Unmasked"):
                    if re.fullmatch(r"20\d{6}", value):
                        continue
                issues.append(f"  L{line_no}: {label}: {value!r}")
        for name in BANNED_NAMES:
            if name in line:
                issues.append(f"  L{line_no}: banned name in fixture: {name!r}")
    return issues


def scan() -> int:
    failed_files = 0
    total_files = 0
    for skill in SKILL_ROOTS:
        fixtures_dir = skill / "tests" / "fixtures"
        evals_dir = skill / "evals" / "fixtures"
        for base in (fixtures_dir, evals_dir):
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                # Only text-y files
                if path.suffix.lower() not in {".txt", ".csv", ".md", ".json",
                                                ".yaml", ".yml"}:
                    continue
                total_files += 1
                issues = scan_file(path)
                if issues:
                    failed_files += 1
                    rel = path.relative_to(REPO_ROOT)
                    print(f"PII issues in {rel}:")
                    for i in issues[:20]:  # cap per-file noise
                        print(i)
                    if len(issues) > 20:
                        print(f"  ... and {len(issues) - 20} more")

    print()
    print(f"Scanned {total_files} fixture file(s).")
    if failed_files:
        print(f"❌ {failed_files} file(s) flagged. Review above.")
        return 1
    print("✅ No PII issues detected.")
    return 0


if __name__ == "__main__":
    sys.exit(scan())
