#!/usr/bin/env python3
"""Backfill missing WiFi snapshots using the DTC API time query."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlunparse

import requests

from fetch import CSV_PATH, DATA_DIR, DEFAULT_API_URL, TIMEZONE, parse_dtc_crowd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTERVAL = int(os.environ.get("WIFI_COLLECT_INTERVAL_SEC", "600"))
DEFAULT_GAP_THRESHOLD = int(os.environ.get("WIFI_GAP_THRESHOLD_SEC", "900"))
REQUEST_TIMEOUT = float(os.environ.get("WIFI_REQUEST_TIMEOUT", "30"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--api-url", default=os.environ.get("WIFI_API_URL", DEFAULT_API_URL))
    parser.add_argument("--interval-sec", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--gap-threshold-sec", type=int, default=DEFAULT_GAP_THRESHOLD)
    parser.add_argument("--max-slots", type=int, default=int(os.environ.get("WIFI_BACKFILL_MAX_SLOTS", "200")))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def crowd_api_base(api_url: str) -> str:
    parsed = urlparse(api_url.strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/crowd/range"):
        path = path[: -len("/range")]
    elif not path.endswith("/crowd"):
        path = f"{path}/crowd" if path else "/crowd"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def crowd_time_url(api_base: str, when: datetime) -> str:
    query = urlencode({"time": when.isoformat()})
    return f"{api_base}?{query}"


def crowd_range_url(api_base: str, start: datetime, end: datetime) -> str:
    query = urlencode({"startTime": start.isoformat(), "endTime": end.isoformat()})
    return f"{api_base}/range?{query}"


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(TIMEZONE)


def load_timestamps(path: Path) -> list[datetime]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    seen: set[datetime] = set()
    order: list[datetime] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = parse_timestamp(row["timestamp"])
            if ts not in seen:
                seen.add(ts)
                order.append(ts)
    order.sort()
    return order


def has_nearby_timestamp(existing: list[datetime], target: datetime, tolerance_sec: int) -> bool:
    tolerance = timedelta(seconds=tolerance_sec)
    return any(abs(ts - target) <= tolerance for ts in existing)


def find_gap_regions(
    timestamps: list[datetime],
    interval_sec: int,
    gap_threshold_sec: int,
) -> list[tuple[datetime, datetime]]:
    if len(timestamps) < 2:
        return []

    threshold = timedelta(seconds=gap_threshold_sec)
    regions: list[tuple[datetime, datetime]] = []
    for prev_ts, next_ts in zip(timestamps, timestamps[1:]):
        if next_ts - prev_ts > threshold:
            regions.append((prev_ts, next_ts))
    return regions


def expected_targets(start: datetime, end: datetime, interval_sec: int) -> list[datetime]:
    step = timedelta(seconds=interval_sec)
    targets: list[datetime] = []
    current = start + step
    while current < end:
        targets.append(current)
        current += step
    return targets


def fetch_snapshot_at(api_base: str, when: datetime) -> tuple[str, list[tuple[str, int]]]:
    response = requests.get(crowd_time_url(api_base, when), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return parse_dtc_crowd(response.json())


def snapshots_from_range(
    api_base: str,
    start: datetime,
    end: datetime,
    existing: list[datetime],
    interval_sec: int,
) -> list[tuple[str, list[tuple[str, int]]]]:
    response = requests.get(crowd_range_url(api_base, start, end), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()

    targets = expected_targets(start, end, interval_sec)
    if not targets:
        return []

    by_target: dict[datetime, dict[str, int]] = {target: {} for target in targets}
    tolerance = timedelta(seconds=interval_sec // 2)

    for reading in payload.get("readings", []):
        scope = reading.get("areaKey") or reading.get("buildingKey")
        if scope is None:
            continue
        for measured_at, count in zip(reading.get("measuredAts", []), reading.get("apClientCounts", [])):
            if count is None:
                continue
            measured = datetime.fromisoformat(measured_at.replace("Z", "+00:00")).astimezone(TIMEZONE)
            nearest = min(targets, key=lambda target: abs(target - measured))
            if abs(nearest - measured) > tolerance:
                continue
            by_target[nearest][str(scope)] = int(count)

    snapshots: list[tuple[str, list[tuple[str, int]]]] = []
    for target in targets:
        if has_nearby_timestamp(existing, target, interval_sec // 2):
            continue
        scopes = by_target.get(target, {})
        if not scopes:
            continue
        total = sum(scopes.values())
        rows = [(scope, count) for scope, count in sorted(scopes.items())]
        rows.append(("all", total))
        snapshots.append((target.replace(microsecond=0).isoformat(), rows))
    return snapshots


def backfill_slot(
    api_base: str,
    target: datetime,
) -> tuple[str, list[tuple[str, int]]]:
    timestamp, rows = fetch_snapshot_at(api_base, target)
    return timestamp, rows


def merge_snapshots(path: Path, snapshots: list[tuple[str, list[tuple[str, int]]]]) -> int:
    if not snapshots:
        return 0

    by_ts: dict[str, dict[str, int]] = {}
    order: list[str] = []
    seen: set[str] = set()

    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = row["timestamp"]
                scope = row.get("scope") or "all"
                if ts not in seen:
                    seen.add(ts)
                    order.append(ts)
                    by_ts[ts] = {}
                by_ts[ts][scope] = int(row["client_count"])

    added = 0
    for timestamp, rows in snapshots:
        if timestamp in by_ts:
            continue
        by_ts[timestamp] = {scope: count for scope, count in rows}
        order.append(timestamp)
        added += 1

    order.sort(key=parse_timestamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "scope", "client_count"])
        for ts in order:
            scopes = by_ts[ts]
            for scope, count in sorted(scopes.items(), key=lambda item: (item[0] == "all", item[0])):
                writer.writerow([ts, scope, count])
    return added


def collect_missing_snapshots(
    api_base: str,
    existing: list[datetime],
    regions: list[tuple[datetime, datetime]],
    interval_sec: int,
    max_slots: int,
) -> list[tuple[str, list[tuple[str, int]]]]:
    snapshots: list[tuple[str, list[tuple[str, int]]]] = []
    slots_used = 0

    for start, end in regions:
        targets = [
            target
            for target in expected_targets(start, end, interval_sec)
            if not has_nearby_timestamp(existing, target, interval_sec // 2)
        ]
        if not targets:
            continue

        if len(targets) > max_slots - slots_used:
            targets = targets[: max_slots - slots_used]

        if len(targets) >= 3:
            range_snapshots = snapshots_from_range(api_base, start, end, existing, interval_sec)
            snapshots.extend(range_snapshots)
            slots_used += len(range_snapshots)
        else:
            for target in targets:
                timestamp, rows = backfill_slot(api_base, target)
                snapshots.append((timestamp, rows))
                slots_used += 1
                if slots_used >= max_slots:
                    break

        if slots_used >= max_slots:
            break

    return snapshots


def main() -> int:
    args = parse_args()
    api_base = crowd_api_base(args.api_url)

    timestamps = load_timestamps(args.csv)
    regions = find_gap_regions(timestamps, args.interval_sec, args.gap_threshold_sec)
    if not regions:
        print("No gaps detected.")
        return 0

    print(f"Detected {len(regions)} gap region(s).")
    snapshots = collect_missing_snapshots(
        api_base,
        timestamps,
        regions,
        args.interval_sec,
        args.max_slots,
    )
    if not snapshots:
        print("No backfill snapshots fetched.")
        return 0

    if args.dry_run:
        for timestamp, rows in snapshots:
            total = next(count for scope, count in rows if scope == "all")
            print(f"would add {timestamp} total={total}")
        return 0

    added = merge_snapshots(args.csv, snapshots)
    try:
        from reshape_wide import reshape

        wide_path = Path(os.environ.get("WIFI_WIDE_CSV_PATH", DATA_DIR / "wifi_clients_wide.csv"))
        n_wide = reshape(args.csv, wide_path)
        print(f"Wrote {n_wide} wide row(s) to {wide_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"Wide CSV reshape skipped: {exc}", file=sys.stderr)

    print(f"Backfilled {added} timestamp(s) into {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
