#!/usr/bin/env python3
"""
Phase 4: Classify positions — map each holding to its asset-class breakdown,
sector, expense ratio, distribution character.

Reads:
- positions.csv (output of consolidate.py)
- references/data/fund_asset_class_map.yaml
- references/data/stock_sector_map.yaml
- references/data/distribution_character.yaml
- references/data/thresholds.yaml
- investment_analysis_config.yaml (for fund_overrides + stock_overrides)

Writes:
- positions_classified.csv — one row per (position, asset_class) tuple
- classification_unknowns.md — funds/stocks that couldn't be classified

Usage:
    python classify_funds.py <work_folder> [--config PATH] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

# Allow `from lookup_fund import ...` when invoked as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))


# -----------------------------------------------------------------------------
# Data containers
# -----------------------------------------------------------------------------

@dataclass
class ClassifiedRow:
    # Original position metadata (preserved)
    account: str
    account_type: str
    owner: str
    employer: Optional[str]
    nested_inside: Optional[str]
    ticker: str
    description: str
    section: str
    quantity: Optional[float]
    market_value_gross: float
    market_value_net: float
    cost_basis: Optional[float]
    unrealized_gain: Optional[float]
    vested: Optional[bool]
    vest_date: Optional[str]
    source_file: str

    # New classification fields
    asset_class: str
    asset_class_weight: float
    weighted_value_gross: float
    weighted_value_net: float
    sector: Optional[str]
    region: Optional[str]
    sub_asset: Optional[str]
    issuer: Optional[str]
    distribution_character: Optional[str]
    distribution_at_payout: Optional[str]
    expense_ratio: Optional[float]
    index: Optional[str]
    implied_sector_weights: Optional[str]      # serialized JSON
    classification_source: str
    classification_date: str


# -----------------------------------------------------------------------------
# Loaders
# -----------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def build_registry(data_dir: Path, config: dict,
                    auto_overrides_path: Optional[Path] = None) -> tuple[dict, dict, dict, dict]:
    fund_map = load_yaml(data_dir / "fund_asset_class_map.yaml")
    stock_map = load_yaml(data_dir / "stock_sector_map.yaml")
    dist_char = load_yaml(data_dir / "distribution_character.yaml")
    taxonomy = load_yaml(data_dir / "account_type_taxonomy.yaml")

    def _merge_overrides(overrides: dict, source_label: str) -> None:
        for ticker, mapping in (overrides or {}).items():
            existing = fund_map.get(ticker, {})
            if isinstance(mapping, dict) and "asset_classes" in mapping:
                existing.update(mapping)
            else:
                # Bare dict of class→weight
                existing["asset_classes"] = mapping
            existing.setdefault("name", ticker)
            existing["_source"] = source_label
            fund_map[ticker] = existing

    # User-edited overrides (highest authority)
    _merge_overrides(config.get("fund_overrides", {}), "user_override")

    # Auto-resolved overrides from prior web_lookup runs (lower authority — user can correct)
    if auto_overrides_path and auto_overrides_path.is_file():
        auto = load_yaml(auto_overrides_path) or {}
        _merge_overrides(auto.get("fund_overrides", {}), "auto_lookup")

    # Merge stock_overrides
    for ticker, mapping in config.get("stock_overrides", {}).items():
        stock_map[ticker] = {**(stock_map.get(ticker) or {}), **mapping, "_source": "user_override"}

    return fund_map, stock_map, dist_char, taxonomy


def append_auto_override(auto_overrides_path: Path, ticker: str, entry: dict) -> None:
    """Persist a resolved lookup to the sidecar file, preserving prior entries."""
    existing = {}
    if auto_overrides_path.is_file():
        existing = load_yaml(auto_overrides_path) or {}
    overrides = existing.setdefault("fund_overrides", {})
    overrides[ticker] = entry
    # Header comment + write
    header = (
        "# Auto-resolved fund overrides, written by classify_funds.py when\n"
        "# `classify.unknown_fund_behavior: web_lookup` is active.\n"
        "#\n"
        "# Each entry was extracted from a public fund factsheet / data page by\n"
        "# Claude (claude-haiku-4-5). Review and correct as needed — entries here\n"
        "# can be promoted into your main investment_analysis_config.yaml under\n"
        "# `fund_overrides:` if you want stronger authority.\n"
        "#\n"
        "# User-edited overrides in the main config always win over auto entries.\n\n"
    )
    with auto_overrides_path.open("w") as f:
        f.write(header)
        yaml.safe_dump(existing, f, sort_keys=False, default_flow_style=False)


def resolve_synonym(ticker: str, fund_map: dict) -> str:
    synonyms = fund_map.get("synonyms") or {}
    return synonyms.get(ticker, ticker)


def resolve_cusip(ticker: str, fund_map: dict) -> str:
    """Some statements use CUSIPs. Map to canonical ticker if possible."""
    cusip_map = fund_map.get("cusip_map") or {}
    return cusip_map.get(ticker, ticker)


# -----------------------------------------------------------------------------
# Classification
# -----------------------------------------------------------------------------

def classify_position(row: pd.Series, fund_map: dict, stock_map: dict,
                       dist_char: dict, taxonomy: dict,
                       classification_date: str) -> tuple[list[ClassifiedRow], Optional[dict]]:
    """Returns (rows, unknown_record). unknown_record is non-None iff classification failed."""
    ticker = str(row.get("ticker") or "").strip().upper()
    section = str(row.get("section") or "").lower()
    account_type = str(row.get("account_type") or "")
    mv_gross = float(row.get("market_value_gross", 0) or 0)
    mv_net = float(row.get("market_value_net", 0) or 0)

    # --- Cash ---
    if ticker == "CASH" or section == "cash":
        return [_make_row(row, "cash", 1.0, "ordinary",
                          _payout_char(account_type, "ordinary", dist_char),
                          source="rule:cash", classification_date=classification_date)], None

    # --- Real estate ---
    if section == "real_estate" or account_type == "real_estate":
        return [_make_row(row, "real_estate", 1.0, "none",
                          _payout_char(account_type, "none", dist_char),
                          sub_asset=row.get("notes"),
                          source="rule:real_estate", classification_date=classification_date)], None

    # --- Crypto ---
    if section == "crypto" or account_type == "crypto":
        sub = _crypto_sub(ticker)
        return [_make_row(row, "crypto", 1.0, "none",
                          _payout_char(account_type, "none", dist_char),
                          sub_asset=sub,
                          source="rule:crypto", classification_date=classification_date)], None

    # --- Concentrated alts (M Units, LTIPs, partnership units, RSUs, ESPP) ---
    if account_type in {"alt_concentrated", "ltip", "rsu_award", "espp",
                        "nqdc", "nqdc_pcra"} and section in {"alt_concentrated", "ltip", "rsu_award", "espp", "other", "alt"}:
        # Wrapper-level alt classification — only for manual holdings, not for funds
        # held INSIDE these wrappers (those classify normally per their ticker).
        pass  # fall through to ticker lookup; non-fund manual holdings handled below

    # --- Resolve ticker via overrides → registry → synonyms → CUSIP ---
    canonical = resolve_synonym(ticker, fund_map)
    canonical = resolve_cusip(canonical, fund_map)
    entry = fund_map.get(canonical)

    if entry and isinstance(entry, dict) and entry.get("asset_classes"):
        return _emit_fund_rows(row, canonical, entry, dist_char, account_type, classification_date), None

    # --- Stock lookup ---
    stock_entry = stock_map.get(ticker)
    if stock_entry:
        region = stock_entry.get("region", "us")
        asset_class = {
            "us": "us_equity",
            "intl_developed": "intl_dev_equity",
            "emerging": "intl_em_equity",
        }.get(region, "us_equity")
        return [_make_row(
            row, asset_class, 1.0, "qualified_dividend",
            _payout_char(account_type, "qualified_dividend", dist_char),
            sector=stock_entry.get("sector"),
            region=region,
            issuer=stock_entry.get("issuer"),
            source="stock_map", classification_date=classification_date,
        )], None

    # --- Manual holding without registry entry (M Units, LTIPs, etc.) ---
    if account_type in {"alt_concentrated", "ltip", "rsu_award", "espp"}:
        return [_make_row(
            row, "alt_concentrated", 1.0, "ordinary",
            _payout_char(account_type, "ordinary", dist_char),
            sub_asset=account_type,
            issuer=row.get("employer"),
            source="account_type", classification_date=classification_date,
        )], None

    # --- DB pension → bond-equivalent ---
    if account_type in {"pension_db", "pension_cb", "pension_unknown"}:
        return [_make_row(
            row, "us_bonds", 1.0, "ordinary",
            _payout_char(account_type, "ordinary", dist_char),
            source="rule:pension", classification_date=classification_date,
        )], None

    # --- Unknown ---
    return [], {
        "ticker": ticker,
        "description": row.get("description", ""),
        "account": row.get("account", ""),
        "account_type": account_type,
        "market_value_gross": mv_gross,
    }


def _emit_fund_rows(row: pd.Series, canonical: str, entry: dict,
                     dist_char: dict, account_type: str,
                     classification_date: str) -> list[ClassifiedRow]:
    rows: list[ClassifiedRow] = []
    classes = entry["asset_classes"]
    default_char = entry.get("distribution_character") or dist_char.get(
        "defaults_by_category", {}
    ).get(entry.get("category"), "unknown")
    payout = _payout_char(account_type, default_char, dist_char)
    er = entry.get("expense_ratio")
    idx = entry.get("index")
    import json as _json
    isw_serialized = _json.dumps(entry.get("implied_sector_weights")) if entry.get("implied_sector_weights") else None

    for asset_class, weight in classes.items():
        rows.append(_make_row(
            row, asset_class, weight, default_char, payout,
            source=entry.get("_source") or "registry",
            classification_date=classification_date,
            expense_ratio=er, index=idx,
            implied_sector_weights=isw_serialized,
        ))
    return rows


def _payout_char(account_type: str, default_char: str, dist_char: dict) -> str:
    overrides = (dist_char.get("overrides_by_account_type") or {}).get(account_type) or {}
    return overrides.get("distribution_at_payout", default_char)


def _crypto_sub(ticker: str) -> str:
    if ticker in {"BTC", "XBT"}:
        return "BTC"
    if ticker in {"ETH"}:
        return "ETH"
    return "other_major" if ticker else "altcoin"


def _make_row(row: pd.Series, asset_class: str, weight: float,
              distribution_character: str, payout: str,
              sector: Optional[str] = None, region: Optional[str] = None,
              sub_asset: Optional[str] = None, issuer: Optional[str] = None,
              expense_ratio: Optional[float] = None, index: Optional[str] = None,
              implied_sector_weights: Optional[str] = None,
              source: str = "default",
              classification_date: str = "") -> ClassifiedRow:
    mv_gross = float(row.get("market_value_gross", 0) or 0)
    mv_net = float(row.get("market_value_net", 0) or 0)
    return ClassifiedRow(
        account=str(row.get("account", "")),
        account_type=str(row.get("account_type", "")),
        owner=str(row.get("owner", "")),
        employer=row.get("employer") if pd.notna(row.get("employer")) else None,
        nested_inside=row.get("nested_inside") if pd.notna(row.get("nested_inside")) else None,
        ticker=str(row.get("ticker", "")),
        description=str(row.get("description", "")),
        section=str(row.get("section", "")),
        quantity=float(row["quantity"]) if pd.notna(row.get("quantity")) else None,
        market_value_gross=mv_gross,
        market_value_net=mv_net,
        cost_basis=float(row["cost_basis"]) if pd.notna(row.get("cost_basis")) else None,
        unrealized_gain=float(row["unrealized_gain"]) if pd.notna(row.get("unrealized_gain")) else None,
        vested=bool(row["vested"]) if pd.notna(row.get("vested")) else None,
        vest_date=str(row["vest_date"]) if pd.notna(row.get("vest_date")) else None,
        source_file=str(row.get("source_file", "")),
        asset_class=asset_class,
        asset_class_weight=weight,
        weighted_value_gross=mv_gross * weight,
        weighted_value_net=mv_net * weight,
        sector=sector,
        region=region,
        sub_asset=sub_asset,
        issuer=issuer,
        distribution_character=distribution_character,
        distribution_at_payout=payout,
        expense_ratio=expense_ratio,
        index=index,
        implied_sector_weights=implied_sector_weights,
        classification_source=source,
        classification_date=classification_date,
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="Defaults to <skill_dir>/references/data")
    args = ap.parse_args()

    data_dir = args.data_dir or (Path(__file__).parent.parent / "references" / "data")
    config = load_yaml(args.config) if args.config else {}
    thresholds = load_yaml(data_dir / "thresholds.yaml")

    # The auto-overrides sidecar lives at the working-folder root (not inside
    # .analysis/) so the user can see and edit it alongside their main config.
    work_root = args.work_folder if args.work_folder.name != ".analysis" else args.work_folder.parent
    auto_overrides_path = work_root / "fund_overrides_auto.yaml"

    fund_map, stock_map, dist_char, taxonomy = build_registry(data_dir, config, auto_overrides_path)

    # Determine unknown-fund behavior
    behavior = (config.get("classify") or {}).get("unknown_fund_behavior") \
               or (thresholds.get("classify") or {}).get("unknown_fund_behavior", "prompt_and_persist")

    # Intermediates live in .analysis/ subfolder
    io_dir = args.work_folder if args.work_folder.name == ".analysis" else args.work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)

    pos_path = io_dir / "positions.csv"
    if not pos_path.is_file():
        print(f"error: {pos_path} not found", file=sys.stderr)
        return 2

    positions = pd.read_csv(pos_path)
    from datetime import date as _date
    classification_date = _date.today().isoformat()

    # If web_lookup mode is active, pre-resolve unknowns before final classification.
    if behavior == "web_lookup":
        try:
            from lookup_fund import lookup_fund_via_web
        except ImportError:
            print("  ⚠ lookup_fund module not available — falling back to prompt_and_persist",
                  file=sys.stderr)
            lookup_fund_via_web = None
        if lookup_fund_via_web:
            # Find unknowns once, look them up, persist, then classify normally.
            seen: set[str] = set()
            resolved_count = 0
            for _, row in positions.iterrows():
                _rows, unknown = classify_position(
                    row, fund_map, stock_map, dist_char, taxonomy, classification_date,
                )
                if not unknown:
                    continue
                ticker = unknown["ticker"]
                if ticker in seen:
                    continue
                seen.add(ticker)
                # Skip if it's not a fund-ticker shape (e.g., long synthetic name from the qualified-plan parser)
                lookup_key = ticker
                description = unknown.get("description", "")
                print(f"  Looking up {lookup_key} ({description[:50]}) ...", file=sys.stderr)
                result = lookup_fund_via_web(lookup_key, description, verbose=False)
                if not result:
                    continue
                # Persist + apply
                append_auto_override(auto_overrides_path, lookup_key, result)
                existing = fund_map.get(lookup_key, {})
                existing.update({
                    "asset_classes": result["asset_classes"],
                    "expense_ratio": result.get("expense_ratio"),
                    "distribution_character": result.get("distribution_character"),
                    "_source": "auto_lookup",
                })
                existing.setdefault("name", result.get("_fund_name") or lookup_key)
                fund_map[lookup_key] = existing
                resolved_count += 1
            if resolved_count:
                print(f"  Auto-resolved {resolved_count} unknown(s) via web lookup → {auto_overrides_path.name}",
                      file=sys.stderr)

    classified: list[ClassifiedRow] = []
    unknowns: list[dict] = []
    for _, row in positions.iterrows():
        rows, unknown = classify_position(row, fund_map, stock_map, dist_char, taxonomy, classification_date)
        classified.extend(rows)
        if unknown:
            unknowns.append(unknown)

    # Write positions_classified.csv
    out_path = io_dir / "positions_classified.csv"
    fieldnames = list(ClassifiedRow.__dataclass_fields__.keys())
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in classified:
            writer.writerow(c.__dict__)

    # Write classification_unknowns.md
    unk_path = io_dir / "classification_unknowns.md"
    if unknowns:
        lines = [
            "# Classification Unknowns",
            "",
            f"{len(unknowns)} position(s) could not be classified against the registry.",
            "Add them to `fund_overrides` (for funds) or `stock_overrides` (for individual stocks)",
            "in your `investment_analysis_config.yaml`, then re-run classify.",
            "",
            "| Ticker | Description | Account | Type | Value |",
            "|---|---|---|---:|---:|",
        ]
        for u in unknowns:
            lines.append(
                f"| `{u['ticker']}` | {u['description']} | {u['account']} | "
                f"{u['account_type']} | ${u['market_value_gross']:,.2f} |"
            )
        unk_path.write_text("\n".join(lines))
    else:
        unk_path.write_text("# Classification Unknowns\n\n_None — every position classified cleanly._\n")

    # Summary
    total_gross = sum(c.weighted_value_gross for c in classified)
    print(f"Classified {len(positions)} positions → {len(classified)} (asset-class-weighted) rows.")
    print(f"Total gross investable across classified rows: ${total_gross:,.2f}")
    if unknowns:
        print(f"  ⚠ {len(unknowns)} unknown(s) — see classification_unknowns.md")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
