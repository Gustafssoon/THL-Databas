# THL Databas

Verktyg och datamodell för Turtle Hockey Leagues spelardatabas.

Projektets första mål är att matcha THL:s spelarlista mot historiska NHL-kontrakt och visa två separata kontraktsbilder:

1. **THL-kontraktet** – kontraktet som gällde under den senast avslutade NHL-säsongen, eftersom THL normalt ligger ett år efter.
2. **Nytt NHL-kontrakt** – ett senare kontrakt som börjar efter THL:s referenssäsong, så att nya förlängningar och avtal också syns.

## Viktiga principer

- Historiska kontrakt och framtida kontrakt hålls isär.
- Matchning sker helst med NHL-ID och annars med normaliserat namn samt position.
- Osäkra matchningar skrivs till en separat granskningsrapport.
- Manuella rättelser lagras separat och skriver aldrig över rådata.
- Ingen PuckPedia- eller CapWages-data ska skrapas eller lagras utan uttryckligt tillstånd.

## Struktur

```text
config/                  Inställningar för säsong och kolumnnamn
data/input/              Materialiserade spelar- och kontraktsfiler
data/manual-overrides/   Manuella rättelser
data/output/             Genererade exporter
reports/                 Matchnings- och kvalitetsrapporter
scripts/                 Import, matchning och export
staging/                 Verifierade importdelar för rosterfilerna
tests/                   Automatiska tester
```

## Inlagda rosterfiler

Följande uppladdningar finns i repot som komprimerade och Base64-kodade staging-delar:

- `STHSPlayerRoster (3)(1).CSV` – 1 739 utespelare plus rubrikrad
- `STHSGoaliesRoster (3)(2).CSV` – 196 målvakter plus rubrikrad

Återskapa de exakta CSV-filerna med:

```bash
python scripts/materialize_rosters.py
```

Det skapar:

```text
data/input/STHSPlayerRoster.csv
data/input/STHSGoaliesRoster.csv
```

Skriptet verifierar både radantal och SHA-256 innan filerna skrivs. Det finns även ett manuellt körbart GitHub Actions-flöde under **Actions → Materialize roster CSV files**.

## Referenssäsong

För THL-säsongen 2026–2027 används NHL-säsongen 2025–2026 som referens. Inställningen finns i `config/config.json`.

Det innebär att exporten visar:

- kontraktet som täcker 2025–2026 under kolumnerna `thl_*`
- ett senare avtal under kolumnerna `next_*`, när spelaren har skrivit ett nytt kontrakt som börjar efter referenssäsongen

## Arbetsflöde

1. Materialisera rosterfilerna:

```bash
python scripts/materialize_rosters.py
```

2. Exportera kontraktsdatan från `nhlscraper`:

```bash
Rscript scripts/export_nhlscraper_contracts.R
```

3. Installera Python-beroenden och kör matchningen:

```bash
python -m pip install -r requirements.txt
python scripts/match_contracts.py
```

4. Granska `reports/unmatched_players.csv` innan resultatet importeras till Google Sheets.

## Status

De aktuella spelar- och målvaktslistorna är inlagda som verifierade importpaket. Grundstruktur och första matchningspipeline är skapade. Matchningsresultatet är ännu inte importerat till THL Spelardatabas.
