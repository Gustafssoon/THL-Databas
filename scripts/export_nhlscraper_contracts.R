#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
output_path <- if (length(args) >= 1) args[[1]] else "data/input/nhlscraper_contracts.csv"

if (!requireNamespace("nhlscraper", quietly = TRUE)) {
  stop(
    paste(
      "Paketet 'nhlscraper' saknas.",
      "Installera det enligt projektets dokumentation innan exporten körs."
    )
  )
}

contracts_data <- nhlscraper::contracts()
required_columns <- c(
  "playerFullName",
  "positionCode",
  "teamTriCode",
  "signedWithTriCode",
  "startSeasonId",
  "endSeasonId",
  "contractYears",
  "contractValue",
  "contractAAV",
  "signingBonus"
)

missing_columns <- setdiff(required_columns, names(contracts_data))
if (length(missing_columns) > 0) {
  stop(paste("Saknade kolumner:", paste(missing_columns, collapse = ", ")))
}

dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
utils::write.csv(
  contracts_data[, required_columns],
  output_path,
  row.names = FALSE,
  na = ""
)

message(sprintf("Exporterade %s kontraktsrader till %s", nrow(contracts_data), output_path))
