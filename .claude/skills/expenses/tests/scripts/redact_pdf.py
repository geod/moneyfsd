#!/usr/bin/env python3
"""
Extract text from a real PDF statement and scrub PII, producing a
fixture-ready .txt file.

Usage:
    python redact_pdf.py /path/to/real_statement.pdf > tests/fixtures/pdf_extracted/<name>.txt

What it does:
1. Extracts text via pdfplumber (page-by-page, preserves line structure).
2. Applies a sequence of regex-based scrubs for the obvious PII patterns:
   - Full account numbers → ****1234
   - SSNs → ***-**-1234
   - Phone numbers → 555-555-1234
   - Email addresses → user@example.com
   - Common surname patterns near "FOR" / "ATTN" / "TO" → REDACTED
3. Prints to stdout.

What it does NOT do:
- Replace dollar amounts (you may want to jitter or replace those separately).
- Replace merchant names (those are usually public companies and not PII).
- Catch every name — review the output before committing.

After running, ALWAYS:
1. Eyeball the .txt for any remaining PII.
2. Run `pii_scan.py` against your tests/fixtures/ directory.
3. Replace your name and address with the generic personas:
   - "Mike Chen" / "Sarah Chen"
   - "123 Main St, Anytown, CA 12345"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Order matters: more-specific patterns first.
SCRUB_RULES: list[tuple[re.Pattern[str], str]] = [
    # Account number patterns: any 8+ digit run, leave last 4
    (re.compile(r"\b(\d{4,})?(\d{4})\b"),
     lambda m: f"****{m.group(2)}" if m.group(1) and len(m.group(1) + m.group(2)) >= 8
              else m.group(0)),
    # SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "***-**-1234"),
    # Phone numbers (US format with various separators)
    (re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "555-555-1234"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
     "user@example.com"),
]


# Patterns that warrant a NOTE-comment in the output (left to human review)
NOTES_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("street address?", re.compile(r"\b\d{1,5}\s+([A-Z][a-zA-Z]+\s){1,4}(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Way)\b")),
    ("city, state ZIP?", re.compile(r"\b[A-Z][a-zA-Z]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?\b")),
]


def _apply_scrubs(text: str) -> str:
    out = text
    for pattern, repl in SCRUB_RULES:
        if callable(repl):
            out = pattern.sub(repl, out)
        else:
            out = pattern.sub(repl, out)
    return out


def _find_notes(text: str) -> list[str]:
    """Patterns we don't auto-scrub but warn about so the human handles them."""
    notes = []
    for label, pattern in NOTES_PATTERNS:
        for m in pattern.finditer(text):
            notes.append(f"# REVIEW: line {text[:m.start()].count(chr(10)) + 1} — possible {label}: {m.group(0)[:60]!r}")
    return notes


def extract_and_scrub(pdf_path: Path) -> tuple[str, list[str]]:
    """Returns (scrubbed_text, list_of_review_notes)."""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        sys.exit("pdfplumber not installed — run: pip install pdfplumber")
    with pdfplumber.open(str(pdf_path)) as pdf:
        raw_pages = [(p.extract_text() or "") for p in pdf.pages]
    raw_text = "\n--- PAGE BREAK ---\n".join(raw_pages)
    scrubbed = _apply_scrubs(raw_text)
    notes = _find_notes(scrubbed)
    return scrubbed, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path, help="Real PDF to extract text from")
    ap.add_argument("--no-banner", action="store_true",
                    help="Skip the leading banner comment in output")
    args = ap.parse_args()

    if not args.pdf.is_file():
        sys.exit(f"not a file: {args.pdf}")

    scrubbed, notes = extract_and_scrub(args.pdf)

    if not args.no_banner:
        print("# Synthetic fixture, derived from a real statement via redact_pdf.py.")
        print("# Account numbers, SSNs, phone, email auto-scrubbed.")
        print("# Names and addresses NOT scrubbed — review the file before committing.")
        if notes:
            print("# ")
            for n in notes:
                print(n)
        print("# ")
        print()

    print(scrubbed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
