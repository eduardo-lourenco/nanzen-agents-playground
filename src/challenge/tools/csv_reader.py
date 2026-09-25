"""CSVReaderTool - reads account context from CSV data files.

This tool gives agents access to the shared data context. Each CSV file
represents a table in the system (billing, support tickets, product usage, etc.).
Agents use this tool to query the data they need for their tasks.
"""

from __future__ import annotations

import csv
from pathlib import Path

from smolagents import Tool

# Root data directory (resolved relative to project root)
DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# Registry of available data sources and their CSV files
DATA_SOURCES: dict[str, str] = {
    "accounts": "accounts.csv",
    "billing": "billing.csv",
    "product_usage": "product_usage.csv",
    "support_tickets": "support_tickets.csv",
    "crm_interactions": "crm_interactions.csv",
    "emails": "emails.csv",
    "contracts": "contracts.csv",
    "purchase_orders": "purchase_orders.csv",
    "mailbox_export": "mailbox_export.csv",
}


def read_csv_source(
    source: str,
    account_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Read one page from a CSV data source, optionally filtering by account ID."""
    if source not in DATA_SOURCES:
        raise ValueError(f"Unknown source '{source}'. Available: {sorted(DATA_SOURCES.keys())}")
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero")

    csv_path = DATA_DIR / DATA_SOURCES[source]
    if not csv_path.exists():
        raise FileNotFoundError(f"Data file not found: {csv_path}")

    rows: list[dict[str, str]] = []
    total_matching = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Filter by account_id if the column exists and a filter is given
            if account_id and "account_id" in row:
                if row["account_id"] != account_id:
                    continue
            if offset <= total_matching < offset + limit:
                rows.append(dict(row))
            total_matching += 1

    next_offset = offset + len(rows)
    has_more = next_offset < total_matching

    return {
        "rows": rows,
        "offset": offset,
        "returned": len(rows),
        "total_matching": total_matching,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


class CSVReaderTool(Tool):
    """Tool for agents to query the shared CSV data context."""

    name = "read_context"
    description = (
        "Read one structured page from the shared CSV context.\n"
        "Available sources: accounts, billing, product_usage, support_tickets, "
        "crm_interactions, emails, contracts, purchase_orders, mailbox_export.\n"
        "Use account_id to filter rows for a specific account (e.g. 'MERID-001'). "
        "The result includes rows, total_matching, has_more, and next_offset. Fetch pages "
        "until has_more is false whenever a task requires complete data."
    )
    inputs = {
        "source": {
            "type": "string",
            "description": (
                "The data source to read. One of: accounts, billing, product_usage, "
                "support_tickets, crm_interactions, emails, contracts, purchase_orders, "
                "mailbox_export."
            ),
        },
        "account_id": {
            "type": "string",
            "description": "Filter rows by account_id (e.g. 'MERID-001'). Optional.",
            "nullable": True,
        },
        "limit": {
            "type": "integer",
            "description": "Maximum rows to return. Must be greater than zero. Default: 50.",
            "nullable": True,
        },
        "offset": {
            "type": "integer",
            "description": "Number of matching rows to skip. Must be zero or greater. Default: 0.",
            "nullable": True,
        },
    }
    output_type = "object"

    def forward(
        self,
        source: str,
        account_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, object]:
        effective_limit = limit if limit is not None else 50
        effective_offset = offset if offset is not None else 0
        return read_csv_source(
            source,
            account_id=account_id,
            limit=effective_limit,
            offset=effective_offset,
        )
