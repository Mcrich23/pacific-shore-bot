# Pacific Shore Availability Bot

Polls the RealPage apartment availability endpoint for every move-in date from May 1, 2026 through September 30, 2026, saves the latest availability snapshot, and posts to a Discord webhook when available units change for a date.

The direct polling path uses the Python standard library. Automatic RealPage auth refresh uses Playwright with WebKit/Chromium, which are installed by the Docker image.

## Run

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export POLL_SECONDS=60
python3 pacific_shore_bot.py
```

With Docker Compose:

```bash
cp .env.example .env
docker compose up -d --build
```

Compose stores the saved availability snapshot in the `pacific-shore-data` volume at `/data/availability_state.json`.
The compose service uses `restart: unless-stopped`, so it will keep running 24/7 and restart after container or host restarts when Docker is configured to start on boot.

For a one-time baseline/test sweep:

```bash
python3 pacific_shore_bot.py --once
```

The first run saves `availability_state.json` and does not notify Discord unless `NOTIFY_ON_FIRST_RUN=true` or `--notify-on-first-run` is used.

If Discord rate-limits or rejects a webhook notification, the date entry in `availability_state.json` is saved with `"needs_refire": true` and a `pending_notification` object. The next sweep retries that saved message even if availability has not changed again.

## Configuration

All options can be set by environment variable or CLI flag.

| Env var | CLI flag | Default |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | `--webhook-url` | unset |
| `POLL_SECONDS` | `--poll-seconds` | `300` |
| `START_DATE` | `--start-date` | `2026-05-01` |
| `END_DATE` | `--end-date` | `2026-09-30` |
| `STATE_FILE` | `--state-file` | `availability_state.json` |
| `REQUEST_DELAY_SECONDS` | `--request-delay-seconds` | `0.25` |
| `TIMEOUT_SECONDS` | `--timeout-seconds` | `30` |
| `REALPAGE_URL` | `--url` | the provided endpoint |
| `REALPAGE_CLIENT_SESSION_ID` | `--client-session-id` | `auto` |
| `REALPAGE_XYZ` | `--xyz-header` | the provided Safari `XYZ` header |
| `REALPAGE_USER_AGENT` | `--user-agent` | the provided Safari user agent |
| `MAX_CONSECUTIVE_401` | `--max-consecutive-401` | `5` |
| `AUTO_REFRESH_AUTH` | `--auto-refresh-auth`, `--no-auto-refresh-auth` | `true` |
| `AUTH_REFRESH_URL` | `--auth-refresh-url` | Pacific Shores apply page |
| `AUTH_REFRESH_BROWSER` | `--auth-refresh-browser` | `auto` |
| `AUTH_REFRESH_TIMEOUT_SECONDS` | `--auth-refresh-timeout-seconds` | `45` |
| `NOTIFY_ON_FIRST_RUN` | `--notify-on-first-run` | `false` |
| `ALERT_ON_ERRORS` | `--alert-on-errors` | `true` |

`POLL_SECONDS` is the delay between full sweeps of all dates. `REQUEST_DELAY_SECONDS` is a small pause between individual date requests inside a sweep.
For every-minute polling, set `POLL_SECONDS=60` in `.env`. If a full sweep takes longer than 60 seconds, the next sweep starts immediately after the previous one finishes.

If RealPage starts returning `401 Unauthorized`, the bot stops the sweep after `MAX_CONSECUTIVE_401` consecutive failures, launches a headless browser, visits `AUTH_REFRESH_URL`, captures a fresh RealPage AppService request with its `XYZ` header, saves that header and `ClientSessionID` under `realpage_auth` in the state file, and immediately starts a new sweep against the ApartmentList endpoint. With `AUTH_REFRESH_BROWSER=auto`, it tries WebKit first and Chromium second. If browser refresh cannot observe an `XYZ` header before `AUTH_REFRESH_TIMEOUT_SECONDS`, it fails cleanly instead of burning through every date; grab a fresh Safari `curl` for the request and update `REALPAGE_URL` and `REALPAGE_XYZ`.

Do not leave `REALPAGE_XYZ` set to a placeholder value in `.env`; if it is unset, the bot uses the captured default header baked into the script.

`REALPAGE_CLIENT_SESSION_ID=auto` generates a fresh RealPage-style GUID when the bot starts.

`MAX_CONSECUTIVE_401` prevents a stale RealPage auth header from burning through every date in the sweep. The default stops after 5 consecutive unauthorized responses.
