#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
output_path <- if (length(args) >= 1) args[[1]] else "data/input/nhlscraper_contracts.csv"

if (!requireNamespace("nhlscraper", quietly = TRUE)) {
  stop(
    paste(
      "Paketet 'nhlscraper' saknas.",
      "Installera det från CRAN innan exporten körs."
    )
  )
}

contracts_data <- nhlscraper::contracts()
if (!is.data.frame(contracts_data) || nrow(contracts_data) == 0L) {
  stop("nhlscraper::contracts() returnerade ingen kontraktsdata.")
}

pick_column <- function(data, candidates, required = TRUE) {
  available <- candidates[candidates %in% names(data)]
  if (length(available) > 0L) {
    return(data[[available[[1L]]]])
  }
  if (required) {
    stop(
      sprintf(
        "Saknade kontraktskolumn. Förväntade någon av: %s",
        paste(candidates, collapse = ", ")
      )
    )
  }
  rep(NA, nrow(data))
}

# nhlscraper 0.7 använder korta namn som term/aav/value/bonus.
# Äldre versioner använde contractYears/contractAAV/contractValue/signingBonus.
# Exporten normaliserar båda varianterna till ett stabilt schema för THL.
normalized <- data.frame(
  playerId = pick_column(contracts_data, c("playerId"), required = FALSE),
  playerFullName = pick_column(contracts_data, c("playerFullName")),
  positionCode = pick_column(contracts_data, c("positionCode")),
  ageAtSigning = pick_column(contracts_data, c("ageAtSigning"), required = FALSE),
  signedWithTeamId = pick_column(
    contracts_data,
    c("signedWithTeamId"),
    required = FALSE
  ),
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
  signingBonus = pick_column(
    contracts_data,
    c("bonus", "signingBonus"),
    required = FALSE
  ),
  stringsAsFactors = FALSE
)

normalized <- normalized[order(normalized$playerFullName, normalized$startSeasonId), ]
rownames(normalized) <- NULL

dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
utils::write.csv(
  normalized,
  output_path,
  row.names = FALSE,
  na = ""
)

message(
  sprintf(
    "Exporterade %s kontraktsrader för %s unika spelare till %s",
    nrow(normalized),
    length(unique(normalized$playerId[!is.na(normalized$playerId)])),
    output_path
  )
)
