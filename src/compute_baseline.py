#!/usr/bin/env python3
"""Compute nightly baseline and hourly deltas from collected CSV data."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "wifi_clients.csv"
DEFAULT_OUTPUT = ROOT / "data" / "wifi_clients_with_delta.csv"
TIMEZONE = ZoneInfo("Asia/Tokyo")
NIGHT_START = time(2, 0)
NIGHT_END = time(5, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scope", default="all", help="CSV scope column to analyze")
    return parser.parse_args()


def load_rows(path: Path, scope: str) -> list[tuple[datetime, int]]:
    rows: list[tuple[datetime, int]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("scope", "all") != scope:
                continue
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TIMEZONE)
            rows.append((ts, int(row["client_count"])))
    return sorted(rows, key=lambda item: item[0])


def nightly_baseline_by_date(rows: list[tuple[datetime, int]]) -> dict[str, int]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for ts, count in rows:
        local_time = ts.astimezone(TIMEZONE).time()
        if NIGHT_START <= local_time < NIGHT_END and ts.astimezone(TIMEZONE).weekday() < 5:
            buckets[ts.date().isoformat()].append(count)

    baselines: dict[str, int] = {}
    for day, values in buckets.items():
        baselines[day] = int(median(values))
    return baselines


def baseline_for(ts: datetime, baselines: dict[str, int], fallback: int) -> int:
    return baselines.get(ts.date().isoformat(), fallback)


def main() -> None:
    args = parse_args()
    rows = load_rows(args.input, args.scope)
    if not rows:
        raise SystemExit(f"No rows found for scope={args.scope!r} in {args.input}")

    baselines = nightly_baseline_by_date(rows)
    fallback = int(median(baselines.values())) if baselines else 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["timestamp", "scope", "client_count", "baseline", "delta", "date"]
        )
        for ts, count in rows:
            baseline = baseline_for(ts, baselines, fallback)
            writer.writerow(
                [
                    ts.isoformat(),
                    args.scope,
                    count,
                    baseline,
                    count - baseline,
                    ts.date().isoformat(),
                ]
            )

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
