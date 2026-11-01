# Changelog

Unreleased changes followed by historical version notes, newest first. Dates use Europe/Berlin. Earlier notes are retained even when their GitHub releases or tags are no longer available.

## Unreleased

- Refresh dashboard BTC prices with regular account checks instead of browser-triggered requests.
- Document deposit-history read permissions and correct Bitvavo private-request signing.

- Verify fiat deposits against Kraken’s booked ledger and Bitvavo’s completed deposit history; display confirmed entries without changing BTC totals or Parqet exports.
- Remove the initial status-check text and consolidate insufficient-funds status into Waiting for deposit.

- Recognize API-confirmed early funding on the deposit day and persist the next monthly budget deadline.
- Keep normal order submission and confirmation green as Bot active; simplify German trading mode and Kraken withdrawal target labels.

- Added a labeled traffic-light status beside Settings: green for active operation, amber for waiting/simulation, red for failures; no separate account-age message.
- Simplified Settings into Bot Configuration, Exchange, Dashboard and Login tabs with directly editable credentials and withdrawal targets.
- Made Settings compact and vertically scrollable on all devices, with fixed navigation/save controls and single-column mobile fields.
- Added an unsaved-draft indicator and in-page discard confirmation; inactive withdrawal thresholds retain their saved values.
- Added English/German interface language, localized dates/numbers and volume-saved Light, Dark and Automatic / System appearance. Technical logs remain English.
- Standardized field-title hierarchy, mobile time-input sizing, scrollbar colors and dismiss-button spacing; removed visible focus indicators as requested while retaining keyboard navigation.
- Improved withdrawal confirmations and messages, background-scroll locking, saved view preferences and reporting feedback.
- Explained withdrawal forecasts with approximate remaining BTC/purchases and expandable assumptions; the monthly forecast amount is volume-saved and starts empty without browser imports.
- Kept forecasts available while waiting for deposits, with overdue-funding assumptions explicitly labelled.
- Added deposit time, actual calendar-month and daylight-saving handling; purchase intervals use the last purchase through the next deposit deadline.
- Persisted deposit-wait tracking across restarts. Affordable old funds remain due, and incoming available fiat releases the wait.
- Removed the 0.5% planning buffer and increased the final affordable order to use the remaining fiat budget, allowing for fees and exchange precision.
- Preserved existing account-check deadlines after manual withdrawal previews/confirmations; due checks take priority over queued requests.
- Paused trading after interrupted Settings writes until durable configuration and exchange activity have been verified again.
- Replaced manual account recovery with conservative automatic startup checks, preserving pending transactions and purchase history.
- Bounded HTTPS connections, rechecked sessions at worker execution and safely paginated withdrawal histories.
- Added native HTTPS with a persistent local CA and renewable certificates, 30-minute secure sessions, attempt limits and password confirmation for sensitive changes.
- Restricted persistent-file permissions, shared durable atomic JSON writes and avoided unnecessary exchange reconnections.
- Versioned SQLite initialization so normal reads skip schema work; unsupported newer schemas are rejected safely.
- Added coordinated SIGTERM/SIGINT shutdown and a 60-second Compose stop grace period.
- Organized application packages and separated HTML/CSS/JavaScript from HTTP handlers without frontend dependencies.
- Removed unused helpers and Adaptive DCA; consolidated regression tests and excluded documentation/tests from container builds.
- Corrected mixed-currency handling for failed withdrawals and retained confirmation states in Period Activity.
- Updated and consolidated README and operation documentation to match the current interface and behavior.

## v0.5.0 — 2026-10-30

- Added first-run setup for creating dashboard credentials and configuring the bot.
- Added a Settings dialog for exchange access, purchase parameters, withdrawal targets and dashboard options.
- Added separate credential editors and a review showing highlighted before-and-after changes.
- Added read-only API connection tests with inline feedback.
- Added controls for live trading, automatic/manual withdrawals, Parqet exports, display currency and timezone.
- Added worldwide timezone presets and contextual setting descriptions.
- Moved all persistent data into `bitcoin-dca-webui-data`, preserving settings and transaction state across deployments.
- Removed the host state bind mount and migration code.
- Made the web UI mandatory; bot settings and credentials now come exclusively from the saved web configuration.
- Added confirmation statuses to Period Activity and automatic withdrawal targets to Notes.
- Reset the Period Analysis end time to the current time on each page load.
- Expanded setup and Settings logs without exposing credentials.
- Improved mobile layouts and simplified the deployment configuration and documentation.

