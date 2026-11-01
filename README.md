# Bitcoin DCA Bot for Bitvavo and Kraken

A Docker bot that buys Bitcoin on Bitvavo or Kraken, with optional automatic and manual withdrawals. It distributes purchases until the next deposit day using the available fiat balance, current price and exchange order minimums. Bitcoin DCA Dashboard provides scheduling, activity and Parqet CSV exports.

![Bitcoin DCA Dashboard: full-page screenshot with fictional data](docs/web-ui-dashboard-screenshot.png)

*Example full-page screenshot with fictional data.*

## Setup

Requires Docker Engine with Compose, internet access and a Bitvavo or Kraken account.

~~~sh
git clone https://github.com/oli792dev/docker-bitcoin-dca.git
cd docker-bitcoin-dca
~~~

Set `WEB_UI_TLS_HOSTS` in Compose or `.env` to the IP address/hostname you use before starting the container:

~~~sh
docker compose up -d --build
~~~

Open `https://<docker-host-ip>:6890`. Trust the generated local CA on your devices; see [HTTPS setup](docs/architecture.md#https-and-session-security). The setup wizard first creates your username and password (12+ characters), then configures the exchange, API access and purchases. The web UI is always enabled. Bot settings and credentials come only from the saved web configuration; new installations start in dry run.

Settings, beside Log out, has Bot Configuration, Exchange, Dashboard and Login tabs. Edit API access and withdrawal targets directly under Exchange, and login credentials under Login. Review changes before saving; closing with unsaved edits asks for confirmation. Sensitive changes require your current password.

| Exchange | API permissions | Bitcoin withdrawal destination |
| --- | --- | --- |
| [Bitvavo](https://docs.bitvavo.com/docs/get-started/) | Read-only / View access (including deposit history); Trade digital assets for live buys; Withdraw digital assets for withdrawals | Address and network saved and verified on Bitvavo |
| [Kraken](https://support.kraken.com/articles/360000919966-how-to-create-an-api-key) | Query Funds; Data → Query ledger entries (deposit history); Query Open/Closed Orders & Trades; Modify Orders for live buys; Withdraw Funds for withdrawals | Exact label of a saved Bitcoin withdrawal method, not the address itself |

Fiat deposit checks use Kraken’s [deposit ledger](https://docs.kraken.com/api-reference/account-data/get-ledgers-info) (Data → Query ledger entries) or Bitvavo’s [deposit history](https://docs.bitvavo.com/docs/rest-api/get-deposit-history/) (Read-only / View access). Both support fiat deposits. Enable this read permission on existing keys too; failed checks pause new automatic transactions until verification succeeds. No deposit or withdrawal permission is needed just to read deposits.

**Test connection** reads balances and deposit history without trading; progress and results appear beside the button. API access and internet are required even for dry runs. Exchange, credential, currency and trading-mode changes are blocked while transactions remain unresolved.

Settings persist as `config.json` in the named volume `bitcoin-dca-webui-data`; passwords are hashed; API credentials are stored in this private file. Empty API fields keep saved credentials. Protect this file and backups; never commit credentials or `.env`. All runtime state and activity also live in this volume; no host state directory is required. Reuse the same volume on redeployment. After setup and each restart, automatic API checks block new transactions until open exchange orders and Bitcoin withdrawals are closed. Unavailable status keeps the bot paused and is retried.

Compose manages the web server, volumes and restart policy. Docker settings are `WEB_UI_PORT` (6890), `LOG_LEVEL` (INFO) and `WEB_UI_TLS_HOSTS` (comma-separated IP addresses/hostnames). HTTPS is always enabled. Sessions expire after 30 minutes; sensitive changes require your current login password. See [Architecture and operation](docs/architecture.md) for storage and operation.

## Purchases and withdrawals

### Purchase schedule

The bot refreshes the available fiat balance, BTC price and exchange order rules. Estimated order cost includes trading fees, without an additional planning buffer. The last affordable purchase uses the remaining fiat budget, subject to exchange precision and actual execution costs.

**Purchase interval = time from the last purchase to the next deposit date and time ÷ (affordable purchases + 1).**

Set the deposit day and time in Bot Configuration; both use the configured timezone (default time: 00:00). The next purchase is the last purchase time plus that interval. At startup, the bot uses recorded real purchases, falling back to saved execution state. Without previous execution history, the first purchase is due after the startup delay. Unchanged planning inputs retain the saved due time; changed funds, costs or deposit boundaries cause recalculation.

The extra time slot puts the final affordable buy before the deposit boundary. API-confirmed fiat deposits on the deposit day, including before its configured time, move the budget deadline to the next month. Delayed deposits show Waiting for deposit; usable residual fiat is spent first, and new available funding resumes purchases. Small remnants below an executable order may remain.

Live orders are submitted once and verified before another purchase. Open orders and uncertain submissions remain pending across restarts; completed partial fills are recorded at their actual executed amount. Network requests and queued actions can delay execution.

### Withdrawals

Enable automatic withdrawals and live trading in Settings, with withdrawal permissions and a configured destination. Account checks compare all available exchange BTC × current exchange price against the configured withdrawal threshold. This includes BTC acquired outside the bot. When reached, the bot withdraws the available balance, less withdrawal fees.

For a manual withdrawal, click **Withdraw BTC manually** in Current BTC balance, review the destination and amount, then confirm. Live trading and destination permissions are required; the automatic toggle and threshold do not apply.

Submitted withdrawals block further withdrawals until resolved. Uncertain Kraken withdrawals are not automatically resent; Bitvavo may retry the same idempotent request. Verify exchange status before intervening.

## Dashboard and Parqet export

The web UI is fully responsive. Dashboard card rows and tables scroll horizontally when needed; Settings scrolls vertically, with fixed tabs and a fixed save action.

- **Status:** beside Settings, green means active, amber waiting/simulation, and red an account-check or connection failure.
- **Configuration:** exchange, purchase settings and withdrawal target.
- **Activity:** API-confirmed fiat deposits appear with the exchange timestamp and amount. Deposits never affect BTC totals or Parqet exports.
- **Schedule:** exchange balances, purchase timing and estimated automatic withdrawal timing. **Expected monthly deposit** is a volume-saved forecast assumption; it adds funds on each deposit day and recalculates future intervals using actual calendar months. It does not initiate deposits or change trading. Forecasts continue while waiting for deposits, show approximate remaining BTC/purchases, and offer expandable assumptions. Overdue deposits are assumed to arrive now and labelled accordingly.
- **Period Analysis:** date filters, summary, activity status (confirmed, pending, failed or simulated) and CSV export. Activities cannot be deleted through the UI.

Under Settings → Dashboard, choose English/German and Light, Dark or Automatic / System. Language also controls date and number formatting; technical logs remain English. The interface supports keyboard navigation and reduced motion. View preferences are saved in this browser; the To field resets to now on page load. Refreshes preserve existing values; messages can be dismissed. Withdrawal confirmations show the destination, gross BTC, fee and net BTC. Inactive withdrawal thresholds are disabled without erasing their saved value.

Display currency is set to EUR or USD in Settings. BTC prices refresh with balances during account checks (default: every five minutes), independently of browser visits. The purchase-currency price comes from the selected exchange; Kraken ticker data supplies the other display currency. The dashboard shows the last check time.

**Download Parqet CSV** exports one consolidated Buy row for the last confirmed withdrawal in the selected range:

The row uses real purchase costs plus trading fees in EUR, the ending withdrawal’s net BTC after network fees, and its date. USD costs use historical reference rates.

The complete withdrawal cycle is used even when the selected start falls inside it. For the first withdrawal, all preceding recorded real purchases are included. Later purchases, simulations and failed or unconfirmed withdrawals are excluded. At least one real purchase is required. Fees are already included in cost and net BTC; the CSV fee field is zero.

Import using [Parqet’s CSV importer](https://faq.parqet.com/de/articles/870989-csv-import-aktivitaten-aus-einer-eigenen-csv-datei-importieren). Re-exporting a withdrawal can create duplicates.

## Container architecture

See [Architecture and operation](docs/architecture.md) for container components, storage, backups, updates, health checks and logs. See the [Changelog](docs/CHANGELOG.md) for release history.

## Limitations

- **Bitcoin spot market orders only.** Prices, fills and fees can differ from estimates. Withdrawal forecasts assume unchanged prices and costs plus the entered monthly deposits.
- **Available funds drive scheduling.** The bot verifies deposits but cannot determine their intended purpose or reserve funds for other uses. Run one instance per account and persistent state; other trading tools can affect balances.
- **Local history is not a full account statement.** Unrelated trades and transfers are not imported. BTC totals use gross withdrawal debits; exported BTC uses the net amount received.
- **Unresolved transactions require care.** Orders with uncertain outcomes block new purchases. Withdrawals qualify for export only after a unique exchange-history confirmation; the bot does not independently verify the blockchain. Older records may remain unverified. In-memory sessions and confirmation previews are lost on restart; pending submissions persist.
- **Reporting depends on external services.** Exchange API outages can delay price updates; historical USD/EUR conversion uses Frankfurter. Unavailable rates can prevent exports. Reporting supports EUR and USD; displayed conversions use current reference rates.
- **Exports consolidate a time interval.** They do not match individual Bitcoin units or track previous exports. Review each CSV before importing.

## Disclaimer

Provided “as is” without warranty or investment, tax or legal advice. You are responsible for configuration, API credentials, monitoring and verifying transactions and exports. To the fullest extent permitted by law, the maintainer accepts no liability for financial losses, fees, outages, withdrawal errors or data loss. This does not exclude liability that cannot legally be excluded.
