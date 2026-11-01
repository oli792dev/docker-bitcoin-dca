# Bitcoin DCA Bot

A Docker bot that buys Bitcoin on Kraken or Bitvavo, with optional automatic and manual withdrawals. Purchases are spread across the time until your next monthly deposit. A responsive English/German dashboard provides settings, balances, scheduling, activity and Parqet CSV exports.

<details>
<summary>Dashboard preview</summary>

![Bitcoin DCA Dashboard with fictional data](docs/web-ui-dashboard-screenshot.png)

</details>

## Setup

Requires Docker with Compose, internet access and a Kraken or Bitvavo account.

1. Download the project:

   ```sh
   git clone https://github.com/oli792dev/docker-bitcoin-dca.git
   cd docker-bitcoin-dca
   cp .env.example .env
   ```

2. In `.env`, set `WEB_UI_TLS_HOSTS` to the Docker host IP address or hostname you will use. Multiple addresses are comma-separated. The default port is `6890`.

3. Start the container:

   ```sh
   docker compose up -d --build
   ```

4. Open `https://<docker-host>:6890` and [trust the generated local CA](docs/architecture.md#https-and-session-security). Create login credentials with a password of at least 12 characters. The wizard then guides you through exchange access and bot settings.

Create an exchange API key with these permissions:

| Exchange | Read access | For live purchases | For optional withdrawals |
| --- | --- | --- | --- |
| Kraken | Query Funds; Query Open/Closed Orders & Trades; Data → Query ledger entries | Modify Orders | Withdraw Funds; exact label of a saved Bitcoin withdrawal method |
| Bitvavo | Read-only / View access | Trade digital assets | Withdraw digital assets; verified Bitcoin address and network |

Use Test connection to check balances and deposit-history access without placing transactions. Existing Kraken keys also need Query ledger entries. Keep credentials in the web settings; never commit credentials or `.env`.

In Settings → Bot Configuration, choose the purchase currency, BTC amount, deposit day/time and timezone. An amount of `0` uses the exchange minimum. New installations use Simulation; activate live trading only when ready. Settings also control withdrawals, dashboard language, display currency and appearance. Changes apply after saving.

## How it works

- Account checks refresh balances, BTC prices and scheduling, normally every five minutes. Browser visits do not trigger exchange price requests.
- The purchase interval is the time from the last purchase to the next deposit date/time divided by `(affordable purchases + 1)`. The final affordable purchase uses the remaining fiat, subject to fees and exchange minimums. Small remnants may remain.
- A fiat balance increase triggers API verification of only that deposit window. Confirmed early deposits advance the deadline to the next month; delayed deposits show Waiting for deposit. Older deposit history is not imported.
- Automatic withdrawals compare the value of all available exchange BTC against your threshold. Manual withdrawals require confirmation and use the same saved target. Both require live trading and send the available BTC less withdrawal fees.
- Pending or unverifiable exchange transactions block further submissions until reconciled, including after restarts. Run one bot per exchange account.

Expected monthly deposit affects only the withdrawal forecast; it does not transfer money or change actual purchases. Forecasts assume unchanged prices, fees and future deposits.

## Reports and Parqet

Period Analysis shows purchases, confirmed fiat deposits, withdrawals and fees. From defaults to the first container-start timestamp saved in the volume; To resets to now. Existing volumes establish this timestamp on their first start with this feature.

The Parqet CSV exports one consolidated Buy row for the complete cycle after the previous confirmed withdrawal through the last confirmed withdrawal in the selected range. It uses actual purchase costs and trading fees in EUR and net withdrawn BTC after network fees. Deposits, later purchases and Simulation activity are excluded. A real purchase and confirmed withdrawal are required. Re-importing an export can create duplicates.

## Data and updates

All settings, credentials, activity and state persist in `bitcoin-dca-webui-data`. Reuse and back up this volume. Passwords are hashed; API secrets are stored in its private configuration file, so protect volume access and backups.

After updating the source, run `docker compose up -d --build`. Do not run `docker compose down -v`: it deletes the data volume.

See [Architecture and operation](docs/architecture.md) for HTTPS, storage, backups, logs and health checks, and the [Changelog](docs/CHANGELOG.md) for changes.

Provided as is, without investment or tax advice. Market prices, fees and execution can differ from estimates; verify transactions and exports.