## v0.4.2 — 2026-10-30

- improvements in configuration and settings page

## v0.4.1 — 2026-10-30

- improving configuration page

## v0.4.0 — 2026-10-30

- Adding settings menu and configuration assistant

## v0.3.5 — 2026-10-30

- Kept scheduled account checks unchanged after manual withdrawal previews and confirmations, avoiding unnecessary purchase schedule recalculations.
- Added compact dismiss buttons to manual withdrawal and Parqet CSV export messages.
- Unified automatic withdrawal forecast subtitles and subsection spacing.
- Kept activity table height stable by filling unused page rows.

## v0.3.4 — 2026-10-30

- Standardized log levels and reduced routine INFO output.
- Added logs for withdrawal status changes.
- Kept temporary network failures at WARNING without stack traces.
- Preserved INFO logs for purchase scheduling and user actions.

## v0.3.3 — 2026-10-30

- Improved the web UI appearance.

## v0.3.2 — 2026-10-30

- Reworked the application architecture, moving Python runtime modules into `app/`.
- Updated Docker source paths, test entry points and architecture documentation.

## v0.3.1 — 2026-10-30

- Improved visibility in the web UI.

## v0.3.0 — 2026-10-30

Improvements in Web UI
- Added responsive horizontal scrolling with clearer scrollbars and edge indicators.
- Improved loading feedback while preserving existing values during refreshes.
- Added a styled withdrawal confirmation dialog showing destination, gross BTC, fees and net BTC.
- Remembered panel states, date ranges and activity page sizes.
- Standardized numeric alignment and missing-value formatting.

## v0.2.9 — 2026-10-30

- Improved responsive layouts for mobile devices.

## v0.2.8 — 2026-10-29

- Improved the web UI appearance.

## v0.2.7 — 2026-10-29

- Improved the web UI appearance.

## v0.2.6 — 2026-10-29

- Improved the web UI appearance.

## v0.2.5 — 2026-10-29

- No release notes were published.

## v0.2.4 — 2026-10-29

- Improved the web UI appearance.

## v0.2.3 — 2026-10-29

- Improved the web UI appearance.

## v0.2.2 — 2026-10-29

- Improved the web UI appearance.

## v0.2.1 — 2026-10-29

- Improved the web UI appearance.

## v0.2.0 — 2026-10-29

- Reworked the web UI.

## v0.1.32 — 2026-10-29

- Improved the web UI appearance.

## v0.1.31 — 2026-10-29

- Improved the web UI appearance.

## v0.1.30 — 2026-10-29

- Improved the web UI appearance.

## v0.1.29 — 2026-10-29

- Improved the automatic withdrawal date estimate in the web UI.

## v0.1.28 — 2026-10-29

- Improved the web UI appearance.

## v0.1.27 — 2026-10-29

- Improved the web UI appearance.

## v0.1.26 — 2026-10-29

- Improved the web UI appearance.

## v0.1.25 — 2026-10-29

- Added an estimated automatic withdrawal countdown to the web UI when applicable.

## v0.1.24 — 2026-10-29

- Improved the web UI appearance.

## v0.1.23 — 2026-10-29

- Improved the web UI appearance.

## v0.1.22 — 2026-10-29

- Improved the web UI appearance.

## v0.1.21 — 2026-10-29

- No release notes were published.

## v0.1.20 — 2026-10-28

- Improved the web UI appearance.

## v0.1.19 — 2026-10-28

- Improved the web UI appearance.

## v0.1.18 — 2026-10-28

- Calculate purchase intervals from the last purchase to the next deposit date, using the current time only when no previous purchase exists.
- Recalculate saved schedules with the corrected rule and preserve the last purchase time across monthly resets.

