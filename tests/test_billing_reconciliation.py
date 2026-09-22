"""Tests for deterministic billing reconciliation."""

from challenge.tasks import TASKS
from challenge.tools.billing_reconciliation import BillingSummaryTool, reconcile_billing


class TestBillingReconciliation:
    def test_meridian_golden_summary(self):
        """Meridian's complete event ledger reconciles to known totals."""
        result = reconcile_billing("MERID-001")

        assert result["account_id"] == "MERID-001"
        assert result["as_of"] == "2026-03-01 09:05:00"
        assert result["currency"] == "EUR"
        assert result["amount_basis"] == "gross, VAT-inclusive"
        assert result["summary"] == {
            "unique_invoices": 28,
            "gross_invoiced": "509852.11",
            "applied_invoice_payments": "472684.95",
            "open_balance": "37167.16",
            "fully_paid_invoices": 26,
            "paid_late_invoices": 10,
            "overdue_invoices": 1,
            "not_due_invoices": 1,
        }

    def test_payment_with_blank_account_id_is_matched_by_invoice(self):
        """Payments linked by a known invoice ID are not lost to malformed account data."""
        result = reconcile_billing("MERID-001")
        invoice = next(
            item for item in result["invoices"] if item["invoice_id"] == "INV-2025-MH-024"
        )

        assert invoice["paid"] == "18583.58"
        assert invoice["balance"] == "0.00"
        assert invoice["status"] == "paid"
        assert any(
            item["type"] == "payment_matched_by_invoice_id"
            and item["invoice_id"] == "INV-2025-MH-024"
            for item in result["exceptions"]
        )

    def test_invoice_statuses_and_exceptions(self):
        """The reconciler handles duplicate issuances, refunds, partial payments,
        and open items."""
        result = reconcile_billing("MERID-001")
        invoices = {item["invoice_id"]: item for item in result["invoices"]}
        exception_types = {item["type"] for item in result["exceptions"]}

        assert invoices["INV-2025-MH-021"]["paid"] == "18583.58"
        assert invoices["INV-2025-MH-021"]["status"] == "paid_late"
        assert invoices["INV-2025-MH-022"]["invoiced"] == "18583.58"
        assert invoices["INV-2025-MH-022"]["balance"] == "0.00"
        assert invoices["INV-2025-MH-023"]["status"] == "overdue"
        assert invoices["INV-2025-MH-023"]["balance"] == "18583.58"
        assert invoices["INV-2026-MH-028"]["status"] == "not_due"
        assert invoices["INV-2026-MH-028"]["balance"] == "18583.58"
        assert {
            "conflicting_invoice_issuance",
            "duplicate_payment",
            "completed_refund",
            "pending_adjustment",
        } <= exception_types

    def test_tool_returns_the_reconciled_result(self):
        """The agent-facing tool exposes the same deterministic reconciliation result."""
        result = BillingSummaryTool().forward(account_id="MERID-001")

        assert result["summary"]["open_balance"] == "37167.16"

    def test_misdirected_payment_return_is_resolved(self):
        """Returned invoice-less payments are not left as unresolved exceptions."""
        result = reconcile_billing("MERID-001")
        resolved = [
            item for item in result["exceptions"] if item["type"] == "resolved_misdirected_payment"
        ]

        assert len(resolved) == 1
        assert "847.50" in resolved[0]["message"]
        assert "2025-04-28" in resolved[0]["message"]
        assert not any(
            item["type"] == "unmatched_payment" and "847.50" in item["message"]
            for item in result["exceptions"]
        )
        assert result["summary"]["open_balance"] == "37167.16"

    def test_billing_task_uses_reconciliation_output(self):
        """The billing task directs the agent to use the deterministic tool."""
        task = next(task for task in TASKS if task["name"] == "billing_summary")

        assert "reconcile_billing" in task["prompt"]
        assert "billing_summary_merid001.pdf" in task["prompt"]
