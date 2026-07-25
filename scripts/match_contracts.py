#!/usr/bin/env python3
"""Match THL players to historical NHL contracts.

The output keeps two contract views separate:
- thl_*: contract covering the configured reference NHL season.
- next_*: later contract beginning after the reference season.
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


def select_contracts(group: pd.DataFrame, settings: Settings) -> dict[str, object]:
    reference = group[
        (group["startSeasonId"] <= settings.reference_season_id)
        & (group["endSeasonId"] >= settings.reference_season_id)
    ].sort_values(["startSeasonId", "endSeasonId"], ascending=[False, False])

    future = group[group["startSeasonId"] > settings.reference_season_id].sort_values(
        ["startSeasonId", "endSeasonId"]
    )

    result: dict[str, object] = {}
    if reference.empty:
        result.update(
            {
                "thl_contract_status": "standardkontrakt",
                "thl_salary": settings.league_minimum,
                "thl_contract_years": 1,
                "thl_contract_start": "",
                "thl_contract_end": "",
            }
        )
    else:
        row = reference.iloc[0]
        years_left = int(row["endSeasonId"] // 10000 - settings.reference_season_id // 10000 + 1)
        result.update(
            {
                "thl_contract_status": "matchat",
                "thl_salary": row.get("contractAAV", pd.NA),
                "thl_contract_years": min(max(years_left, 1), 8),
                "thl_contract_start": row.get("startSeasonId", pd.NA),
                "thl_contract_end": row.get("endSeasonId", pd.NA),
            }
        )

    if future.empty:
        result.update(
            {
                "has_new_contract": False,
                "next_contract_salary": pd.NA,
                "next_contract_years": pd.NA,
                "next_contract_start": pd.NA,
                "next_contract_end": pd.NA,
            }
        )
    else:
        row = future.iloc[0]
        result.update(
            {
                "has_new_contract": True,
                "next_contract_salary": row.get("contractAAV", pd.NA),
                "next_contract_years": row.get("contractYears", pd.NA),
                "next_contract_start": row.get("startSeasonId", pd.NA),
                "next_contract_end": row.get("endSeasonId", pd.NA),
            }
        )
    return result


def match_players(players: pd.DataFrame, contracts: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    contracts = contracts.copy()
    contracts["normalized_name"] = contracts["playerFullName"].map(normalize_name)
    contracts["normalized_position"] = contracts["positionCode"].map(normalize_position)

    candidates_by_position = {
        position: sorted(group["normalized_name"].dropna().unique())
        for position, group in contracts.groupby("normalized_position")
    }

    matched_rows: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []

    for player in players.to_dict("records"):
        key = normalize_name(player["player_name"])
        position = normalize_position(player["position"])
        exact = contracts[
            (contracts["normalized_name"] == key)
            & (contracts["normalized_position"] == position)
        ]
        score = 100.0

        if exact.empty:
            choices = candidates_by_position.get(position, [])
            fuzzy = process.extractOne(key, choices, scorer=fuzz.ratio) if choices else None
            if fuzzy is None:
                review_rows.append({**player, "reason": "inga kandidater", "match_score": 0})
                continue
            matched_key, score, _ = fuzzy
            exact = contracts[
                (contracts["normalized_name"] == matched_key)
                & (contracts["normalized_position"] == position)
            ]

        if exact.empty or score < settings.threshold * 100:
            review_rows.append({**player, "reason": "osäker namnmatchning", "match_score": score})
            continue

        contract_data = select_contracts(exact, settings)
        matched_rows.append(
            {
                **player,
                "matched_name": exact.iloc[0]["playerFullName"],
                "match_score": round(score, 1),
                **contract_data,
                "data_source": "nhlscraper",
            }
        )

    return pd.DataFrame(matched_rows), pd.DataFrame(review_rows)


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
        threshold=float(config["name_match_threshold"]),
    )

    skaters = read_thl_players(Path(config["input"]["skaters_csv"]), "skater")
    goalies = read_thl_players(Path(config["input"]["goalies_csv"]), "goalie")
    players = pd.concat([skaters, goalies], ignore_index=True)
    contracts = pd.read_csv(config["input"]["contracts_csv"])

    matched, review = match_players(players, contracts, settings)

    output_path = Path(config["output"]["matched_contracts_csv"])
    review_path = Path(config["output"]["unmatched_players_csv"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    matched.to_csv(output_path, index=False)
    review.to_csv(review_path, index=False)

    print(f"Matchade: {len(matched)}")
    print(f"Behöver granskas: {len(review)}")
    print(f"Export: {output_path}")


if __name__ == "__main__":
    main()
