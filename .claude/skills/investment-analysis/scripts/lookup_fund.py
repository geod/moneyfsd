#!/usr/bin/env python3
"""
Fund composition lookup via web + LLM parsing.

For an unknown ticker, fetches a sequence of candidate pages (Yahoo Finance
holdings, Morningstar portfolio, Morningstar quote) and asks Claude to
extract a structured asset-allocation breakdown from each page until one
succeeds.

Falls back gracefully:
- No ANTHROPIC_API_KEY in env  → returns None (caller falls back to prompt_and_persist)
- `anthropic` SDK not installed → auto-installs on first use
- Network failure / page empty / parse failure → tries next candidate URL
- All candidates exhausted     → returns None

Output format (one entry per resolved fund):

    {
      "asset_classes": { "us_equity": 0.55, ... },     # sums to ~1.0
      "expense_ratio": 0.0021,
      "distribution_character": "mixed",
      "_lookup_source": "<url that succeeded>",
      "_lookup_date": "2026-05-14",
      "_confidence": "high" | "medium" | "low"
    }

Usage as a module:
    from lookup_fund import lookup_fund_via_web
    result = lookup_fund_via_web("PPQZX", "PIMCO RealPath Blend 2050")

Usage as CLI (for ad-hoc testing):
    python lookup_fund.py PPQZX "PIMCO RealPath Blend 2050"
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from datetime import date
from typing import Optional


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------

def _ensure(pkg: str, import_name: Optional[str] = None) -> bool:
    """Best-effort install. Returns True if importable after the attempt."""
    name = import_name or pkg
    try:
        __import__(name)
        return True
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                check=True, capture_output=True,
            )
            __import__(name)
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# Page fetching
# -----------------------------------------------------------------------------

_REAL_TICKER_RE = re.compile(r"^[A-Z]{1,6}(\.[A-Z]{1,2})?$")


def _resolve_real_ticker(ticker: str, description: str) -> str:
    """If `ticker` doesn't look like a real exchange ticker (e.g., it's a
    truncated fund-name fragment from the 401(k) plan parser), search Yahoo
    Finance for the canonical ticker by description. Returns either the
    resolved ticker or the original input unchanged.
    """
    if _REAL_TICKER_RE.fullmatch(ticker):
        return ticker
    if not _ensure("requests"):
        return ticker
    import requests  # noqa: PLC0415

    query = description or ticker
    # Yahoo's symbol search endpoint (public, no auth)
    url = (
        "https://query1.finance.yahoo.com/v1/finance/search"
        f"?q={requests.utils.quote(query)}&quotesCount=5&newsCount=0"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return ticker
        data = r.json()
        for q in data.get("quotes") or []:
            qt = q.get("quoteType")
            sym = q.get("symbol")
            if sym and qt in ("MUTUALFUND", "ETF", "EQUITY"):
                return sym
    except Exception:
        return ticker
    return ticker


def _candidate_urls(ticker: str) -> list[str]:
    """Ordered list of URLs to try for a given ticker.

    Higher-quality / more reliable sources first.
    """
    t = ticker.upper()
    t_lower = t.lower()
    return [
        # Yahoo Finance — holdings tab (good for ETFs + mutual funds)
        f"https://finance.yahoo.com/quote/{t}/holdings",
        # Yahoo Finance — main quote page (has summary asset allocation)
        f"https://finance.yahoo.com/quote/{t}/",
        # Morningstar — portfolio tab (often paywalled but worth trying)
        f"https://www.morningstar.com/funds/xnas/{t_lower}/portfolio",
        f"https://www.morningstar.com/funds/xnas/{t_lower}/quote",
        # Fallback: ETF.com
        f"https://www.etf.com/{t}",
    ]


def _fetch_page(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a URL. Returns text content (HTML or extracted PDF text).
    None on any failure.
    """
    if not _ensure("requests"):
        return None
    import requests  # noqa: PLC0415

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            if not _ensure("pdfplumber"):
                return None
            import pdfplumber  # noqa: PLC0415
            try:
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    return "\n".join(p.extract_text() or "" for p in pdf.pages[:8])
            except Exception:
                return None
        # HTML — strip script/style for cleaner LLM input
        return _strip_html(r.text)
    except Exception:
        return None


_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Cheap HTML-to-text. Keeps enough structure for an LLM to parse."""
    s = _SCRIPT_RE.sub(" ", html)
    s = _TAG_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s


# -----------------------------------------------------------------------------
# LLM parsing
# -----------------------------------------------------------------------------

LOOKUP_SYSTEM_PROMPT = """You are a financial data extraction tool. Given a web page about a single investment fund (ETF or mutual fund), extract the fund's CURRENT asset-allocation breakdown.

Output strictly valid JSON, no commentary, no markdown fences. Schema:

{
  "found": true | false,
  "name": "<full fund name>" | null,
  "ticker": "<ticker symbol>" | null,
  "asset_classes": {
    "us_equity": <0..1>,
    "intl_dev_equity": <0..1>,
    "intl_em_equity": <0..1>,
    "us_bonds": <0..1>,
    "intl_bonds": <0..1>,
    "cash": <0..1>,
    "real_estate": <0..1>,
    "alt_concentrated": <0..1>,
    "crypto": <0..1>
  },
  "expense_ratio": <decimal e.g. 0.0021 for 0.21%> | null,
  "distribution_character": "qualified_dividend" | "ordinary" | "muni" | "mixed" | "none" | "unknown",
  "as_of_date": "<ISO date>" | null,
  "confidence": "high" | "medium" | "low",
  "notes": "<one short sentence if found=false>"
}

