#!/usr/bin/env python3
"""Match every THL player to historical NHL contracts.

The output always contains one row per THL player and keeps two contract views
separate:
- thl_*: contract covering the configured reference NHL season.
- next_*: later contract beginning in the configured next NHL season or later.

Unmatched and ambiguous players receive a clearly marked one-year THL fallback
contract at league minimum and are also written to review reports.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process


@dataclass(frozen=True)
class Settings:
    reference_season_id: int
    next_season_id: int
    league_minimum: int
    max_contract_years: int
    threshold: float


def season_to_id(season: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{4})", season.strip())
    if not match:
        raise ValueError(f"Ogiltigt säsongsformat: {season!r}")
    start, end = map(int, match.groups())
    if end != start + 1:
        raise ValueError(f"Säsongen måste vara två sammanhängande år: {season!r}")
    return start * 10000 + end


def normalize_name(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_position(value: object) -> str:
    position = "" if pd.isna(value) else str(value).strip().upper()
    return {"L": "LW", "R": "RW", "G": "G"}.get(position, position)


def read_thl_players(path: Path, player_type: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    name_column = "Goalie Name" if player_type == "goalie" else "Player Name"
    if name_column not in frame.columns:
        raise ValueError(f"{path} saknar kolumnen {name_column!r}")

    if player_type == "goalie":
        positions = pd.Series("G", index=frame.index)
    elif "Position" in frame.columns:
        positions = frame["Position"].map(normalize_position)
    else:
        position_columns = [column for column in ("C", "L", "R", "D") if column in frame.columns]
        if not position_columns:
            raise ValueError(f"{path} saknar positionsinformation")

        def resolve_position(row: pd.Series) -> str:
            for column in position_columns:
                if str(row[column]).strip().upper() == "X":
                    return normalize_position(column)
            return ""

        positions = frame.apply(resolve_position, axis=1)

    return pd.DataFrame(
        {
            "player_name": frame[name_column].astype(str).str.strip(),
            "position": positions,
            "player_type": player_type,
            "source_row": frame.index + 2,
        }
    )


def prepare_contracts(contracts: pd.DataFrame) -> pd.DataFrame:
    required = {
        "playerFullName",
        "positionCode",
        "startSeasonId",
        "endSeasonId",
        "contractYears",
        "contractAAV",
    }
    missing = sorted(required - set(contracts.columns))
    if missing:
        raise ValueError(f"Kontraktsfilen saknar kolumner: {', '.join(missing)}")

    prepared = contracts.copy()
    numeric_columns = [
        "playerId",
        "startSeasonId",
        "endSeasonId",
        "contractYears",
        "contractAAV",
        "contractValue",
        "signingBonus",
    ]
    for column in numeric_columns:
        if column not in prepared.columns:
            prepared[column] = pd.NA
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.dropna(
        subset=["playerFullName", "positionCode", "startSeasonId", "endSeasonId"]
    )
    prepared["startSeasonId"] = prepared["startSeasonId"].astype(int)
    prepared["endSeasonId"] = prepared["endSeasonId"].astype(int)
    prepared["normalized_name"] = prepared["playerFullName"].map(normalize_name)
    prepared["normalized_position"] = prepared["positionCode"].map(normalize_position)
    return prepared


def empty_future_contract() -> dict[str, object]:
    return {
        "has_new_contract": False,
        "next_contract_salary": pd.NA,
        "next_contract_years": pd.NA,
        "next_contract_start": pd.NA,
        "next_contract_end": pd.NA,
        "next_contract_value": pd.NA,
        "next_signing_bonus": pd.NA,
    }


def fallback_contract(settings: Settings, status: str) -> dict[str, object]:
    return {
        "thl_contract_status": status,
        "thl_salary": settings.league_minimum,
        "thl_contract_years": 1,
        "thl_contract_start": pd.NA,
        "thl_contract_end": pd.NA,
        "thl_contract_value": settings.league_minimum,
        "thl_signing_bonus": pd.NA,
        **empty_future_contract(),
    }


def select_contracts(group: pd.DataFrame, settings: Settings) -> dict[str, object]:
    reference = group[
        (group["startSeasonId"] <= settings.reference_season_id)
        & (group["endSeasonId"] >= settings.reference_season_id)
    ].sort_values(["startSeasonId", "endSeasonId"], ascending=[False, False])

    future = group[group["startSeasonId"] >= settings.next_season_id].sort_values(
        ["startSeasonId", "endSeasonId"]
    )

    if reference.empty:
        result = fallback_contract(settings, "standardkontrakt")
    else:
        row = reference.iloc[0]
        years_left = int(
            row["endSeasonId"] // 10000
            - settings.reference_season_id // 10000
            + 1
        )
        result = {
            "thl_contract_status": "matchat",
            "thl_salary": row.get("contractAAV", pd.NA),
            "thl_contract_years": min(
                max(years_left, 1), settings.max_contract_years
            ),
            "thl_contract_start": row.get("startSeasonId", pd.NA),
            "thl_contract_end": row.get("endSeasonId", pd.NA),
            "thl_contract_value": row.get("contractValue", pd.NA),
            "thl_signing_bonus": row.get("signingBonus", pd.NA),
            **empty_future_contract(),
        }

    if not future.empty:
        row = future.iloc[0]
        result.update(
            {
                "has_new_contract": True,
                "next_contract_salary": row.get("contractAAV", pd.NA),
                "next_contract_years": row.get("contractYears", pd.NA),
                "next_contract_start": row.get("startSeasonId", pd.NA),
                "next_contract_end": row.get("endSeasonId", pd.NA),
                "next_contract_value": row.get("contractValue", pd.NA),
                "next_signing_bonus": row.get("signingBonus", pd.NA),
            }
        )
    return result


def fallback_output_row(
    player: dict[str, object],
    settings: Settings,
    match_status: str,
    score: float,
    suggested_name: str = "",
) -> dict[str, object]:
    return {
        **player,
        "player_id": pd.NA,
        "matched_name": suggested_name,
        "match_status": match_status,
        "match_method": "fallback",
        "match_score": round(score, 1),
        **fallback_contract(settings, f"standardkontrakt_{match_status}"),
        "data_source": "THL fallback",
    }


def match_players(
    players: pd.DataFrame, contracts: pd.DataFrame, settings: Settings
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates_by_position = {
        position: sorted(group["normalized_name"].dropna().unique())
        for position, group in contracts.groupby("normalized_position")
    }

    output_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []
    ambiguous_rows: list[dict[str, object]] = []

    for player in players.to_dict("records"):
        key = normalize_name(player["player_name"])
        position = normalize_position(player["position"])
        candidate_rows = contracts[
            (contracts["normalized_name"] == key)
            & (contracts["normalized_position"] == position)
        ]
        score = 100.0
        method = "exact"
        suggested_name = ""

        if candidate_rows.empty:
            choices = candidates_by_position.get(position, [])
            fuzzy = process.extractOne(key, choices, scorer=fuzz.ratio) if choices else None
            if fuzzy is None:
                report = {
                    **player,
                    "reason": "inga kandidater för positionen",
                    "suggested_name": "",
                    "match_score": 0.0,
                }
                unmatched_rows.append(report)
                output_rows.append(
                    fallback_output_row(player, settings, "unmatched", 0.0)
                )
                continue

            matched_key, score, _ = fuzzy
            candidate_rows = contracts[
                (contracts["normalized_name"] == matched_key)
                & (contracts["normalized_position"] == position)
            ]
            suggested_name = str(candidate_rows.iloc[0]["playerFullName"])
            method = "fuzzy"

        unique_player_ids = candidate_rows["playerId"].dropna().unique()
        duplicate_identity = len(unique_player_ids) > 1
        if candidate_rows.empty or score < settings.threshold * 100 or duplicate_identity:
            reason = (
                "flera NHL-ID för samma namn och position"
                if duplicate_identity
                else "osäker namnmatchning"
            )
            report = {
                **player,
                "reason": reason,
                "suggested_name": suggested_name,
                "match_score": round(score, 1),
            }
            ambiguous_rows.append(report)
            output_rows.append(
                fallback_output_row(
                    player,
                    settings,
                    "ambiguous",
                    score,
                    suggested_name,
                )
            )
            continue

        contract_data = select_contracts(candidate_rows, settings)
        first = candidate_rows.iloc[0]
        player_id = first.get("playerId", pd.NA)
        if pd.notna(player_id):
            player_id = int(player_id)

        output_rows.append(
            {
                **player,
                "player_id": player_id,
                "matched_name": first["playerFullName"],
                "match_status": "matched",
                "match_method": method,
                "match_score": round(score, 1),
                **contract_data,
                "data_source": (
                    "nhlscraper"
                    if contract_data["thl_contract_status"] == "matchat"
                    else "nhlscraper + THL fallback"
                ),
            }
        )

    return (
        pd.DataFrame(output_rows),
        pd.DataFrame(unmatched_rows),
        pd.DataFrame(ambiguous_rows),
    )


def write_report(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "player_name",
        "position",
        "player_type",
        "source_row",
        "reason",
        "suggested_name",
        "match_score",
    ]
    if frame.empty:
        frame = pd.DataFrame(columns=columns)
    else:
        frame = frame.reindex(columns=columns)
    frame.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = Settings(
        reference_season_id=season_to_id(config["reference_nhl_season"]),
        next_season_id=season_to_id(config["next_nhl_season"]),
        league_minimum=int(config["league_minimum"]),
        max_contract_years=int(config["max_contract_years"]),
        threshold=float(config["name_match_threshold"]),
    )

    skaters = read_thl_players(Path(config["input"]["skaters_csv"]), "skater")
    goalies = read_thl_players(Path(config["input"]["goalies_csv"]), "goalie")
    players = pd.concat([skaters, goalies], ignore_index=True)
    contracts = prepare_contracts(pd.read_csv(config["input"]["contracts_csv"]))

    output, unmatched, ambiguous = match_players(players, contracts, settings)
    if len(output) != len(players):
        raise RuntimeError(
            f"Exporten innehåller {len(output)} rader men rosterfilerna innehåller "
            f"{len(players)} spelare."
        )

    output_path = Path(config["output"]["matched_contracts_csv"])
    unmatched_path = Path(config["output"]["unmatched_players_csv"])
    ambiguous_path = Path(config["output"]["ambiguous_matches_csv"])
    summary_path = Path("reports/match_summary.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    write_report(unmatched, unmatched_path)
    write_report(ambiguous, ambiguous_path)

    summary = {
        "thl_season": config["thl_season"],
        "reference_nhl_season": config["reference_nhl_season"],
        "next_nhl_season": config["next_nhl_season"],
        "players_total": int(len(players)),
        "skaters_total": int(len(skaters)),
        "goalies_total": int(len(goalies)),
        "matched_total": int((output["match_status"] == "matched").sum()),
        "unmatched_total": int(len(unmatched)),
        "ambiguous_total": int(len(ambiguous)),
        "standard_contract_total": int(
            output["thl_contract_status"].astype(str).str.startswith("standardkontrakt").sum()
        ),
        "players_with_new_contract": int(output["has_new_contract"].fillna(False).sum()),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Export: {output_path}")
    print(f"Omatchade: {unmatched_path}")
    print(f"Osäkra: {ambiguous_path}")


if __name__ == "__main__":
    main()
