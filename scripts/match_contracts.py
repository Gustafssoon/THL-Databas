#!/usr/bin/env python3
"""Match every THL player to historical NHL contracts.

The matcher uses nhlscraper's unfiltered internal contract table so contract rows
are not discarded merely because nhlscraper could not resolve a player ID.
It keeps two contract views separate:
- thl_*: contract covering the configured reference NHL season.
- next_*: later contract beginning in the configured next NHL season or later.

Every THL player receives one output row. Unmatched or ambiguous identities get a
clearly marked one-year THL fallback contract and are written to review reports.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from rapidfuzz import fuzz


FORWARD_POSITIONS = {"C", "L", "LW", "R", "RW", "F"}


@dataclass(frozen=True)
class Settings:
    reference_season_id: int
    next_season_id: int
    league_minimum: int
    max_contract_years: int
    threshold: float
    roster_age_year: int
    age_tolerance: int


def season_to_id(season: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{4})", season.strip())
    if not match:
        raise ValueError(f"Ogiltigt säsongsformat: {season!r}")
    start, end = map(int, match.groups())
    if end != start + 1:
        raise ValueError(f"Säsongen måste vara två sammanhängande år: {season!r}")
    return start * 10000 + end


def clean_player_name(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return re.sub(r"\s*\(R\)\s*$", "", text, flags=re.IGNORECASE).strip()


def ascii_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    return "".join(char for char in text if not unicodedata.combining(char))


def normalize_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_text(clean_player_name(value)).lower())


def name_parts(value: object) -> tuple[str, str]:
    tokens = re.findall(r"[a-z0-9]+", ascii_text(clean_player_name(value)).lower())
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], tokens[0]
    return tokens[0], "".join(tokens[1:])


def safe_name_score(query: object, candidate: object) -> float:
    q_first, q_last = name_parts(query)
    c_first, c_last = name_parts(candidate)
    if not q_first or not c_first or not q_last or not c_last:
        return 0.0
    if q_first[0] != c_first[0]:
        return 0.0

    first_score = float(fuzz.ratio(q_first, c_first))
    last_score = float(fuzz.ratio(q_last, c_last))
    full_score = float(fuzz.ratio(normalize_name(query), normalize_name(candidate)))

    if last_score < 80.0 or first_score < 55.0:
        return 0.0
    return 0.65 * last_score + 0.25 * first_score + 0.10 * full_score


def normalize_position(value: object) -> str:
    position = "" if pd.isna(value) else str(value).strip().upper()
    return {"L": "LW", "R": "RW"}.get(position, position)


def position_group(value: object) -> str:
    position = normalize_position(value)
    if position == "G":
        return "G"
    if position == "D":
        return "D"
    if position in FORWARD_POSITIONS:
        return "F"
    return position


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

    ages = (
        pd.to_numeric(frame["Age"], errors="coerce")
        if "Age" in frame.columns
        else pd.Series(pd.NA, index=frame.index, dtype="Float64")
    )
    original_names = frame[name_column].astype(str).str.strip()
    lookup_names = original_names.map(clean_player_name)

    return pd.DataFrame(
        {
            "player_name": original_names,
            "lookup_name": lookup_names,
            "position": positions,
            "position_group": positions.map(position_group),
            "age": ages,
            "player_type": player_type,
            "source_row": frame.index + 2,
            "rookie_suffix_removed": original_names.ne(lookup_names),
        }
    )


def load_aliases(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    frame = pd.read_csv(path)
    required = {"thl_name", "contract_name"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Aliasfilen {path} måste innehålla kolumnerna thl_name och contract_name")
    aliases: dict[str, str] = {}
    for row in frame.to_dict("records"):
        key = normalize_name(row["thl_name"])
        target = clean_player_name(row["contract_name"])
        if key and target:
            aliases[key] = target
    return aliases


def prepare_contracts(contracts: pd.DataFrame, settings: Settings) -> pd.DataFrame:
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
        "ageAtSigning",
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
    prepared["position_group"] = prepared["positionCode"].map(position_group)
    prepared["start_year"] = prepared["startSeasonId"] // 10000
    prepared["estimated_birth_year"] = prepared["start_year"] - prepared["ageAtSigning"]
    prepared["estimated_age_at_roster"] = (
        prepared["ageAtSigning"] + settings.roster_age_year - prepared["start_year"]
    )
    return prepared


def prepare_registry(registry: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    required = {"playerId", "playerFullName", "positionCode"}
    missing = sorted(required - set(registry.columns))
    if missing:
        raise ValueError(f"Spelarregistret saknar kolumner: {', '.join(missing)}")

    prepared = registry.copy()
    prepared["playerId"] = pd.to_numeric(prepared["playerId"], errors="coerce")
    prepared = prepared.dropna(subset=["playerId", "playerFullName", "positionCode"])
    prepared["playerId"] = prepared["playerId"].astype(int)
    prepared["normalized_name"] = prepared["playerFullName"].map(normalize_name)
    prepared["position_group"] = prepared["positionCode"].map(position_group)
    if "birthDate" in prepared.columns:
        birth_year = pd.to_numeric(
            prepared["birthDate"].astype(str).str.slice(0, 4), errors="coerce"
        )
    else:
        birth_year = pd.Series(pd.NA, index=prepared.index, dtype="Float64")
    prepared["estimated_age_at_roster"] = settings.roster_age_year - birth_year
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
            "thl_contract_years": min(max(years_left, 1), settings.max_contract_years),
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


def count_age_clusters(values: Iterable[float], gap: int = 2) -> int:
    clean = sorted({int(round(float(value))) for value in values if pd.notna(value)})
    if not clean:
        return 1
    clusters = 1
    previous = clean[0]
    for value in clean[1:]:
        if value - previous > gap:
            clusters += 1
        previous = value
    return clusters


def narrow_by_age(rows: pd.DataFrame, player_age: object, tolerance: int) -> pd.DataFrame:
    if rows.empty or pd.isna(player_age) or "estimated_age_at_roster" not in rows.columns:
        return rows
    known = rows[rows["estimated_age_at_roster"].notna()].copy()
    if known.empty:
        return rows
    known["age_difference"] = (known["estimated_age_at_roster"] - float(player_age)).abs()
    close = known[known["age_difference"] <= tolerance]
    return close.drop(columns=["age_difference"]) if not close.empty else rows


def best_fuzzy_name(query: str, candidates: pd.DataFrame) -> tuple[str, float] | None:
    if candidates.empty:
        return None
    names = candidates[["normalized_name", "playerFullName"]].drop_duplicates()
    best_key = ""
    best_score = 0.0
    for row in names.to_dict("records"):
        score = safe_name_score(query, row["playerFullName"])
        if score > best_score:
            best_score = score
            best_key = str(row["normalized_name"])
    return (best_key, best_score) if best_key else None


def find_rows_for_player(
    player: dict[str, object],
    source: pd.DataFrame,
    settings: Settings,
    aliases: dict[str, str],
) -> tuple[pd.DataFrame, str, float, str]:
    lookup_name = str(player["lookup_name"])
    key = normalize_name(lookup_name)
    group = str(player["position_group"])
    scoped = source[source["position_group"] == group]

    rows = scoped[scoped["normalized_name"] == key]
    method = "exact"
    score = 100.0
    suggested_name = str(rows.iloc[0]["playerFullName"]) if not rows.empty else ""

    if rows.empty and key in aliases:
        alias_key = normalize_name(aliases[key])
        rows = scoped[scoped["normalized_name"] == alias_key]
        if not rows.empty:
            method = "alias"
            score = 100.0
            suggested_name = str(rows.iloc[0]["playerFullName"])

    if rows.empty:
        fuzzy = best_fuzzy_name(lookup_name, scoped)
        if fuzzy is None:
            return rows, "none", 0.0, ""
        fuzzy_key, score = fuzzy
        rows = scoped[scoped["normalized_name"] == fuzzy_key]
        method = "fuzzy"
        suggested_name = str(rows.iloc[0]["playerFullName"]) if not rows.empty else ""

    rows = narrow_by_age(rows, player.get("age"), settings.age_tolerance)
    return rows, method, score, suggested_name


def resolve_registry_id(
    player: dict[str, object],
    registry: pd.DataFrame,
    settings: Settings,
    aliases: dict[str, str],
) -> tuple[object, str]:
    rows, method, score, _ = find_rows_for_player(player, registry, settings, aliases)
    if rows.empty or score < settings.threshold * 100:
        return pd.NA, "unresolved"
    ids = rows["playerId"].dropna().astype(int).unique()
    if len(ids) != 1:
        return pd.NA, "ambiguous"
    return int(ids[0]), method


def fallback_output_row(
    player: dict[str, object],
    settings: Settings,
    match_status: str,
    score: float,
    suggested_name: str = "",
    match_method: str = "fallback",
) -> dict[str, object]:
    return {
        **player,
        "player_id": pd.NA,
        "matched_name": suggested_name,
        "match_status": match_status,
        "match_method": match_method,
        "match_score": round(score, 1),
        **fallback_contract(settings, f"standardkontrakt_{match_status}"),
        "data_source": "THL fallback",
    }


def match_players(
    players: pd.DataFrame,
    contracts: pd.DataFrame,
    registry: pd.DataFrame,
    settings: Settings,
    aliases: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    aliases = aliases or {}
    output_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []
    ambiguous_rows: list[dict[str, object]] = []

    for player in players.to_dict("records"):
        candidate_rows, method, score, suggested_name = find_rows_for_player(
            player, contracts, settings, aliases
        )

        if candidate_rows.empty:
            report = {
                **player,
                "reason": "inga kontraktskandidater för positionsgruppen",
                "suggested_name": "",
                "match_method": method,
                "match_score": 0.0,
            }
            unmatched_rows.append(report)
            output_rows.append(fallback_output_row(player, settings, "unmatched", 0.0))
            continue

        identity_clusters = count_age_clusters(candidate_rows["estimated_birth_year"])
        if score < settings.threshold * 100 or identity_clusters > 1:
            reason = (
                "flera möjliga identiteter efter ålderskontroll"
                if identity_clusters > 1
                else "osäker namnmatchning"
            )
            report = {
                **player,
                "reason": reason,
                "suggested_name": suggested_name,
                "match_method": method,
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
                    method,
                )
            )
            continue

        player_id, registry_method = resolve_registry_id(player, registry, settings, aliases)
        contract_data = select_contracts(candidate_rows, settings)
        first = candidate_rows.iloc[0]
        output_rows.append(
            {
                **player,
                "player_id": player_id,
                "matched_name": first["playerFullName"],
                "match_status": "matched",
                "match_method": method,
                "registry_match_method": registry_method,
                "match_score": round(score, 1),
                **contract_data,
                "data_source": (
                    "nhlscraper raw contracts"
                    if contract_data["thl_contract_status"] == "matchat"
                    else "nhlscraper raw contracts + THL fallback"
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
        "lookup_name",
        "position",
        "age",
        "player_type",
        "source_row",
        "reason",
        "suggested_name",
        "match_method",
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
        roster_age_year=int(config.get("roster_age_year", 2026)),
        age_tolerance=int(config.get("age_tolerance", 2)),
    )

    skaters = read_thl_players(Path(config["input"]["skaters_csv"]), "skater")
    goalies = read_thl_players(Path(config["input"]["goalies_csv"]), "goalie")
    players = pd.concat([skaters, goalies], ignore_index=True)
    contracts = prepare_contracts(
        pd.read_csv(config["input"]["contracts_csv"]), settings
    )
    registry = prepare_registry(
        pd.read_csv(config["input"]["players_csv"]), settings
    )
    aliases = load_aliases(Path(config["input"]["aliases_csv"]))

    output, unmatched, ambiguous = match_players(
        players, contracts, registry, settings, aliases
    )
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
        "real_reference_contract_total": int(
            (output["thl_contract_status"] == "matchat").sum()
        ),
        "unmatched_total": int(len(unmatched)),
        "ambiguous_total": int(len(ambiguous)),
        "standard_contract_total": int(
            output["thl_contract_status"].astype(str).str.startswith("standardkontrakt").sum()
        ),
        "players_with_new_contract": int(output["has_new_contract"].fillna(False).sum()),
        "rookie_suffix_removed_total": int(players["rookie_suffix_removed"].sum()),
        "alias_matches_total": int((output["match_method"] == "alias").sum()),
        "fuzzy_matches_total": int((output["match_method"] == "fuzzy").sum()),
        "exact_matches_total": int((output["match_method"] == "exact").sum()),
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
