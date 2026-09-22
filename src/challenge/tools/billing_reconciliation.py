"""Deterministic reconciliation for invoice-event billing data."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from smolagents import Tool

from challenge.tools.csv_reader import read_csv_source

PAGE_SIZE = 100


def _read_all_billing_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    offset = 0

    while True:
        page = read_csv_source("billing", limit=PAGE_SIZE, offset=offset)
        rows.extend(page["rows"])
        if not page["has_more"]:
            return rows
        offset = page["next_offset"]


def _amount(row: dict[str, str]) -> Decimal:
    return Decimal(row["amount"] or "0")


def _money(amount: Decimal) -> str:
    return f"{amount:.2f}"


def _event_time(row: dict[str, str]) -> datetime:
    return datetime.fromisoformat(row["timestamp"])


def reconcile_billing(account_id: str) -> dict[str, object]:
    """Reconcile complete invoice-event history for one account."""
    all_rows = _read_all_billing_rows()
    invoice_ids = {
        row["invoice_id"]
        for row in all_rows
        if row["account_id"] == account_id
        and row["event_type"] == "invoice_issued"
        and row["invoice_id"]
    }
    relevant_rows = [
        row
        for row in all_rows
        if row["account_id"] == account_id or row["invoice_id"] in invoice_ids
    ]

    if not relevant_rows:
        raise ValueError(f"No billing records found for account_id='{account_id}'")

    currencies = {
        row["currency"]
        for row in relevant_rows
        if row["event_type"] == "invoice_issued" and row["invoice_id"] in invoice_ids
    }
    if len(currencies) != 1:
        raise ValueError(
            "Billing reconciliation requires exactly one invoice currency; "
            f"found {sorted(currencies)}"
        )
    currency = currencies.pop()
    as_of = max(_event_time(row) for row in relevant_rows)
    events_by_invoice: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in relevant_rows:
        if row["invoice_id"] in invoice_ids:
            events_by_invoice[row["invoice_id"]].append(row)

    invoices: list[dict[str, object]] = []
    exceptions: list[dict[str, str]] = []
    applied_payments = Decimal("0")
    gross_invoiced = Decimal("0")

    for invoice_id in sorted(invoice_ids):
        events = sorted(events_by_invoice[invoice_id], key=_event_time)
        issuances = [row for row in events if row["event_type"] == "invoice_issued"]
        canonical_issuance = issuances[0]
        issued_amount = _amount(canonical_issuance)
        gross_invoiced += issued_amount

        issuance_amounts = {_amount(row) for row in issuances}
        if len(issuance_amounts) > 1:
            exceptions.append(
                {
                    "type": "conflicting_invoice_issuance",
                    "invoice_id": invoice_id,
                    "message": (
                        f"Used earliest issuance of {currency} {_money(issued_amount)}; "
                        "later issuance records conflict: "
                        f"{', '.join(_money(amount) for amount in sorted(issuance_amounts))}."
                    ),
                }
            )

        payments = [
            row
            for row in events
            if row["event_type"] == "payment_received" and row["status"] != "overpayment"
        ]
        duplicate_payments = [
            row
            for row in events
            if row["event_type"] == "payment_received" and row["status"] == "overpayment"
        ]
        for duplicate in duplicate_payments:
            exceptions.append(
                {
                    "type": "duplicate_payment",
                    "invoice_id": invoice_id,
                    "message": (
                        f"Excluded duplicate payment of {currency} {_money(_amount(duplicate))}."
                    ),
                }
            )

        completed_refunds = [row for row in events if row["event_type"] == "refund_completed"]
        for refund in completed_refunds:
            exceptions.append(
                {
                    "type": "completed_refund",
                    "invoice_id": invoice_id,
                    "message": f"Completed refund of {currency} {_money(abs(_amount(refund)))}.",
                }
            )

        payment_total = sum((_amount(row) for row in payments), Decimal("0"))
        paid_amount = min(payment_total, issued_amount)
        applied_payments += paid_amount
        balance = issued_amount - paid_amount

        settled_at: date | None = None
        cumulative_paid = Decimal("0")
        for payment in payments:
            cumulative_paid += _amount(payment)
            if cumulative_paid >= issued_amount:
                settled_at = date.fromisoformat(payment["paid_date"])
                break

        due_date = date.fromisoformat(canonical_issuance["due_date"])
        if balance == 0:
            days_late = max((settled_at - due_date).days, 0) if settled_at else 0
            status = "paid_late" if days_late else "paid"
        elif due_date < as_of.date():
            days_late = None
            status = "overdue"
        else:
            days_late = None
            status = "not_due"

        blank_account_payments = [row for row in payments if not row["account_id"]]
        if blank_account_payments:
            exceptions.append(
                {
                    "type": "payment_matched_by_invoice_id",
                    "invoice_id": invoice_id,
                    "message": (
                        "Included payment with blank account_id because its invoice ID belongs "
                        "to this account."
                    ),
                }
            )

        invoices.append(
            {
                "invoice_id": invoice_id,
                "invoice_date": canonical_issuance["timestamp"][:10],
                "due_date": canonical_issuance["due_date"],
                "invoiced": _money(issued_amount),
                "paid": _money(paid_amount),
                "balance": _money(balance),
                "status": status,
                "days_late": days_late,
                "final_payment_date": settled_at.isoformat() if settled_at else None,
            }
        )

    unallocated_returns = [
        row
        for row in relevant_rows
        if not row["invoice_id"]
        and row["event_type"] == "refund_completed"
        and row["status"] in {"returned", "refund_complete"}
    ]
    matched_return_ids: set[str] = set()

    for row in sorted(relevant_rows, key=_event_time):
        if row["event_type"] == "payment_received" and not row["invoice_id"]:
            matching_return = next(
                (
                    refund
                    for refund in unallocated_returns
                    if refund["event_id"] not in matched_return_ids
                    and refund["account_id"] == row["account_id"]
                    and refund["currency"] == row["currency"]
                    and abs(_amount(refund)) == _amount(row)
                    and _event_time(refund) > _event_time(row)
                ),
                None,
            )
            if matching_return:
                matched_return_ids.add(matching_return["event_id"])
                exceptions.append(
                    {
                        "type": "resolved_misdirected_payment",
                        "invoice_id": "",
                        "message": (
                            f"Misdirected payment of {currency} {_money(_amount(row))} "
                            f"was returned on {matching_return['timestamp'][:10]} and did not "
                            "affect invoice balances."
                        ),
                    }
                )
            else:
                exceptions.append(
                    {
                        "type": "unmatched_payment",
                        "invoice_id": "",
                        "message": (
                            f"Unmatched payment of {currency} {_money(_amount(row))} "
                            "requires review."
                        ),
                    }
                )
        if (
            row["event_type"] == "adjustment"
            and abs(_amount(row)) >= Decimal("1")
            and not row["credit_note_ref"]
        ):
            exceptions.append(
                {
                    "type": "pending_adjustment",
                    "invoice_id": row["invoice_id"],
                    "message": (
                        f"{currency} {_money(abs(_amount(row)))} adjustment has no credit note "
                        "and remains "
                        "pending reconciliation."
                    ),
                }
            )

    open_balance = sum((Decimal(invoice["balance"]) for invoice in invoices), Decimal("0"))
    paid_invoices = [invoice for invoice in invoices if invoice["status"].startswith("paid")]
    overdue_invoices = [invoice for invoice in invoices if invoice["status"] == "overdue"]
    not_due_invoices = [invoice for invoice in invoices if invoice["status"] == "not_due"]

    return {
        "account_id": account_id,
        "as_of": as_of.isoformat(sep=" "),
        "currency": currency,
        "amount_basis": "gross, VAT-inclusive",
        "summary": {
            "unique_invoices": len(invoices),
            "gross_invoiced": _money(gross_invoiced),
            "applied_invoice_payments": _money(applied_payments),
            "open_balance": _money(open_balance),
            "fully_paid_invoices": len(paid_invoices),
            "paid_late_invoices": sum(invoice["status"] == "paid_late" for invoice in invoices),
            "overdue_invoices": len(overdue_invoices),
            "not_due_invoices": len(not_due_invoices),
        },
        "invoices": invoices,
        "exceptions": exceptions,
    }


class BillingSummaryTool(Tool):
    """Tool for deterministic billing reconciliation."""

    name = "reconcile_billing"
    description = (
        "Reconcile the complete billing event ledger for an account. Returns exact, "
        "VAT-inclusive invoice balances, payment status, lateness, data cutoff, and exceptions. "
        "Use its totals and invoice rows directly; do not recompute them in generated code."
    )
    inputs = {
        "account_id": {
            "type": "string",
            "description": "Account to reconcile, for example 'MERID-001'.",
        }
    }
    output_type = "object"

    def forward(self, account_id: str) -> dict[str, object]:
        return reconcile_billing(account_id)
