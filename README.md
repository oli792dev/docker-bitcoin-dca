# Bitcoin DCA Bot

A self-hosted Bitcoin DCA bot for Kraken and Bitvavo, managed through an HTTPS dashboard.

- Automatic purchases spread your fiat budget until the next monthly deposit.
- Simulation, live trading, transaction pause and optional automatic/manual Bitcoin withdrawals.
- Responsive English/German dashboard with balances, schedules, withdrawal forecasts and activity analysis.
- Parqet CSV export and encrypted Full, Activities or Config backups.

<details>
<summary>Dashboard preview</summary>

![Bitcoin DCA Dashboard with fictional data](docs/web-ui-dashboard-screenshot.png)

</details>

## Setup

Requires Docker Compose, internet access and an exchange account. Run one bot per exchange account.

```sh
git clone https://github.com/oli792dev/docker-bitcoin-dca.git
cd docker-bitcoin-dca
cp .env.example .env
```

1. Set `WEB_UI_TLS_HOSTS` in `.env` to your Docker host IP or hostname; separate multiple addresses with commas.
2. Run `docker compose up -d --build`.
3. Open `https://<docker-host>:6890` and [trust the local certificate authority](docs/architecture.md#https-and-session-security).
4. Create a login (password: at least 12 characters). Use the setup wizard to enter your API credentials, test the connection and configure purchases.

Grant these API permissions:

| Exchange | Read access | Live purchases | Optional withdrawals |
| --- | --- | --- | --- |
| Kraken | Query Funds; Query Open/Closed Orders & Trades; Query ledger entries | Modify Orders | Withdraw Funds |
| Bitvavo | Read-only / View | Trade digital assets | Withdraw digital assets |

Enter credentials in the web settings; never commit credentials or `.env`.

## Usage

- Start in Simulation. Enable live trading in Settings for real purchases. Amounts below the exchange minimum, including `0`, use that minimum.
- Configure the monthly deposit day/time and fund the exchange yourself. The bot verifies deposits and adjusts purchases to your available balance. Expected monthly deposit affects only the withdrawal forecast.
- Optional automatic withdrawals use all available exchange BTC, including BTC bought outside the bot. Configure a threshold and target: a saved withdrawal-method label for Kraken, or an address/network for Bitvavo.
- Settings also provides Pause transactions, manual withdrawal and Parqet export. Pausing stops new transactions while account checks continue; manual withdrawals require confirmation and bypass the automatic threshold.

Parqet export consolidates purchases between confirmed withdrawals into one Buy row, using EUR costs including trading fees and net withdrawn BTC. Deposits, later purchases and Simulation are excluded. Check the CSV before importing; repeated imports can create duplicates.

## Backups and updates

Keep the `bitcoin-dca-webui-data` volume: it holds your settings, credentials and history. Protect access to it; API secrets are stored unencrypted.

Settings → Backup offers Full (configuration and activities), Activities only, and Config only backups. Enter your current dashboard password and a separate backup password of at least 12 characters. Download the encrypted file and keep its password safely.

On a fresh installation, restore a Full or Config backup directly on the first setup page, then sign in with the username and password saved in that backup. Only the backup password is needed to restore; no temporary account is required. Activities-only backups cannot initialize an installation. Once an account exists, use Settings → Backup with the current dashboard password. Activities adds history while keeping current settings.

To update:

```sh
git pull
docker compose up -d --build
```

Never run `docker compose down -v`: it deletes the data volume. See [Architecture and operation](docs/architecture.md) for technical details, backup rules, security and troubleshooting.

## Limitations and disclaimer

Bitcoin spot purchases only. Prices, fees and timing may differ from estimates; small fiat remnants can remain. API outages can delay operation. Forecasts are estimates, and activity is not a complete exchange statement.

Provided “as is”, without warranty or investment, tax or legal advice. You are responsible for settings, credentials, transactions, backups and exports. To the extent permitted by law, the maintainer accepts no liability for losses or service failures.