## v0.1.17 — 2026-10-28

Changes in the Parqet CSV generation logic:
- Restricted Parqet CSV exports to the complete interval between the previous confirmed withdrawal and the last confirmed withdrawal in the selected date range.
- Excluded purchases made after the ending withdrawal, even when the selected range includes them.
- Included the full withdrawal interval when the selected start date falls inside it.
- For the first withdrawal, included all preceding recorded real purchases.
- Updated the README, UI guidance, and illustration.

## v0.1.16 — 2026-10-28

- Improved the web UI appearance.

## v0.1.15 — 2026-10-28

- Improved the web UI appearance.

## v0.1.14 — 2026-10-28

- Improved the web UI appearance.

## v0.1.13 — 2026-10-28

- Improved the web UI appearance.

## v0.1.12 — 2026-10-28

- Improved the web UI appearance.

## v0.1.11 — 2026-10-28

- Made all superscript footnote numbers consistently white.
- Fixed currency-rate parsing that incorrectly hid monetary totals in EUR-only reports.
- Improved the currency conversion error message.
- Restored startup INFO logs showing the last purchase, elapsed time, calculated interval, next purchase time, and remaining wait.
- Updated the README and web UI illustration.

## v0.1.10 — 2026-10-28

- Improved the web UI appearance.

## v0.0.9 — 2026-10-28

- Distinguished definitive exchange rejections from uncertain submission outcomes.
- Fixed BTC balance calculations to include network fees.
- Added withdrawal status tracking; only confirmed withdrawals are included in Parqet exports.
- Improved market-rule refreshes, fee-aware budgeting, and mixed-currency reports.
- Reduced API requests and added time-limited price caching.
- Migrated activity history to SQLite with server-side pagination.
- Added a task queue for manual withdrawals.
- Added periodic account checks, worker supervision, and a Docker healthcheck.
- Fixed date-range initialization and removed unused code.
- Updated the README, web UI preview, and documented limitations.

## v0.0.8 — 2026-10-28

- Improved the web UI appearance.

## v0.0.7 — 2026-10-28

- Repositioned the manual withdrawal button in the web UI.

## v0.0.6 — 2026-10-28

- Renamed the application and web UI to Bitcoin DCA Bot.
- Restricted purchases and withdrawals to Bitcoin (BTC).
- Removed BASE_ASSET and configurable cryptocurrency support.
- Limited dashboard activity and Parqet exports to BTC records.
- Updated the README and example screenshots.

## v0.0.5 — 2026-10-28

- Moved “Purchase schedule” into its own main panel alongside “Bot configuration”.
- Added a linked footnote explaining how purchase intervals and the next purchase time are calculated.

## v0.0.4 — 2026-10-28

- Simplified dashboard labels and renamed “Bot settings” to “Bot configuration”.
- Separated the purchase schedule from other configuration details.
- Moved date filters above the selected period summary and improved visual grouping.
- Moved explanatory text and the local-access notice into linked footnotes.
- Removed the exchange label above the title and updated the subtitle.
- Matched the withdrawal interval selector width to the date fields.
- Added clear CSV export messages when the selected period has no withdrawal or real purchase.

## v0.0.3 — 2026-10-28

- Simplified dashboard labels and renamed “Bot settings” to “Bot configuration”.
- Visually separated the purchase schedule from other configuration details.
- Moved date filters above “Selected period summary” and added a clearer visual separation between portfolio information and period analysis.

## v0.0.2 — 2026-10-28

- Added configurable live-order verification for Kraken and Bitvavo via `ORDER_STATUS_CHECK_SECONDS`. Open or unresolved orders block further purchases; final fills are recorded after the order ends.
- Added the estimated next purchase time and a live countdown to the dashboard.
- Improved Kraken read-request retries and endpoint logging without automatically resending orders or withdrawals.
- Improved mobile dashboard layouts and reduced date-range typography for clearer display on small screens.

## v0.0.1 — 2026-10-27

- No release notes were published.

