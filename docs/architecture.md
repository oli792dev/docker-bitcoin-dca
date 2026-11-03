# Architecture and operation

[Setup and usage](../README.md)

## Components

One Python process runs an HTTPS dashboard and a single account worker. The worker serializes exchange checks, purchases and withdrawals; settings changes use the same account lock. Web actions enter a bounded queue. Reports read saved data; browser refreshes do not request exchange prices.

| Directory | Responsibility |
| --- | --- |
| `app/trading/` | Worker, runtime, funding/scheduling, order and withdrawal reconciliation |
| `app/exchanges/` | Kraken/Bitvavo adapters, transport and scoped read caches |
| `app/data/` | Persistent storage, activity ledger, analytics and Parqet CSV |
| `app/webpage/` | HTTPS, reporting orchestration, HTML/CSS/JavaScript and translations |
| `app/core/` | Configuration, planning rules, security, logging and health checks |

Docker starts `python -m app`. CI tests the code and publishes the container image to GHCR.

## Storage and account boundaries

The named volume `bitcoin-dca-webui-data` mounts at `/webui-data`:

- `config.json`: settings, API credentials and hashed login password.
- `state.json`: schedule, funding checkpoints and pending transactions.
- `controls.json`: durable pause and optional UTC expiry, independent of monthly scheduling.
- `.restore-journal/`: temporary durable rollback copies during restore.
- `activity.sqlite3`: activity and historical FX cache.
- Other files: dashboard snapshot, `report-preferences.json`, first-start timestamp, heartbeat and `tls/` certificates/keys.

JSON writes use private temporary files, atomic replacement and filesystem synchronization. SQLite writes are transactional. Full backups include the saved report start preference and installation timestamp; restore reloads the in-memory installation default too. The Backup tab holds the account and ledger locks while SQLite's backup API captures committed WAL data. A versioned ZIP_STORED archive uses an exact file allowlist, SHA-256 manifest and bounded payloads; scrypt derives an AES-256-GCM key from the backup password. Encrypted archives are returned directly for download and are not retained in the volume. Private plaintext staging directories can remain in the volume after an abrupt process kill; protect the volume like its existing plaintext configuration.

Restore requires current-password reauthentication and rejects queued/unresolved financial work, conflicting Activity/account bindings and archived pending requests. Full restore requires the archived ledger to contain all existing records unchanged and rejects a rewind of the last order timestamp. Activity-only restore merges validated records and legacy account metadata into the application's existing schema; archived SQL and caches are never installed. A durable rollback journal precedes multi-file changes. Failure rolls back; startup rolls back an interrupted restore before loading settings. An unreadable journal prevents startup. Successful restore forces persistent pause, invalidates sessions and requires the normal read-only exchange gate before future transactions. Local TLS certificates remain unchanged. Stop the container when making an independent full-volume filesystem backup.

Exchange, currency and active API-key fingerprints separate scheduling/account state and export cycles. Changing the active key is treated as a new account, even for a key rotation; historical activity remains. Secret-only rotation preserves the binding. Unresolved transactions block account changes.

## Execution and recovery

- After startup delay, verify open orders and BTC withdrawals before new transactions. Saved pending requests are reconciled; uncertain non-idempotent submissions are not blindly repeated.
- An explicit pause gates all new buys and withdrawals, including simulation, manual confirmation and retries. Read-only account checks and order/withdrawal reconciliation continue. The pause switch applies immediately and does not reset purchase deadlines.
- Purchase interval = UTC time from the last purchase to the active deposit deadline ÷ `(affordable purchases + 1)`, minimum 60 seconds. Fees and exchange limits apply; the final purchase can use the remaining budget.
- Deposit dates use the configured timezone and local time. Short months use their last day; daylight-saving gaps move forward and repeated times use the first occurrence.
- Booked fiat increases trigger bounded API verification. Released order holds are not deposits. Confirmed early deposits advance the deadline; overdue deposits remain pending. Sale proceeds require matching account-history evidence. Unknown credits or incomplete history keep automatic transactions paused; a timeout never confirms funding.
- Forecasts use saved balances/prices and assumed monthly deposits. Dashboard polling revalues reports without changing exchange-check deadlines or trading.
- Interrupted settings writes pause trading until durable configuration is verified. SIGTERM/SIGINT stop new work and allow up to 45 seconds for the active worker operation; Compose allows 60 seconds before termination.

## HTTPS and session security

Only deployment parameters use `.env`: `WEB_UI_PORT` (default `6890`), `WEB_UI_TLS_HOSTS` and `LOG_LEVEL` (default `INFO`). All application settings come from the web configuration.

HTTPS uses a volume-persisted local certificate authority. Set `WEB_UI_TLS_HOSTS` to every server IP/hostname used, then copy its public certificate:

```sh
docker cp bitcoin-dca:/webui-data/tls/ca.pem ./bitcoin-dca-ca.pem
```

Trust this certificate authority on each client device. Never distribute private keys. Changing hosts renews the server certificate; keeping the volume preserves the CA. A new volume requires trusting its new CA.

Sessions last 30 minutes and use `Secure`, `HttpOnly` and `SameSite=Strict` cookies. Login/password-confirmation attempts are limited. Sensitive settings require the current password; changing login credentials invalidates sessions. API secrets are stored unencrypted with owner-only permissions: protect the Docker host, volume and backups. The container runs as root.

## Monitoring

```sh
docker compose logs --tail=200
```

INFO records scheduling, transactions and explicit UI actions; WARNING covers recoverable failures; ERROR covers unexpected or uncertain outcomes; DEBUG adds request details and repeated waiting states. Logs can contain balances and transaction IDs.

Heartbeat and Docker health checks run every five minutes. A supervisor exits after a ten-minute worker stall so Docker can restart it. Health measures worker responsiveness, not successful trading; Docker’s unhealthy status alone does not restart the container.

## Development checks

Python 3.12+ and Node 22+:

```sh
python -m pip install requests==2.34.2 cryptography==50.0.2 -r requirements-dev.txt
ruff check app
ruff format --check app
mypy
python tests/run_tests.py
node tests/test_dashboard.cjs
node tests/test_settings.cjs
npm ci
npx playwright install --with-deps chromium webkit
npm run test:browser
```

Tests use synthetic exchange data; Chromium/WebKit cover desktop/mobile layout and interactions. No real transactions are submitted. Browser tools are development-only and are excluded from the runtime image.
