#!/usr/bin/env python3
"""Reshape long wifi_clients.csv into a wide per-timestamp CSV."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "wifi_clients.csv"
DEFAULT_OUTPUT = ROOT / "data" / "wifi_clients_wide.csv"

# Stable, human-friendly column order. Unknown buildings are appended sorted.
PREFERRED_BUILDINGS = [
    "kappa",
    "epsilon",
    "iota",
    "omicron",
    "delta",
    "tau",
    "mu",
    "omega",
    "alpha",
    "theta",
    "lambda",
    "pe-buildings",
    "sigma",
    "lounge",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_long(path: Path) -> tuple[list[str], dict[str, dict[str, int]]]:
    """Return (timestamps in order, {timestamp: {scope: count}})."""
    by_ts: dict[str, dict[str, int]] = defaultdict(dict)
    order: list[str] = []
    seen: set[str] = set()

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = row["timestamp"]
            scope = row.get("scope") or "all"
            count = int(row["client_count"])
            if ts not in seen:
                seen.add(ts)
                order.append(ts)
            by_ts[ts][scope] = count
    return order, by_ts


def building_columns(by_ts: dict[str, dict[str, int]]) -> list[str]:
    present: set[str] = set()
    for scopes in by_ts.values():
        present.update(k for k in scopes if k != "all")

    cols = [b for b in PREFERRED_BUILDINGS if b in present]
    extras = sorted(present - set(PREFERRED_BUILDINGS))
    return cols + extras


def write_wide(path: Path, order: list[str], by_ts: dict[str, dict[str, int]]) -> int:
    buildings = building_columns(by_ts)
    header = ["timestamp", "total", *buildings]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for ts in order:
            scopes = by_ts[ts]
            total = scopes.get("all")
            if total is None:
                total = sum(v for k, v in scopes.items() if k != "all")
            row = [ts, total, *[scopes.get(b, "") for b in buildings]]
            writer.writerow(row)
    return len(order)


def reshape(input_path: Path, output_path: Path) -> int:
    if not input_path.exists() or input_path.stat().st_size == 0:
        return 0
    order, by_ts = load_long(input_path)
    if not order:
        return 0
    return write_wide(output_path, order, by_ts)


def main() -> None:
    args = parse_args()
    n = reshape(args.input, args.output)
    print(f"Wrote {n} row(s) to {args.output}")


if __name__ == "__main__":
    main()
