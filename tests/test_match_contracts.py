from __future__ import annotations

import pandas as pd

from scripts.match_contracts import (
    Settings,
    match_players,
    prepare_contracts,
    season_to_id,
    select_contracts,
)


def settings() -> Settings:
    return Settings(
        reference_season_id=20252026,
        next_season_id=20262027,
        league_minimum=775000,
        max_contract_years=8,
        threshold=0.94,
    )


def contract_frame() -> pd.DataFrame:
    return prepare_contracts(
        pd.DataFrame(
            [
                {
                    "playerId": 1,
                    "playerFullName": "Test Player",
                    "positionCode": "C",
                    "startSeasonId": 20242025,
                    "endSeasonId": 20252026,
                    "contractYears": 2,
                    "contractAAV": 1000000,
                    "contractValue": 2000000,
                    "signingBonus": 0,
                },
                {
                    "playerId": 1,
                    "playerFullName": "Test Player",
                    "positionCode": "C",
                    "startSeasonId": 20262027,
                    "endSeasonId": 20282029,
                    "contractYears": 3,
                    "contractAAV": 3000000,
                    "contractValue": 9000000,
                    "signingBonus": 1000000,
                },
            ]
        )
    )


def test_season_to_id() -> None:
    assert season_to_id("2025-2026") == 20252026


def test_selects_reference_and_new_contract_separately() -> None:
    result = select_contracts(contract_frame(), settings())

    assert result["thl_salary"] == 1000000
    assert result["thl_contract_years"] == 1
    assert result["has_new_contract"] is True
    assert result["next_contract_salary"] == 3000000
    assert result["next_contract_start"] == 20262027


def test_every_player_gets_an_output_row() -> None:
    players = pd.DataFrame(
        [
            {
                "player_name": "Test Player",
                "position": "C",
                "player_type": "skater",
                "source_row": 2,
            },
            {
                "player_name": "Missing Goalie",
                "position": "G",
                "player_type": "goalie",
                "source_row": 2,
            },
        ]
    )

    output, unmatched, ambiguous = match_players(players, contract_frame(), settings())

    assert len(output) == 2
    assert len(unmatched) == 1
    assert ambiguous.empty
    fallback = output.loc[output["player_name"] == "Missing Goalie"].iloc[0]
    assert fallback["thl_salary"] == 775000
    assert fallback["match_status"] == "unmatched"
