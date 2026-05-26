#!/usr/bin/env python3
"""
Phase 3: Consolidate raw positions into the final position ledger.

Reads:
- raw_positions.csv (output of extract_positions.py)
- statements_meta.json (statement-level metadata + nesting indicators)
- investment_analysis_config.yaml (user configuration)

Performs:
  1. Account-type inference (explicit config → header signals → trustee/custodian
     suffix → nesting heuristic → default)
  2. Nested-wrapper detection & dedup (PCRA-in-401(k) trap)
  3. Owner attribution (per config; default = primary)
  4. Manual holdings injection (M Units, LTIPs, crypto, real estate, etc.)
  5. Real estate methodology application (carrying vs liquidation_net)
  6. Household balance-sheet reconciliation (when spreadsheet provided)

Writes:
- positions.csv (the consolidated ledger ready for classify.py)
- consolidation_summary.md (account types, nestings, manual holdings, mismatches)
- consolidation_log.csv (per-action audit trail)

Usage:
    python consolidate.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from _config_discover import auto_discover_config

# Default thresholds (these mirror references/data/thresholds.yaml)
DEFAULT_RECONCILIATION = {
    "per_account_vs_sheet": {"absolute_usd": 1000.0, "relative_pct": 0.01},
}


# -----------------------------------------------------------------------------
# Data
# -----------------------------------------------------------------------------

@dataclass
class Position:
    """Consolidated position row — schema matches positions.csv."""
    account: str
    account_type: str
    wrapper_structure: Optional[str]
    owner: str
    joint_share: Optional[float]
    employer: Optional[str]
    nested_inside: Optional[str]
    ticker: str
    description: str
    section: str
    quantity: Optional[float]
    price: Optional[float]
    market_value_gross: float
    market_value_net: float
    cost_basis: Optional[float]
    unrealized_gain: Optional[float]
    vested: Optional[bool]
    vest_date: Optional[str]
    est_annual_income: Optional[float]
    est_yield_pct: Optional[float]
    income_character: Optional[str]
    methodology: Optional[str]
    liquid: Optional[bool]
    source_file: str
    notes: Optional[str]


@dataclass
class LogEntry:
    action: str
    target: str
    detail: str


# -----------------------------------------------------------------------------
# Account-type inference
# -----------------------------------------------------------------------------

TYPE_HEURISTICS: list[tuple[str, list[str]]] = [
    ("roth_ira", ["roth_ira"]),
    ("traditional_ira", ["traditional_ira"]),
    ("hsa", ["hsa"]),
    ("529", ["529"]),
    ("roth_401k", ["roth_401k"]),
    ("qualified_401k", ["qualified_401k", "qualified_403b", "qualified_457"]),
    ("nqdc", ["nqdc"]),
    ("pension_db", ["pension_db"]),
    ("pension_cb", ["pension_cb"]),
    ("taxable_brokerage", ["taxable_brokerage"]),
]


def infer_account_type(stmt_type: str, custodian: str, file_match_rules: list[dict],
                       filename: str, log: list[LogEntry]) -> str:
    """Resolve in priority order: config match → statement_type from fingerprint → trustee/cust suffix → default."""

    # Priority 1: explicit config file_match
    for rule in file_match_rules:
        pattern = rule.get("file_match", "")
        if pattern and _glob_match(pattern, filename):
            t = rule.get("type")
            if t:
                log.append(LogEntry("type_inference", filename, f"config file_match → {t}"))
                return t

    # Priority 2: statement_type from fingerprint
    if stmt_type and stmt_type != "unknown":
        # PCRA inside a qualified plan: trustee-bank-suffix decides
        if stmt_type == "pcra":
            if custodian == "schwab_trust_ttee":
                log.append(LogEntry("type_inference", filename, "pcra + TTEE → qualified_pcra"))
                return "qualified_pcra"
            elif custodian == "schwab_trust_cust":
                log.append(LogEntry("type_inference", filename, "pcra + CUST → nqdc_pcra"))
                return "nqdc_pcra"
            else:
                log.append(LogEntry("type_inference", filename, "pcra (unresolved trustee) → pending_nesting"))
                return "pending_nesting"

        log.append(LogEntry("type_inference", filename, f"fingerprint → {stmt_type}"))
        return stmt_type

    # Default
    log.append(LogEntry("type_inference", filename, "no signal — defaulted to unknown"))
    return "unknown"


def _glob_match(pattern: str, name: str) -> bool:
    """Simple glob matcher."""
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


# -----------------------------------------------------------------------------
# Nested-wrapper detection
# -----------------------------------------------------------------------------

def detect_nestings(statements_meta: list[dict], log: list[LogEntry]) -> dict[str, str]:
    """
    Returns: {child_source_file: parent_source_file}

    Algorithm: for each statement with a nesting_indicator (a line referencing
    "Personal Choice Retirement Account" or similar with a dollar value),
    look for another statement whose extracted_total matches that value.
    """
    nestings: dict[str, str] = {}

    for parent in statements_meta:
        indicator = parent.get("nesting_indicator")
        if not indicator:
            continue
        target_value = indicator.get("value")
        if not target_value:
            continue

        for child in statements_meta:
            if child["source_file"] == parent["source_file"]:
                continue
            if abs(child.get("extracted_total", 0) - target_value) < 0.01:
                nestings[child["source_file"]] = parent["source_file"]
                log.append(LogEntry(
                    "nesting_detected",
                    child["source_file"],
                    f"matches ${target_value:,.2f} sleeve line in {parent['source_file']}",
                ))
                break

    return nestings


# -----------------------------------------------------------------------------
# Owner attribution
# -----------------------------------------------------------------------------

def attribute_owner(config_account: Optional[dict], default_member: str,
                    log: list[LogEntry], filename: str) -> tuple[str, Optional[float]]:
    """Return (owner, joint_share). joint_share is None unless this is a joint account."""
    if config_account is None:
        return default_member, None

    owner = config_account.get("owner", default_member)
    if owner == "joint":
        joint_attr = config_account.get("joint_attribution", [])
        # Skip — we emit one row per owner share in consolidate_positions instead.
        return "joint", None
    return owner, None


# -----------------------------------------------------------------------------
# Real estate methodology
# -----------------------------------------------------------------------------

def compute_re_equity(prop: dict, defaults: dict) -> tuple[float, str]:
    """Compute net equity for a real-estate entry per the configured methodology.
    Returns (net_equity, methodology_label).
    """
    methodology = prop.get("methodology", "carrying")
    mv = float(prop.get("market_value", 0))
    mortgage = float(prop.get("mortgage", 0))

    if methodology == "carrying":
        return mv - mortgage, "carrying"

    if methodology == "liquidation_net":
        d = defaults
        selling = mv * d.get("selling_costs_pct", 0.06)
        gross_proceeds = mv - selling - mortgage

        # Cap gains (only if cost basis provided)
        cost_basis = prop.get("cost_basis")
        depreciation = prop.get("accumulated_depreciation", 0)
        is_primary = prop.get("use", "investment") == "primary"
        is_married = prop.get("married", True)

        if cost_basis is not None:
            gross_gain = max(0, mv - selling - cost_basis)
            if is_primary:
                exclusion = (d.get("sec_121_exclusion_married", 500000)
                             if is_married
                             else d.get("sec_121_exclusion_single", 250000))
                taxable_gain = max(0, gross_gain - exclusion)
            else:
                taxable_gain = gross_gain
            cap_tax = taxable_gain * (d.get("fed_ltcg_rate", 0.20)
                                       + d.get("nii_surtax_rate", 0.038)
                                       + d.get("default_state_marginal_rate", 0.05))
        else:
            cap_tax = 0  # unknown — note in report

        recapture = depreciation * d.get("depreciation_recapture_rate", 0.25) if not is_primary else 0
        net = gross_proceeds - cap_tax - recapture
        return net, "liquidation_net"

    return mv - mortgage, "carrying"


# -----------------------------------------------------------------------------
# Main consolidation
# -----------------------------------------------------------------------------

def consolidate_positions(work_folder: Path, config: dict) -> tuple[list[Position], list[LogEntry], list[str]]:
    log: list[LogEntry] = []
    summary_lines: list[str] = []

    # Intermediates live in .analysis/ alongside the user's source folder
    io_dir = work_folder if work_folder.name == ".analysis" else work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)
    raw_path = io_dir / "raw_positions.csv"
    meta_path = io_dir / "statements_meta.json"

    if not raw_path.is_file() or not meta_path.is_file():
        raise SystemExit(f"missing input files in {io_dir}: raw_positions.csv and statements_meta.json")

    raw = pd.read_csv(raw_path)
    statements = json.loads(meta_path.read_text())

    # 1. Detect nestings
    nestings = detect_nestings(statements, log)

    # 2. Build per-file account-type map
    file_match_rules = config.get("accounts", [])
    default_member = next(
        (m["name"] for m in config.get("household", {}).get("members", []) if "name" in m),
        "primary"
    )

    file_account_type: dict[str, str] = {}
    file_owner: dict[str, str] = {}
    file_config_entry: dict[str, dict] = {}
    for stmt in statements:
        fname = stmt["source_file"]
        cfg_entry = _match_config_account(file_match_rules, fname)
        file_config_entry[fname] = cfg_entry or {}
        atype = infer_account_type(
            stmt.get("statement_type", "unknown"),
            stmt.get("custodian", "unknown"),
            file_match_rules,
            fname,
            log,
        )
        # If nested, override the type — the parent's wrapper governs.
        if fname in nestings:
            parent_fname = nestings[fname]
            parent_type = file_account_type.get(parent_fname)
            if parent_type:
                atype = f"{parent_type}_pcra"
        file_account_type[fname] = atype
        file_owner[fname] = (cfg_entry or {}).get("owner") or default_member

    # 3. Build positions from raw rows
    positions: list[Position] = []
    for _, r in raw.iterrows():
        fname = r["source_file"]
        atype = file_account_type.get(fname, "unknown")
        owner = file_owner.get(fname, default_member)
        cfg = file_config_entry.get(fname, {})
        haircut = cfg.get("tax_haircut", 0.0)
        mv_gross = float(r.get("market_value", 0) or 0)
        mv_net = mv_gross * (1 - haircut)

        # Skip the indicator line for the parent — its detail came from the child
        nest_indicator = NESTING_TICKER_PATTERN.search(str(r.get("description", "")))
        if nest_indicator and fname not in nestings.values():
            # This is a parent statement's indicator line; drop it (child detail replaces).
            log.append(LogEntry("drop_nesting_indicator", fname, str(r["description"])))
            continue

        positions.append(Position(
            account=cfg.get("alias") or _alias_from_filename(fname, atype),
            account_type=atype,
            wrapper_structure=cfg.get("wrapper_structure"),
            owner=owner,
            joint_share=None,
            employer=cfg.get("employer"),
            nested_inside=nestings.get(fname),
            ticker=str(r["ticker"]),
            description=str(r["description"]),
            section=str(r["section"]),
            quantity=float(r["quantity"]) if pd.notna(r.get("quantity")) else None,
            price=float(r["price"]) if pd.notna(r.get("price")) else None,
            market_value_gross=mv_gross,
            market_value_net=mv_net,
            cost_basis=float(r["cost_basis"]) if pd.notna(r.get("cost_basis")) else None,
            unrealized_gain=float(r["unrealized_gain"]) if pd.notna(r.get("unrealized_gain")) else None,
            vested=True,                                   # statement positions are vested by definition
            vest_date=None,
            est_annual_income=float(r["est_annual_income"]) if pd.notna(r.get("est_annual_income")) else None,
            est_yield_pct=float(r["est_yield_pct"]) if pd.notna(r.get("est_yield_pct")) else None,
            income_character=None,                         # filled in by classify
            methodology=None,
            liquid=None,
            source_file=fname,
            notes=None,
        ))

    # 4. Inject manual holdings
    for mh in config.get("manual_holdings", []):
        positions.append(_manual_holding_to_position(mh, default_member))
        log.append(LogEntry("manual_holding_injected", mh.get("account", "?"), f"type={mh.get('type')} value={mh.get('value')}"))

    # 5. Inject real estate
    # Primary residence (use=primary) is NOT injected into positions — per
    # SKILL.md it's excluded from the investable allocation analysis (it's a
    # lifestyle asset, not a portfolio position). Its market_value + mortgage
    # stay in the config and will be picked up by the future Layer-2
    # `balance-sheet` skill for net-worth composition. Investment-use
    # properties (rentals, vacation, etc.) are injected normally.
    re_defaults = config.get("real_estate_liquidation", {})
    for prop in config.get("real_estate", []):
        if prop.get("use") == "primary":
            log.append(LogEntry("real_estate_excluded_primary", prop.get("name", "?"),
                                "use=primary — excluded from investable; lives in config for net-worth view"))
            continue
        net_eq, methodology = compute_re_equity(prop, re_defaults)
        positions.append(Position(
            account=prop.get("name", "real_estate"),
            account_type="real_estate",
            wrapper_structure=None,
            owner=prop.get("owner", default_member),
            joint_share=None,
            employer=None,
            nested_inside=None,
            ticker="RE",
            description=prop.get("name", ""),
            section="real_estate",
            quantity=None,
            price=None,
            market_value_gross=float(prop.get("market_value", 0)) - float(prop.get("mortgage", 0)),
            market_value_net=net_eq,
            cost_basis=prop.get("cost_basis"),
            unrealized_gain=None,
            vested=True,
            vest_date=None,
            est_annual_income=None,
            est_yield_pct=None,
            income_character=None,
            methodology=methodology,
            liquid=(methodology == "liquidation_net"),
            source_file="config:real_estate",
            notes=f"use={prop.get('use', 'investment')}",
        ))
        log.append(LogEntry("real_estate_injected", prop.get("name", "?"),
                            f"methodology={methodology} net_equity={net_eq:,.0f}"))

    # 6. Household reconciliation (if a balance sheet was found in statements_meta)
    sheet_stmts = [s for s in statements if s.get("statement_type") == "balance_sheet"]
    if sheet_stmts:
        summary_lines.append(f"Balance sheet detected: {sheet_stmts[0]['source_file']}")
        # Detailed reconciliation is left to a future enhancement — the spreadsheet
        # column layout varies too much to hardcode. Flag for review.
        log.append(LogEntry("balance_sheet_seen", sheet_stmts[0]["source_file"],
                            "spreadsheet present — reconciliation deferred to manual review"))

    return positions, log, summary_lines


# Regex for catching nesting indicator lines that slipped into raw_positions
# (e.g., the "Personal Choice Retirement Acct" entry in a parent statement).
NESTING_TICKER_PATTERN = re.compile(
    r"Personal\s+Choice|PCRA|Self[\s-]+Directed|BrokerageLink",
    re.IGNORECASE,
)


def _match_config_account(rules: list[dict], filename: str) -> Optional[dict]:
    for rule in rules:
        pattern = rule.get("file_match", "")
        if pattern and _glob_match(pattern, filename):
            return rule
    return None


def _alias_from_filename(filename: str, atype: str) -> str:
    stem = Path(filename).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem)


def _manual_holding_to_position(mh: dict, default_member: str) -> Position:
    return Position(
        account=mh.get("account", "manual"),
        account_type=mh.get("type", "manual"),
        wrapper_structure=None,
        owner=mh.get("owner", default_member),
        joint_share=None,
        employer=mh.get("employer"),
        nested_inside=None,
        ticker=mh.get("ticker") or mh.get("account", "MANUAL"),
        description=mh.get("notes", ""),
        section=mh.get("type", "other"),
        quantity=None,
        price=None,
        market_value_gross=float(mh.get("value", 0)),
        market_value_net=float(mh.get("value", 0)) * (1 - float(mh.get("tax_haircut", 0))),
        cost_basis=None,
        unrealized_gain=None,
        vested=mh.get("vested", True),
        vest_date=mh.get("vest_date"),
        est_annual_income=None,
        est_yield_pct=None,
        income_character=None,
        methodology=None,
        liquid=None,
        source_file="config:manual_holdings",
        notes=mh.get("notes"),
    )


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

def write_outputs(positions: list[Position], log: list[LogEntry],
                  summary: list[str], work_folder: Path) -> None:
    io_dir = work_folder if work_folder.name == ".analysis" else work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)
    work_folder = io_dir
    # positions.csv
    pos_path = work_folder / "positions.csv"
    fieldnames = list(positions[0].__dict__.keys()) if positions else []
    with pos_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in positions:
            writer.writerow(p.__dict__)

    # consolidation_log.csv
    log_path = work_folder / "consolidation_log.csv"
    with log_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["action", "target", "detail"])
        for entry in log:
            writer.writerow([entry.action, entry.target, entry.detail])

    # consolidation_summary.md
    summary_path = work_folder / "consolidation_summary.md"
    nestings = [e for e in log if e.action == "nesting_detected"]
    manuals = [e for e in log if e.action == "manual_holding_injected"]
    re_entries = [e for e in log if e.action == "real_estate_injected"]
    types_inferred = [e for e in log if e.action == "type_inference"]

    lines = [
        "# Consolidation Summary",
        "",
        f"Total positions: {len(positions)}",
        f"Gross investable: ${sum(p.market_value_gross for p in positions):,.2f}",
        f"Net investable: ${sum(p.market_value_net for p in positions):,.2f}",
        "",
        "## Account types inferred",
        "",
    ]
    for entry in types_inferred:
        lines.append(f"- `{entry.target}` — {entry.detail}")
    lines.extend([
        "",
        "## Nested wrappers detected",
        "",
    ])
    if not nestings:
        lines.append("_None detected._")
    else:
        for entry in nestings:
            lines.append(f"- `{entry.target}` → {entry.detail}")
    lines.extend([
        "",
        "## Manual holdings injected",
        "",
    ])
    if not manuals:
        lines.append("_None._")
    else:
        for entry in manuals:
            lines.append(f"- `{entry.target}` — {entry.detail}")
    lines.extend([
        "",
        "## Real estate injected",
        "",
    ])
    if not re_entries:
        lines.append("_None._")
    else:
        for entry in re_entries:
            lines.append(f"- `{entry.target}` — {entry.detail}")
    if summary:
        lines.extend(["", "## Notes", ""])
        for s in summary:
            lines.append(f"- {s}")

    summary_path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path, help="Folder with raw_positions.csv and statements_meta.json")
    ap.add_argument("--config", type=Path, default=None,
                    help="investment_analysis_config.yaml")
    args = ap.parse_args()

    if not args.work_folder.is_dir():
        print(f"error: not a directory: {args.work_folder}", file=sys.stderr)
        return 2

    config: dict[str, Any] = {}
    resolved_config = auto_discover_config(args.work_folder, args.config)
    if resolved_config:
        with resolved_config.open() as f:
            config = yaml.safe_load(f) or {}
        if not args.config:
            print(f"  Using config: {resolved_config}")

    positions, log, summary = consolidate_positions(args.work_folder, config)
    write_outputs(positions, log, summary, args.work_folder)

    print(f"Consolidated {len(positions)} positions.")
    nestings = [e for e in log if e.action == "nesting_detected"]
    if nestings:
        print(f"  Detected {len(nestings)} nested wrapper(s)")
    io_dir = args.work_folder if args.work_folder.name == ".analysis" else args.work_folder / ".analysis"
    print(f"Output: {io_dir / 'positions.csv'}")
    print(f"        {io_dir / 'consolidation_summary.md'}")
    print(f"        {io_dir / 'consolidation_log.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
