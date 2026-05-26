"""
Shared helper: locate `investment_analysis_config.yaml` for a pipeline script.

All pipeline scripts (`extract_positions`, `consolidate`, `classify_funds`,
`analyze`, `generate_charts`, `generate_report`) call `auto_discover_config`
in their `main()` so the user can omit `--config` and have the config
auto-resolved from the work folder.

This matches the invariant in `SKILL.md`: the config is a *deliverable* that
lives at the root of the user's source folder. Scripts should find it
automatically — otherwise running a script without `--config` silently
produces analysis with zero manual holdings and zero real estate (looks
complete, is actually wrong; the exact failure mode SKILL.md warns about).
"""

from __future__ import annotations

from pathlib import Path


CONFIG_FILENAME = "investment_analysis_config.yaml"


def auto_discover_config(work_folder: Path, explicit: Path | None) -> Path | None:
    """Return a config path, preferring `explicit` over auto-discovery.

    Resolution order:
      1. `explicit` if it's a real file.
      2. `<user_folder>/investment_analysis_config.yaml` where `user_folder`
         is the parent of `.analysis/` if the work_folder *is* `.analysis/`,
         otherwise the work_folder itself.
      3. None — caller treats as "no config; defaults apply."
    """
    if explicit and explicit.is_file():
        return explicit
    user_folder = work_folder if work_folder.name != ".analysis" else work_folder.parent
    guess = user_folder / CONFIG_FILENAME
    return guess if guess.is_file() else None