Hard rules:
1. asset_classes weights MUST sum to between 0.95 and 1.05 (allow rounding).
2. Use ONLY the keys listed above. Fold any extra categories into the closest match:
   - "Convertibles" → us_bonds
   - "Preferred stock" → us_equity (or intl_dev_equity if foreign)
   - "Other" → cash (unless clearly a real asset, then real_estate)
3. If the page splits foreign stock by region (developed/EM), use those values directly.
4. If the page lumps "foreign stock" without split, assume 70% dev / 30% EM.
5. For target-date funds, use the CURRENT allocation, NOT the glide-path target year.
6. For active multi-sector bond funds without further breakdown, default to 75% us_bonds / 20% intl_bonds / 5% cash.
7. If you cannot find composition data with reasonable confidence, set found=false. Do not invent numbers.

Confidence levels:
- "high":   asset allocation explicitly stated on the page with all major buckets
- "medium": stated with some buckets inferred or aggregated
- "low":    only partial data; significant inference required
"""


def _call_claude_sdk(user_content: str) -> Optional[str]:
    """Anthropic SDK path. Returns response text or None if unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    if not _ensure("anthropic"):
        return None
    from anthropic import Anthropic  # noqa: PLC0415
    try:
        client = Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=LOOKUP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        parts = [b.text for b in resp.content if hasattr(b, "text")]
        return "".join(parts) if parts else None
    except Exception:
        return None


def _call_claude_cli(user_content: str) -> Optional[str]:
    """Fallback for environments without ANTHROPIC_API_KEY but with `claude` CLI
    on PATH (e.g., when running inside Claude Code). Spawns `claude -p` with
    the system+user prompt and reads the response from stdout.
    """
    import shutil  # noqa: PLC0415
    if not shutil.which("claude"):
        return None
    prompt = f"{LOOKUP_SYSTEM_PROMPT}\n\n---\n\n{user_content}"
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5-20251001"],
            input=prompt, capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _parse_via_claude(ticker: str, description: str, url: str, page_text: str) -> Optional[dict]:
    """Send page text to Claude, get structured breakdown back.

    Tries the Anthropic SDK first, then falls back to the `claude` CLI for
    environments where the SDK can't authenticate (e.g., inside Claude Code
    sessions where auth is routed through ANTHROPIC_BASE_URL).
    """
    trimmed = page_text[:30000]
    user_content = (
        f"Ticker: {ticker}\n"
        f"Description from statement: {description}\n"
        f"Source URL: {url}\n\n"
        f"--- PAGE TEXT ---\n{trimmed}"
    )

    response_text = _call_claude_sdk(user_content) or _call_claude_cli(user_content)
    if not response_text:
        return None

    # Extract first JSON object from the response text.
    m = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    if not data.get("found"):
        return None

    asset_classes = data.get("asset_classes") or {}
    if not isinstance(asset_classes, dict):
        return None
    # Drop zero weights for compactness
    asset_classes = {k: float(v) for k, v in asset_classes.items() if float(v or 0) > 0}
    total = sum(asset_classes.values())
    if not (0.95 <= total <= 1.05):
        return None

    return {
        "asset_classes": asset_classes,
        "expense_ratio": data.get("expense_ratio"),
        "distribution_character": data.get("distribution_character") or "unknown",
        "_lookup_source": url,
        "_lookup_date": date.today().isoformat(),
        "_confidence": data.get("confidence") or "unknown",
        "_fund_name": data.get("name"),
    }


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------

def lookup_fund_via_web(ticker: str, description: str = "",
                         verbose: bool = False) -> Optional[dict]:
    """Try multiple sources; return first successful structured breakdown."""
    # Check we have *some* path to Claude (SDK with key OR `claude` CLI on PATH)
    import shutil as _shutil  # noqa: PLC0415
    has_sdk_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_cli = bool(_shutil.which("claude"))
    if not has_sdk_key and not has_cli:
        if verbose:
            print(f"  [{ticker}] no ANTHROPIC_API_KEY and no `claude` CLI — web_lookup skipped",
                  file=sys.stderr)
        return None

    # Resolve fake/truncated tickers (e.g., "PIMCOREALPATHBLEND20") to the
    # actual exchange ticker (e.g., "PPQZX") before fetching pages.
    real_ticker = _resolve_real_ticker(ticker, description)
    if real_ticker != ticker and verbose:
        print(f"  [{ticker}] resolved description → real ticker {real_ticker}",
              file=sys.stderr)

    for url in _candidate_urls(real_ticker):
        if verbose:
            print(f"  [{ticker}] trying {url}", file=sys.stderr)
        text = _fetch_page(url)
        if not text or len(text) < 500:
            continue
        result = _parse_via_claude(ticker, description, url, text)
        if result:
            # Record the resolved real ticker on the result so callers know
            # what was actually fetched.
            if real_ticker != ticker:
                result["_resolved_ticker"] = real_ticker
            if verbose:
                print(f"  [{ticker}] resolved via {url} (confidence={result['_confidence']})",
                      file=sys.stderr)
            return result

    if verbose:
        print(f"  [{ticker}] all sources exhausted — no breakdown found",
              file=sys.stderr)
    return None


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticker")
    ap.add_argument("description", nargs="?", default="")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    result = lookup_fund_via_web(args.ticker, args.description, verbose=args.verbose)
    if result is None:
        print("No breakdown found.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
