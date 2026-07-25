from __future__ import annotations

import pandas as pd

from scripts.match_contracts import (
    Settings,
    clean_player_name,
    match_players,
    position_group,
    prepare_contracts,
    prepare_registry,
    safe_name_score,
    season_to_id,
    select_contracts,
)


def settings() -> Settings:
    return Settings(
        reference_season_id=20252026,
        next_season_id=20262027,
        league_minimum=775000,
        max_contract_years=8,
        threshold=0.88,
        roster_age_year=2026,
        age_tolerance=2,
    )


def contract_frame() -> pd.DataFrame:
    return prepare_contracts(
        pd.DataFrame(
            [
                {
                    "playerFullName": "Test Player",
                    "positionCode": "C",
                    "ageAtSigning": 28,
                    "startSeasonId": 20242025,
                    "endSeasonId": 20252026,
                    "contractYears": 2,
                    "contractAAV": 1000000,
                    "contractValue": 2000000,
                    "signingBonus": 0,
                },
                {
                    "playerFullName": "Test Player",
                    "positionCode": "R",
                    "ageAtSigning": 30,
                    "startSeasonId": 20262027,
                    "endSeasonId": 20282029,
                    "contractYears": 3,
                    "contractAAV": 3000000,
                    "contractValue": 9000000,
                    "signingBonus": 1000000,
                },
                {
                    "playerFullName": "Erik Gustafsson",
                    "positionCode": "D",
                    "ageAtSigning": 27,
                    "startSeasonId": 20192020,
                    "endSeasonId": 20252026,
                    "contractYears": 7,
                    "contractAAV": 2000000,
                    "contractValue": 14000000,
                    "signingBonus": 0,
                },
                {
                    "playerFullName": "Erik Gustafsson",
                    "positionCode": "D",
                    "ageAtSigning": 31,
                    "startSeasonId": 20192020,
                    "endSeasonId": 20252026,
                    "contractYears": 7,
                    "contractAAV": 4000000,
                    "contractValue": 28000000,
                    "signingBonus": 0,
                },
            ]
        ),
        settings(),
    )


def registry_frame() -> pd.DataFrame:
    return prepare_registry(
        pd.DataFrame(
            [
                {
                    "playerId": 1,
                    "playerFullName": "Test Player",
                    "positionCode": "C",
                    "birthDate": "1996-01-01",
                },
                {
                    "playerId": 2,
                    "playerFullName": "Erik Gustafsson",
                    "positionCode": "D",
                    "birthDate": "1992-03-14",
                },
                {
                    "playerId": 3,
                    "playerFullName": "Erik Gustafsson",
                    "positionCode": "D",
                    "birthDate": "1988-12-15",
                },
            ]
        ),
        settings(),
    )


def test_season_to_id() -> None:
    assert season_to_id("2025-2026") == 20252026


def test_rookie_suffix_and_forward_positions_are_normalized() -> None:
    assert clean_player_name("Leo Loof (R)") == "Leo Loof"
    assert position_group("C") == "F"
    assert position_group("RW") == "F"


def test_safe_fuzzy_matching_accepts_known_name_variant() -> None:
    assert safe_name_score("Alexander Ovechkin", "Alex Ovechkin") >= 88
    assert safe_name_score("Joey Anderson", "Josh Anderson") < 88


def test_selects_reference_and_new_contract_separately() -> None:
    rows = contract_frame()
    rows = rows[rows["normalized_name"] == "testplayer"]
    result = select_contracts(rows, settings())

    assert result["thl_salary"] == 1000000
    assert result["thl_contract_years"] == 1
    assert result["has_new_contract"] is True
    assert result["next_contract_salary"] == 3000000
    assert result["next_contract_start"] == 20262027


def test_age_disambiguates_same_name_and_every_player_gets_output() -> None:
    players = pd.DataFrame(
        [
            {
                "player_name": "Test Player",
                "lookup_name": "Test Player",
                "position": "LW",
                "position_group": "F",
                "age": 30,
                "player_type": "skater",
                "source_row": 2,
                "rookie_suffix_removed": False,
            },
            {
                "player_name": "Erik Gustafsson",
                "lookup_name": "Erik Gustafsson",
                "position": "D",
                "position_group": "D",
                "age": 34,
                "player_type": "skater",
                "source_row": 3,
                "rookie_suffix_removed": False,
            },
            {
                "player_name": "Missing Goalie (R)",
                "lookup_name": "Missing Goalie",
                "position": "G",
                "position_group": "G",
                "age": 20,
                "player_type": "goalie",
                "source_row": 2,
                "rookie_suffix_removed": True,
            },
        ]
    )

    output, unmatched, ambiguous = match_players(
        players,
        contract_frame(),
        registry_frame(),
        settings(),
        {},
    )

    assert len(output) == 3
    assert len(unmatched) == 1
    assert ambiguous.empty
    erik = output.loc[output["player_name"] == "Erik Gustafsson"].iloc[0]
    assert erik["thl_salary"] == 2000000
    assert erik["player_id"] == 2
    fallback = output.loc[output["player_name"] == "Missing Goalie (R)"].iloc[0]
    assert fallback["thl_salary"] == 775000
    assert fallback["match_status"] == "unmatched"
