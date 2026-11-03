"""Reporting request validation and export/analysis orchestration, independent of HTTP."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

Activity = dict[str, Any]
ReportRead = tuple[list[Activity], int, int, list[dict[str, Any]], Decimal]


def period(query: Mapping[str, Sequence[str]]) -> tuple[int, int]:
    try:
        start_ms = int(query["start"][0])
        end_ms = int(query["end"][0])
    except (KeyError, ValueError, IndexError):
        raise ValueError("start and end must be Unix timestamps in milliseconds") from None
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    if start_ms < 0 or end_ms <= start_ms or end_ms > now_ms + 60_000:
        raise ValueError("Invalid period; end must be after start and not in the future")
    return start_ms, end_ms


@dataclass(frozen=True)
class ReportService:
    """Explicit ledger and formatting boundaries, with no exchange submissions."""

    interval_records: Callable[[int, int], list[Activity]]
    aggregate_rows: Callable[[list[Activity], str], list[dict[str, str]]]
    format_csv: Callable[[list[dict[str, str]]], str]
    read_report: Callable[..., ReportRead]
    read_snapshot: Callable[[], dict[str, Any]]
    build_report: Callable[[Mapping[str, Any], list[dict[str, Any]], dict[str, Any], list[Activity]], dict[str, Any]]

    def export(self, start: int, end: int, exchange: str) -> tuple[str, int]:
        selected_records = self.interval_records(start, end)
        real_records = [record for record in selected_records if not record.get("simulated")]
        if not any(
            record["row"].get("type") == "TransferOut" and record.get("withdrawalStatus") == "completed"
            for record in real_records
        ):
            raise ValueError(
                "No confirmed bot-recorded BTC withdrawal was found in the selected period. "
                "The Parqet export requires a purchase and a withdrawal. "
                "Choose a period that includes a withdrawal, or export after your first withdrawal."
            )
        if not any(record["row"].get("type") == "Buy" for record in real_records):
            raise ValueError(
                "No real bot purchase was found since the previous confirmed withdrawal. "
                "The Parqet export requires a real purchase and a withdrawal; purchases made in Simulation are excluded."
            )
        rows = self.aggregate_rows(selected_records, exchange)
        if not rows:
            raise ValueError(
                "The selected period must contain at least one real purchase and one bot-recorded BTC withdrawal."
            )
        return self.format_csv(rows), len(rows)

    def analytics(
        self, start: int, end: int, page: int, limit: int, settings: Mapping[str, Any], kind: str = "", status: str = ""
    ) -> dict[str, Any]:
        records, total, page, totals, balance = (
            self.read_report(start, end, page, limit, kind=kind, status=status)
            if kind or status
            else self.read_report(start, end, page, limit)
        )
        snapshot = self.read_snapshot()
        snapshot["trackedBtc"] = str(balance)
        if snapshot.get("quote") not in (None, settings["quote"]):
            snapshot["price"] = "0"
        result = self.build_report(settings, totals, snapshot, records)
        limit = max(1, min(1000, limit))
        result["pagination"] = {
            "page": page,
            "pageSize": limit,
            "total": total,
            "pages": max(1, (total + limit - 1) // limit),
        }
        return result
