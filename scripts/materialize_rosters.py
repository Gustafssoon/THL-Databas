#!/usr/bin/env python3
"""Rebuild the uploaded THL roster CSV files from repository staging chunks."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RosterArtifact:
    name: str
    chunk_pattern: str
    output_path: Path
    sha256: str
    expected_lines: int


ARTIFACTS = (
    RosterArtifact(
        name="goalies",
        chunk_pattern="goalies.csv.gz.b64.part*",
        output_path=Path("data/input/STHSGoaliesRoster.csv"),
        sha256="eec389a41c40c350742d64e13af6313b9927ed802e9037cbe1a9eb8c87b4d9a6",
        expected_lines=197,
    ),
    RosterArtifact(
        name="skaters",
        chunk_pattern="skaters.csv.gz.b64.part*",
        output_path=Path("data/input/STHSPlayerRoster.csv"),
        sha256="4ab1b85bab0c319c71376db7dca3fb2fc8a7fcbc1566f0e8e04b6b3b6adadb0d",
        expected_lines=1740,
    ),
)


def materialize(artifact: RosterArtifact, staging_dir: Path) -> None:
    chunks = sorted(staging_dir.glob(artifact.chunk_pattern))
    if not chunks:
        if artifact.output_path.exists():
            print(f"{artifact.name}: CSV-filen finns redan: {artifact.output_path}")
            return
        raise FileNotFoundError(
            f"Hittade inga staging-delar för {artifact.name}: "
            f"{staging_dir / artifact.chunk_pattern}"
        )

    encoded = "".join(chunk.read_text(encoding="ascii").strip() for chunk in chunks)
    compressed = base64.b64decode(encoded, validate=True)
    payload = gzip.decompress(compressed)

    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != artifact.sha256:
        raise ValueError(
            f"Fel SHA-256 för {artifact.name}: {actual_hash}; förväntade {artifact.sha256}"
        )

    line_count = len(payload.splitlines())
    if line_count != artifact.expected_lines:
        raise ValueError(
            f"Fel radantal för {artifact.name}: {line_count}; "
            f"förväntade {artifact.expected_lines}"
        )

    artifact.output_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.output_path.write_bytes(payload)
    print(
        f"{artifact.name}: skapade {artifact.output_path} "
        f"({line_count} rader, SHA-256 {actual_hash})"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", default="staging")
    args = parser.parse_args()

    staging_dir = Path(args.staging_dir)
    for artifact in ARTIFACTS:
        materialize(artifact, staging_dir)


if __name__ == "__main__":
    main()
