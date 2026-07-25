#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
contracts_output <- if (length(args) >= 1) args[[1]] else "data/input/nhlscraper_contracts.csv"
players_output <- if (length(args) >= 2) args[[2]] else "data/input/nhlscraper_players.csv"

if (!requireNamespace("nhlscraper", quietly = TRUE)) {
  stop("Paketet 'nhlscraper' saknas. Installera det från CRAN innan exporten körs.")
}

pick_column <- function(data, candidates, required = TRUE) {
  available <- candidates[candidates %in% names(data)]
  if (length(available) > 0L) return(data[[available[[1L]]]])
  if (required) {
    stop(sprintf(
      "Saknad kolumn. Förväntade någon av: %s",
      paste(candidates, collapse = ", ")
    ))
  }
  rep(NA, nrow(data))
}

namespace <- asNamespace("nhlscraper")
contracts_data <- tryCatch(
  get(".contracts_base", envir = namespace, inherits = FALSE),
  error = function(e) NULL
)
if (!is.data.frame(contracts_data) || nrow(contracts_data) == 0L) {
  stop("Kunde inte läsa nhlscrapers interna råa kontraktstabell '.contracts_base'.")
}

# Den interna tabellen behåller även kontraktsrader som contracts() annars kan
# släppa när NHL-ID-matchningen är tvetydig. THL gör en egen åldersmedveten
# identitetsmatchning mot rosterfilerna.
contracts_normalized <- data.frame(
  playerId = rep(NA_integer_, nrow(contracts_data)),
  playerFullName = pick_column(contracts_data, c("playerFullName")),
  positionCode = pick_column(contracts_data, c("positionCode")),
  ageAtSigning = pick_column(contracts_data, c("ageAtSigning"), required = FALSE),
  signedWithTeamId = pick_column(contracts_data, c("signedWithTeamId"), required = FALSE),
  signedWithTeamTriCode = pick_column(
    contracts_data,
    c("signedWithTeamTriCode", "signedWithTriCode", "teamTriCode"),
    required = FALSE
  ),
  startSeasonId = pick_column(contracts_data, c("startSeasonId")),
  endSeasonId = pick_column(contracts_data, c("endSeasonId")),
  contractYears = pick_column(contracts_data, c("term", "contractYears")),
  contractAAV = pick_column(contracts_data, c("aav", "contractAAV")),
  contractValue = pick_column(contracts_data, c("value", "contractValue")),
  signingBonus = pick_column(contracts_data, c("bonus", "signingBonus"), required = FALSE),
  sourceFile = pick_column(contracts_data, c("sourceFile"), required = FALSE),
  stringsAsFactors = FALSE
)
contracts_normalized <- contracts_normalized[
  order(contracts_normalized$playerFullName, contracts_normalized$startSeasonId),
]
rownames(contracts_normalized) <- NULL

players_data <- nhlscraper::players()
if (!is.data.frame(players_data) || nrow(players_data) == 0L) {
  stop("nhlscraper::players() returnerade ingen spelarregisterdata.")
}
players_normalized <- data.frame(
  playerId = pick_column(players_data, c("playerId")),
  playerFullName = pick_column(players_data, c("playerFullName")),
  playerFirstName = pick_column(players_data, c("playerFirstName"), required = FALSE),
  playerLastName = pick_column(players_data, c("playerLastName"), required = FALSE),
  positionCode = pick_column(players_data, c("positionCode")),
  birthDate = pick_column(players_data, c("birthDate"), required = FALSE),
  currentTeamId = pick_column(players_data, c("currentTeamId"), required = FALSE),
  onRoster = pick_column(players_data, c("onRoster"), required = FALSE),
  stringsAsFactors = FALSE
)
players_normalized <- players_normalized[!is.na(players_normalized$playerId), ]
players_normalized <- players_normalized[order(players_normalized$playerFullName), ]
rownames(players_normalized) <- NULL

dir.create(dirname(contracts_output), recursive = TRUE, showWarnings = FALSE)
dir.create(dirname(players_output), recursive = TRUE, showWarnings = FALSE)
utils::write.csv(contracts_normalized, contracts_output, row.names = FALSE, na = "")
utils::write.csv(players_normalized, players_output, row.names = FALSE, na = "")

message(sprintf(
  "Exporterade %s råa kontraktsrader till %s",
  nrow(contracts_normalized), contracts_output
))
message(sprintf(
  "Exporterade %s spelare med NHL-ID till %s",
  nrow(players_normalized), players_output
))
