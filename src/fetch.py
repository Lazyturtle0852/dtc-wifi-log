#!/usr/bin/env python3
"""Fetch campus WiFi client counts and append them to CSV."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("WIFI_DATA_DIR", ROOT / "data"))
CSV_PATH = Path(os.environ.get("WIFI_CSV_PATH", DATA_DIR / "wifi_clients.csv"))
TIMEZONE = ZoneInfo(os.environ.get("WIFI_TIMEZONE", "Asia/Tokyo"))
REQUEST_TIMEOUT = float(os.environ.get("WIFI_REQUEST_TIMEOUT", "30"))
DEFAULT_API_URL = "https://api.dtc.wide.ad.jp/crowd"
DEFAULT_API_FORMAT = "dtc_crowd"


def now_iso() -> str:
    return datetime.now(TIMEZONE).replace(microsecond=0).isoformat()


def to_local_iso(value: str) -> str:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts.astimezone(TIMEZONE).replace(microsecond=0).isoformat()


def fetch_json(url: str, max_attempts: int | None = None, base_delay: float | None = None) -> dict:
    attempts = max_attempts or int(os.environ.get("WIFI_FETCH_MAX_ATTEMPTS", "5"))
    delay = base_delay or float(os.environ.get("WIFI_FETCH_RETRY_DELAY_SEC", "5"))
    last_error: requests.RequestException | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                break
            print(
                f"fetch failed (attempt {attempt}/{attempts}): {exc}; retrying in {delay}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 3

    assert last_error is not None
    raise last_error


def parse_counts(body: str, fmt: str) -> tuple[str, list[tuple[str, int]]]:
    if fmt == "mock":
        return now_iso(), [("all", 0)]

    if fmt == "plain":
        return now_iso(), [("all", int(body))]

    if fmt == "conbu":
        return now_iso(), [("all", int(body))]

    payload = json.loads(body)

    if fmt == "dtc_crowd":
        return parse_dtc_crowd(payload)

    if fmt == "dtc_wifi_clients":
        return parse_dtc_wifi_clients(payload)

    if fmt == "json_total":
        for key in ("client_count", "count", "total", "associations"):
            if key in payload:
                return now_iso(), [("all", int(payload[key]))]
        raise ValueError(f"json_total format: no known total field in {payload!r}")

    if fmt == "json_per_ap":
        return now_iso(), parse_json_per_ap(payload)

    if fmt == "auto":
        if body.isdigit() or (body.startswith("-") and body[1:].isdigit()):
            return now_iso(), [("all", int(body))]
        if isinstance(payload, dict) and payload.get("type") == "building-crowd-snapshot":
            return parse_dtc_crowd(payload)
        if isinstance(payload, dict) and "clients" in payload:
            return parse_dtc_wifi_clients(payload)
        if isinstance(payload, dict):
            for key in ("client_count", "count", "total", "associations"):
                if key in payload and isinstance(payload[key], (int, float, str)):
                    return now_iso(), [("all", int(payload[key]))]
            if all(isinstance(v, (int, float, str, dict)) for v in payload.values()):
                return now_iso(), parse_json_per_ap(payload)
        if isinstance(payload, list):
            return now_iso(), parse_json_per_ap(payload)
        raise ValueError("auto format: could not parse API response")

    raise ValueError(f"Unknown WIFI_API_FORMAT: {fmt}")


def parse_dtc_crowd(payload: dict) -> tuple[str, list[tuple[str, int]]]:
    measured_at = payload.get("measuredAt") or payload.get("generatedAt")
    timestamp = to_local_iso(measured_at) if measured_at else now_iso()

    rows: list[tuple[str, int]] = []
    total = 0
    for reading in payload.get("readings", []):
        count = reading.get("apClientCount")
        if count is None:
            continue
        area = reading.get("areaKey") or reading.get("buildingKey")
        if area is None:
            continue
        count_int = int(count)
        rows.append((str(area), count_int))
        total += count_int

    rows.append(("all", total))
    return timestamp, rows


def parse_dtc_wifi_clients(payload: dict) -> tuple[str, list[tuple[str, int]]]:
    measured_at = payload.get("measuredAt")
    timestamp = to_local_iso(measured_at) if measured_at else now_iso()
    clients = payload.get("clients", [])
    return timestamp, [("all", len(clients))]


def parse_json_per_ap(payload: object) -> list[tuple[str, int]]:
    if isinstance(payload, dict):
        rows: list[tuple[str, int]] = []
        for ap_id, value in payload.items():
            if isinstance(value, dict):
                count = value.get("client_count", value.get("count"))
            else:
                count = value
            if count is not None:
                rows.append((str(ap_id), int(count)))
        if rows:
            return rows
    if isinstance(payload, list):
        rows = []
        for item in payload:
            ap_id = item.get("ap_id") or item.get("name") or item.get("id")
            count = item.get("client_count", item.get("count"))
            if ap_id is None or count is None:
                raise ValueError(f"json_per_ap list item missing fields: {item!r}")
            rows.append((str(ap_id), int(count)))
        return rows
    raise ValueError(f"json_per_ap format: unsupported payload {type(payload)!r}")


def ensure_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(["timestamp", "scope", "client_count"])


def append_rows(path: Path, rows: list[tuple[str, int]], timestamp: str) -> None:
    ensure_csv(path)
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for scope, count in rows:
            writer.writerow([timestamp, scope, count])


def main() -> int:
    url = os.environ.get("WIFI_API_URL", DEFAULT_API_URL).strip()
    fmt = os.environ.get("WIFI_API_FORMAT", DEFAULT_API_FORMAT).strip().lower()

    if not url and fmt != "mock":
        print("WIFI_API_URL is required (or set WIFI_API_FORMAT=mock for dry-run).", file=sys.stderr)
        return 1

    if fmt == "mock":
        timestamp, rows = parse_counts("0", "mock")
    else:
        payload = fetch_json(url)
        timestamp, rows = parse_counts(json.dumps(payload), fmt)

    append_rows(CSV_PATH, rows, timestamp)

    try:
        from reshape_wide import reshape

        wide_path = Path(os.environ.get("WIFI_WIDE_CSV_PATH", DATA_DIR / "wifi_clients_wide.csv"))
        n_wide = reshape(CSV_PATH, wide_path)
        print(f"Wrote {n_wide} wide row(s) to {wide_path}")
    except Exception as exc:  # noqa: BLE001 — wide view must not break collection
        print(f"Wide CSV reshape skipped: {exc}", file=sys.stderr)

    for scope, count in rows:
        print(f"{timestamp}\t{scope}\t{count}")
    print(f"Appended {len(rows)} row(s) to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
