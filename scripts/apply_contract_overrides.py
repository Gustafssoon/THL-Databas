#!/usr/bin/env python3
"""Apply reviewed manual corrections to the generated THL contract export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


NEXT_FIELDS = [
    "next_contract_salary",
    "next_contract_years",
    "next_contract_start",
    "next_contract_end",
    "next_contract_value",
    "next_signing_bonus",
]


def apply_fallback(row: pd.Series, override: dict[str, object]) -> pd.Series:
    salary = int(override.get("salary") or 775000)
    years = int(override.get("years") or 1)

    row["player_id"] = pd.NA
    row["matched_name"] = ""
    row["match_status"] = "manual_fallback"
    row["match_method"] = "manual_override"
    row["registry_match_method"] = "manual_override"
    row["match_score"] = 0.0
    row["thl_contract_status"] = "standardkontrakt_manual_override"
    row["thl_salary"] = salary
    row["thl_contract_years"] = years
    row["thl_contract_start"] = pd.NA
    row["thl_contract_end"] = pd.NA
    row["thl_contract_value"] = salary * years
    row["thl_signing_bonus"] = pd.NA
    row["has_new_contract"] = False
    for field in NEXT_FIELDS:
        row[field] = pd.NA
    row["data_source"] = "THL manual override"
    return row


def update_summary(output: pd.DataFrame, summary_path: Path, applied: int) -> None:
    summary = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    summary.update(
        {
            "matched_total": int((output["match_status"] == "matched").sum()),
            "real_reference_contract_total": int(
                (output["thl_contract_status"] == "matchat").sum()
            ),
            "standard_contract_total": int(
                output["thl_contract_status"]
                .astype(str)
                .str.startswith("standardkontrakt")
                .sum()
            ),
            "players_with_new_contract": int(
                output["has_new_contract"].fillna(False).sum()
            ),
            "manual_override_total": int(applied),
            "alias_matches_total": int((output["match_method"] == "alias").sum()),
            "fuzzy_matches_total": int((output["match_method"] == "fuzzy").sum()),
            "exact_matches_total": int((output["match_method"] == "exact").sum()),
        }
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", default="data/output/thl_contracts.csv")
    parser.add_argument(
        "--overrides", default="data/manual-overrides/contract_overrides.csv"
    )
    parser.add_argument("--summary", default="reports/match_summary.json")
    args = parser.parse_args()

    contracts_path = Path(args.contracts)
    overrides_path = Path(args.overrides)
    summary_path = Path(args.summary)

    output = pd.read_csv(contracts_path)
    if not overrides_path.exists():
        update_summary(output, summary_path, 0)
        return

    overrides = pd.read_csv(overrides_path).fillna("")
    required = {"thl_name", "action", "reason"}
    missing = required - set(overrides.columns)
    if missing:
        raise ValueError(f"Overridefilen saknar kolumner: {', '.join(sorted(missing))}")

    applied = 0
    for override in overrides.to_dict("records"):
        name = str(override["thl_name"]).strip()
        action = str(override["action"]).strip().lower()
        matches = output.index[output["player_name"].astype(str).str.strip() == name]
        if len(matches) != 1:
            raise ValueError(
                f"Override för {name!r} matchade {len(matches)} rader; förväntade exakt 1"
            )
        index = matches[0]
        if action == "fallback":
            output.loc[index] = apply_fallback(output.loc[index].copy(), override)
        else:
            raise ValueError(f"Okänd override-åtgärd för {name!r}: {action!r}")
        applied += 1

    output.to_csv(contracts_path, index=False)
    update_summary(output, summary_path, applied)
    print(f"Tillämpade {applied} manuella kontraktsöverskrivningar.")


if __name__ == "__main__":
    main()
