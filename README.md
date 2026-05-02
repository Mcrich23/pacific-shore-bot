# Pacific Shore Availability Bot

Polls the RealPage apartment availability endpoint for every move-in date from May 1, 2026 through September 30, 2026, saves the latest availability snapshot, and posts to a Discord webhook when available units change for a date.

The bot uses only the Python standard library.

## Run

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export POLL_SECONDS=300
python3 pacific_shore_bot.py
```

With Docker Compose:

```bash
cp .env.example .env
docker compose up -d --build
```

Compose stores the saved availability snapshot in the `pacific-shore-data` volume at `/data/availability_state.json`.

For a one-time baseline/test sweep:

```bash
python3 pacific_shore_bot.py --once
```

The first run saves `availability_state.json` and does not notify Discord unless `NOTIFY_ON_FIRST_RUN=true` or `--notify-on-first-run` is used.

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
| `NOTIFY_ON_FIRST_RUN` | `--notify-on-first-run` | `false` |
| `ALERT_ON_ERRORS` | `--alert-on-errors` | `true` |

`POLL_SECONDS` is the delay between full sweeps of all dates. `REQUEST_DELAY_SECONDS` is a small pause between individual date requests inside a sweep.

If RealPage starts returning `401 Unauthorized`, grab a fresh Safari `curl` for the request and update `REALPAGE_URL` and `REALPAGE_XYZ`.

Do not leave `REALPAGE_XYZ` set to a placeholder value in `.env`; if it is unset, the bot uses the captured default header baked into the script.

`REALPAGE_CLIENT_SESSION_ID=auto` generates a fresh RealPage-style GUID when the bot starts.
