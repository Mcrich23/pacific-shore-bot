#!/usr/bin/env python3
"""Poll RealPage apartment availability and notify Discord when units change."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


DEFAULT_URL = (
    "https://leasing.realpage.com/RP.Leasing.AppService.WebHost/ApartmentList/v1"
    "?FloorplanId=10155386"
    "&MoveInDate=06/01/2026"
    "&PmcId=1182950"
    "&SiteId=1960105"
    "&BpmId=OLL.Shopping.Search.Apartment"
    "&BpmSequence=0"
    "&LogSequence=11"
    "&ClientSessionID=e19868fe-6d4d-89f1-a2f5-3b528e8c414b"
)
DEFAULT_XYZ = (
    "UjZCNTRDRTQ4OTA1QjUxMDE1M0I2QjhDMzRENjBGMUEzOVFHNjBBOUMxMkQ1MzEyQkU3MzQ5NTgy"
    "M0Q0NzFDNEM5MTVnVHRHME1UYzNOemMyTWpNek5qTTFPQT09RjJudHJYbQ=="
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.4 Safari/605.1.15"
)

DEFAULT_START_DATE = "2026-05-01"
DEFAULT_END_DATE = "2026-09-30"
DEFAULT_STATE_FILE = "availability_state.json"

VOLATILE_KEYS = {
    "bpmsequence",
    "clientsessionid",
    "correlationid",
    "generatedat",
    "logsequence",
    "requestid",
    "serverdate",
    "timestamp",
}

UNIT_ID_KEYS = (
    "UnitId",
    "UnitID",
    "UnitNumber",
    "UnitName",
    "ApartmentId",
    "ApartmentID",
    "ApartmentNumber",
    "ApartmentName",
    "AptNumber",
    "AptNo",
)

UNIT_DETAIL_KEYS = (
    "UnitId",
    "UnitID",
    "UnitNumber",
    "UnitName",
    "ApartmentId",
    "ApartmentID",
    "ApartmentNumber",
    "ApartmentName",
    "AptNumber",
    "AptNo",
    "AvailableDate",
    "AvailabilityDate",
    "MadeReadyDate",
    "ReadyDate",
    "MoveInDate",
    "Rent",
    "RentAmount",
    "BaseRentAmount",
    "MarketRent",
    "UnitMarketRent",
    "MinRent",
    "MaxRent",
    "Price",
    "Bedrooms",
    "Bathrooms",
    "Beds",
    "Baths",
    "SqFt",
    "SquareFeet",
    "RentableSquareFootage",
    "FloorNumber",
    "BuildingNumber",
)


class BotError(Exception):
    """Raised when polling or notification cannot complete cleanly."""


@dataclass(frozen=True)
class Config:
    url: str
    webhook_url: str | None
    start_date: dt.date
    end_date: dt.date
    poll_seconds: float
    request_delay_seconds: float
    timeout_seconds: float
    state_file: str
    client_session_id: str
    xyz_header: str | None
    user_agent: str
    notify_on_first_run: bool
    alert_on_errors: bool
    once: bool


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        raise ValueError("end date must be on or after start date")
    days = (end - start).days
    return [start + dt.timedelta(days=offset) for offset in range(days + 1)]


def move_in_date(value: dt.date) -> str:
    return value.strftime("%m/%d/%Y")


def build_url(base_url: str, value: dt.date, client_session_id: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["MoveInDate"] = [move_in_date(value)]
    query["ClientSessionID"] = [client_session_id]
    encoded_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=encoded_query))


def fetch_json(url: str, config: Config) -> Any:
    headers = {
        "Pragma": "no-cache",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://www.pacificshoresapts.com",
        "Referer": "https://www.pacificshoresapts.com/",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Priority": "u=3, i",
        "X-Phased": "",
        "X-AuthToken": "",
        "User-Agent": config.user_agent,
    }
    if config.xyz_header:
        headers["XYZ"] = config.xyz_header

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500]
        raise BotError(f"HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise BotError(f"request failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise BotError(f"response was not JSON: {body[:500]}") from exc


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key.lower() in VOLATILE_KEYS:
                continue
            cleaned[key] = strip_volatile(item)
        return cleaned
    if isinstance(value, list):
        return [strip_volatile(item) for item in value]
    return value


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def scalar_details(item: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for key in UNIT_DETAIL_KEYS:
        if key in item and is_scalar(item[key]):
            details[key] = item[key]

    if not details:
        for key, value in item.items():
            if is_scalar(value) and key.lower() not in VOLATILE_KEYS:
                details[key] = value

    return details


def unit_identity(item: dict[str, Any], fallback_index: int) -> str:
    for key in UNIT_ID_KEYS:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)

    digest = stable_hash(item)[:12]
    return f"unit-{fallback_index}-{digest}"


def looks_like_unit(item: dict[str, Any]) -> bool:
    keys = set(item)
    if keys.intersection(UNIT_ID_KEYS):
        return True

    lower_keys = {key.lower() for key in keys}
    has_unitish_name = bool({"unit", "unitnumber", "apartment", "apartmentnumber"} & lower_keys)
    has_availability = bool(
        {
            "availabledate",
            "availabilitydate",
            "madereadydate",
            "readydate",
            "moveindate",
        }
        & lower_keys
    )
    has_price = bool({"rent", "rentamount", "baserentamount", "price"} & lower_keys)
    return has_unitish_name and (has_availability or has_price)


def walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for item in value.values():
            found.extend(walk_dicts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(walk_dicts(item))
    return found


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_availability(payload: Any) -> dict[str, Any]:
    cleaned = strip_volatile(payload)
    unit_items = [item for item in walk_dicts(cleaned) if looks_like_unit(item)]

    units: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(unit_items):
        identity = unit_identity(item, index)
        units[identity] = scalar_details(item)

    if units:
        source = {"kind": "units", "units": dict(sorted(units.items()))}
    else:
        source = {"kind": "response", "response": cleaned}

    return {
        "hash": stable_hash(source),
        "kind": source["kind"],
        "unit_count": len(units) if units else None,
        "units": source.get("units"),
        "response": source.get("response") if not units else None,
    }


def load_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"dates": {}}
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(path: str, state: dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".availability-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def describe_unit(unit_id: str, details: dict[str, Any] | None) -> str:
    if not details:
        return unit_id

    interesting = []
    for key in (
        "UnitNumber",
        "ApartmentName",
        "ApartmentNumber",
        "AvailableDate",
        "ReadyDate",
        "MoveInDate",
        "Rent",
        "RentAmount",
        "BaseRentAmount",
        "Price",
        "SqFt",
        "SquareFeet",
    ):
        value = details.get(key)
        if value not in (None, ""):
            interesting.append(f"{key}={value}")

    if not interesting:
        return unit_id
    return f"{unit_id} ({', '.join(interesting[:6])})"


def summarize_change(date_key: str, before: dict[str, Any] | None, after: dict[str, Any]) -> str:
    if before is None:
        count = after.get("unit_count")
        if count is None:
            return f"{date_key}: baseline captured; response fingerprint saved."
        return f"{date_key}: baseline captured with {count} available unit(s)."

    before_units = before.get("units") or {}
    after_units = after.get("units") or {}
    if before_units and after_units:
        before_ids = set(before_units)
        after_ids = set(after_units)
        added = sorted(after_ids - before_ids)
        removed = sorted(before_ids - after_ids)
        changed = sorted(
            unit_id
            for unit_id in before_ids & after_ids
            if before_units.get(unit_id) != after_units.get(unit_id)
        )

        lines = [
            f"{date_key}: availability changed",
            f"available units: {len(before_units)} -> {len(after_units)}",
        ]
        if added:
            lines.append("added: " + "; ".join(describe_unit(unit_id, after_units[unit_id]) for unit_id in added[:8]))
        if removed:
            lines.append("removed: " + "; ".join(describe_unit(unit_id, before_units[unit_id]) for unit_id in removed[:8]))
        if changed:
            lines.append("changed: " + "; ".join(changed[:8]))
        return "\n".join(lines)

    before_count = before.get("unit_count")
    after_count = after.get("unit_count")
    if before_count is not None or after_count is not None:
        return f"{date_key}: availability response changed; available units {before_count} -> {after_count}."
    return f"{date_key}: availability response changed; no unit-level records were detected."


def post_discord(webhook_url: str, message: str, timeout_seconds: float) -> None:
    chunks = split_discord_message(message)
    for chunk in chunks:
        payload = json.dumps({"content": chunk}).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "pacific-shore-availability-bot/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.status >= 300:
                    raise BotError(f"Discord webhook returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            retry_after = exc.headers.get("Retry-After")
            retry_note = f" retry_after={retry_after}s" if retry_after else ""
            raise BotError(f"Discord webhook HTTP {exc.code}:{retry_note} {details}") from exc
        except urllib.error.URLError as exc:
            raise BotError(f"Discord webhook failed: {exc.reason}") from exc


def split_discord_message(message: str) -> list[str]:
    limit = 1900
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in message.splitlines():
        next_len = current_len + len(line) + 1
        if current and next_len > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def clear_pending_notification(entry: dict[str, Any]) -> None:
    entry["needs_refire"] = False
    entry.pop("pending_notification", None)


def mark_pending_notification(entry: dict[str, Any], message: str, error: Exception) -> None:
    existing = entry.get("pending_notification") or {}
    entry["needs_refire"] = True
    entry["pending_notification"] = {
        "message": message,
        "attempts": int(existing.get("attempts", 0)) + 1,
        "created_at": existing.get("created_at") or utc_now(),
        "last_attempt_at": utc_now(),
        "last_error": str(error),
    }


def send_or_mark_pending(
    config: Config,
    state: dict[str, Any],
    date_key: str,
    entry: dict[str, Any],
    message: str,
) -> bool:
    if not config.webhook_url:
        return True

    try:
        post_discord(config.webhook_url, message, config.timeout_seconds)
        clear_pending_notification(entry)
        save_state(config.state_file, state)
        return True
    except Exception as exc:
        mark_pending_notification(entry, message, exc)
        save_state(config.state_file, state)
        print(f"{date_key}: Discord notification pending ({exc})", flush=True)
        return False


def retry_pending_notification(
    config: Config,
    state: dict[str, Any],
    date_key: str,
    entry: dict[str, Any],
) -> bool:
    if not config.webhook_url or not entry.get("needs_refire"):
        return False

    pending = entry.get("pending_notification") or {}
    message = pending.get("message")
    if not message:
        message = f"{date_key}: availability changed; retry requested but no saved message was present."

    sent = send_or_mark_pending(config, state, date_key, entry, message)
    if sent:
        print(f"{date_key}: pending Discord notification sent", flush=True)
    return sent


def poll_once(config: Config, state: dict[str, Any]) -> int:
    saved_dates = state.setdefault("dates", {})
    changed_dates = 0
    first_run_dates = 0
    refired_notifications = 0
    errors: list[str] = []

    for index, value in enumerate(date_range(config.start_date, config.end_date)):
        date_key = value.isoformat()
        url = build_url(config.url, value, config.client_session_id)
        is_last = index == (config.end_date - config.start_date).days
        try:
            payload = fetch_json(url, config)
            snapshot = normalize_availability(payload)
        except Exception as exc:
            errors.append(f"{date_key}: {exc}")
            print(f"{date_key}: failed ({exc})", flush=True)
            if not is_last and config.request_delay_seconds > 0:
                time.sleep(config.request_delay_seconds)
            continue

        previous = saved_dates.get(date_key)

        is_first_seen = previous is None
        is_changed = previous is None or previous.get("hash") != snapshot["hash"]
        if is_changed:
            entry = {
                **snapshot,
                "checked_at": utc_now(),
                "needs_refire": False,
            }
            saved_dates[date_key] = entry

            if is_first_seen:
                first_run_dates += 1
            if config.webhook_url and (config.notify_on_first_run or not is_first_seen):
                message = summarize_change(date_key, previous, snapshot)
                send_or_mark_pending(config, state, date_key, entry, message)

            if not is_first_seen:
                changed_dates += 1
        elif previous is not None and previous.get("needs_refire"):
            if retry_pending_notification(config, state, date_key, previous):
                refired_notifications += 1

        print(
            f"{date_key}: {'changed' if is_changed and not is_first_seen else 'baseline' if is_first_seen else 'unchanged'}",
            flush=True,
        )

        if not is_last and config.request_delay_seconds > 0:
            time.sleep(config.request_delay_seconds)

    save_state(config.state_file, state)
    if first_run_dates and not config.notify_on_first_run:
        print(f"Captured {first_run_dates} baseline date(s); first-run Discord notifications are disabled.")
    if refired_notifications:
        print(f"Refired {refired_notifications} pending Discord notification(s).")
    if errors:
        sample = "; ".join(errors[:5])
        extra = "" if len(errors) <= 5 else f"; plus {len(errors) - 5} more"
        raise BotError(f"{len(errors)} date request(s) failed. {sample}{extra}")
    return changed_dates


def build_config(argv: list[str]) -> Config:
    parser = argparse.ArgumentParser(description="Poll RealPage availability and notify Discord on changes.")
    parser.add_argument("--url", default=os.getenv("REALPAGE_URL", DEFAULT_URL))
    parser.add_argument("--webhook-url", default=os.getenv("DISCORD_WEBHOOK_URL"))
    parser.add_argument("--start-date", default=os.getenv("START_DATE", DEFAULT_START_DATE))
    parser.add_argument("--end-date", default=os.getenv("END_DATE", DEFAULT_END_DATE))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("POLL_SECONDS", "300")))
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=float(os.getenv("REQUEST_DELAY_SECONDS", "0.25")),
        help="Delay between date requests inside each sweep.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("TIMEOUT_SECONDS", "30")))
    parser.add_argument("--state-file", default=os.getenv("STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument(
        "--client-session-id",
        default=os.getenv("REALPAGE_CLIENT_SESSION_ID", "auto"),
        help="Use 'auto' to generate a fresh RealPage ClientSessionID at startup.",
    )
    parser.add_argument("--xyz-header", default=os.getenv("REALPAGE_XYZ", DEFAULT_XYZ))
    parser.add_argument("--user-agent", default=os.getenv("REALPAGE_USER_AGENT", DEFAULT_USER_AGENT))
    parser.add_argument("--notify-on-first-run", action="store_true", default=env_bool("NOTIFY_ON_FIRST_RUN", False))
    parser.add_argument("--alert-on-errors", action="store_true", default=env_bool("ALERT_ON_ERRORS", True))
    parser.add_argument("--once", action="store_true", default=env_bool("RUN_ONCE", False))
    args = parser.parse_args(argv)

    if args.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be greater than zero")
    if args.request_delay_seconds < 0:
        raise ValueError("--request-delay-seconds cannot be negative")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than zero")

    client_session_id = args.client_session_id
    if client_session_id.strip().lower() == "auto":
        client_session_id = str(uuid.uuid4())

    return Config(
        url=args.url,
        webhook_url=args.webhook_url,
        start_date=parse_date(args.start_date),
        end_date=parse_date(args.end_date),
        poll_seconds=args.poll_seconds,
        request_delay_seconds=args.request_delay_seconds,
        timeout_seconds=args.timeout_seconds,
        state_file=args.state_file,
        client_session_id=client_session_id,
        xyz_header=args.xyz_header,
        user_agent=args.user_agent,
        notify_on_first_run=args.notify_on_first_run,
        alert_on_errors=args.alert_on_errors,
        once=args.once,
    )


def main(argv: list[str]) -> int:
    config = build_config(argv)
    state = load_state(config.state_file)
    stop = False

    def handle_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    print(
        "Polling "
        f"{config.start_date.isoformat()} through {config.end_date.isoformat()} "
        f"every {config.poll_seconds:g}s; state={config.state_file}",
        flush=True,
    )
    print(f"RealPage ClientSessionID={config.client_session_id}", flush=True)

    while not stop:
        started = time.monotonic()
        try:
            changed_dates = poll_once(config, state)
            print(f"Sweep complete: {changed_dates} date(s) changed.", flush=True)
        except Exception as exc:
            message = f"Availability bot error: {exc}"
            print(message, file=sys.stderr, flush=True)
            if config.webhook_url and config.alert_on_errors:
                try:
                    post_discord(config.webhook_url, message, config.timeout_seconds)
                except Exception as webhook_exc:
                    print(f"Could not post error to Discord: {webhook_exc}", file=sys.stderr, flush=True)

        if config.once:
            break

        elapsed = time.monotonic() - started
        sleep_for = max(0.0, config.poll_seconds - elapsed)
        print(f"Sleeping {sleep_for:.1f}s.", flush=True)
        deadline = time.monotonic() + sleep_for
        while not stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    save_state(config.state_file, state)
    print("Stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
