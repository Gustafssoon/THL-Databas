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

## Planerad struktur

```text
config/                  Inställningar för säsong och kolumnnamn
data/input/              Lokala indatafiler, ej versionshanterade
data/manual-overrides/   Manuella rättelser
ndata/output/             Genererade exporter, ej versionshanterade
reports/                 Matchnings- och kvalitetsrapporter
scripts/                 Import, matchning och export
tests/                   Automatiska tester
```

## Referenssäsong

För THL-säsongen 2026–2027 används normalt NHL-säsongen 2025–2026 som referens. Detta styrs i `config/config.json` eller via kommandoradsargument.

## Status

Grundstruktur under uppbyggnad.
