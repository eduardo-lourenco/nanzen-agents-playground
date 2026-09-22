# Meridian Billing Summary Implementation Plan

## Goal

Produce a correct billing summary for Meridian Health while keeping the change focused.
The implementation should make data completeness explicit and move financial reconciliation
into deterministic code.

This iteration will not attempt full semantic validation of the generated PDF. Reconciliation
will be tested independently, and the final PDF will be inspected manually.

## Plan For Now

### 1. Implement Structured Context Retrieval and Its Tests

Update `src/challenge/tools/csv_reader.py` so agents receive structured data instead of a
pipe-delimited table.

The tool should:

- Change `CSVReaderTool.output_type` from `string` to `object`.
- Add an `offset` input.
- Return a dictionary with the following shape:

  ```python
  {
      "rows": [...],
      "offset": 0,
      "returned": 50,
      "total_matching": 154,
      "has_more": True,
      "next_offset": 50,
  }
  ```

- Validate that `offset >= 0` and `limit > 0`.
- Raise errors for invalid input or unavailable sources instead of returning strings prefixed
  with `ERROR:`.
- Return valid pagination metadata when no rows match.
- Explain in the tool description that callers must continue while `has_more` is true when a
  task requires complete retrieval.
- Keep page sizes bounded instead of replacing the current limit with another arbitrary large
  limit.

Add or update retrieval tests as part of this step. Verify that:

- Tool output is a structured dictionary containing rows and pagination metadata.
- The first page reports `has_more=True` when additional records exist.
- A subsequent offset returns a different page.
- The final page reports `has_more=False` and `next_offset=None`.
- Invalid limits and offsets fail clearly.
- Empty results return a valid result with zero rows and complete metadata.
- Account filtering still works.

Do not move to billing reconciliation until these tests pass.

### 2. Implement Deterministic Billing Reconciliation and Its Tests

Add `src/challenge/tools/billing_reconciliation.py`. Keep the financial logic in a pure,
testable reconciliation function and expose it through a thin `BillingSummaryTool` adapter
named `reconcile_billing`.

The tool input should be:

```python
{"account_id": "MERID-001"}
```

The result should have a compact, structured shape such as:

```python
{
    "account_id": "MERID-001",
    "as_of": "2026-03-01 09:05:00",
    "currency": "EUR",
    "amount_basis": "gross, VAT-inclusive",
    "summary": {...},
    "invoices": [...],
    "exceptions": [...],
}
```

Implement these reconciliation rules:

- Read the complete billing source, without relying on a model to paginate it.
- Identify invoices belonging to the requested account.
- Include events with a blank `account_id` when they refer to one of those invoice IDs. This is
  required to recover the payment for `INV-2025-MH-024`.
- Group events by invoice ID.
- Use `Decimal` for all financial calculations.
- Use the earliest `invoice_issued` event as the canonical issuance.
- Flag duplicate or conflicting issuance events rather than silently discarding the conflict.
- Aggregate partial payments for each invoice.
- Exclude payment events marked as duplicate overpayments from applied invoice payments.
- Record completed refunds and duplicate payments as exceptions without counting them as
  additional invoice settlement.
- Determine paid status from the reconciled invoice balance.
- Calculate lateness from the due date and final settlement date rather than trusting narrative
  text.
- Classify open invoices as `overdue` or `not_due` using the latest included billing event as the
  data cutoff.
- Keep credits and adjustments separate when they are not formally incorporated into an issued
  invoice.
- Flag the EUR 1,854 goodwill adjustment as pending because no credit note has been issued.
- Return monetary values as two-decimal strings across the tool boundary.

Add reconciliation tests as part of this step. The Meridian fixture should establish these
golden results as of `2026-03-01 09:05:00`:

| Metric | Expected value |
| --- | ---: |
| Unique invoices | 28 |
| Gross invoiced | EUR 509,852.11 |
| Applied invoice payments | EUR 472,684.95 |
| Open balance | EUR 37,167.16 |
| Fully paid invoices | 26 |
| Paid-late invoices | 10 |
| Overdue | `INV-2025-MH-023`, EUR 18,583.58 |
| Open but not due | `INV-2026-MH-028`, EUR 18,583.58 |
| Pending adjustment | EUR 1,854.00 |

Also verify that:

- `INV-2025-MH-024` is paid despite the blank account ID on its payment.
- Split payments reconcile to their invoice totals.
- The duplicate payment and completed refund for `INV-2024-MH-006` do not overstate payments.
- The conflicting issuance for `INV-2025-MH-022` is surfaced as an exception.
- The delayed SLA credit is represented without double-subtracting it from invoiced totals.

Do not register the tool with the agent until the pure reconciliation tests pass.

### 3. Register the Tool and Tighten the Billing Task

Update `src/challenge/tools/__init__.py` and `src/challenge/agent.py` to export and instantiate
`BillingSummaryTool` alongside the existing tools.

Update only the `billing_summary` task in `src/challenge/tasks.py`. Keep the prompt concise and
require the agent to:

- Call `reconcile_billing(account_id="MERID-001")`.
- Use the returned figures and invoice rows without recomputing them.
- Include every reconciled invoice in the report.
- State the data cutoff and that amounts are gross and VAT-inclusive.
- Separate overdue balances from open invoices that are not yet due.
- Include returned exceptions and reconciliation assumptions.
- Use factual, customer-appropriate wording without speculative internal explanations.
- Create exactly `billing_summary_merid001.pdf`.

Do not duplicate detailed accounting rules in the prompt. Those rules belong in the tested
tool.

Add focused configuration tests in this step to confirm that:

- `reconcile_billing` is available to `ActorAgent`.
- The billing task declares the expected output filename.

### 4. Verify the Complete Flow

Run the normal project checks:

```bash
make style
make test
make run ARGS="--task billing_summary"
```

Confirm that the report is created. Inspect `output/billing_summary_merid001.pdf` manually and
verify that it contains:

- 28 invoice rows.
- The `2026-03-01 09:05:00` data cutoff.
- EUR 509,852.11 gross invoiced.
- EUR 472,684.95 in applied invoice payments.
- EUR 37,167.16 open.
- One overdue invoice and one open invoice that is not yet due.
- The duplicate issuance and pending adjustment disclosures.

If the deterministic tests pass but the PDF does not contain those facts, treat the task as
incomplete even though semantic report validation is not automated in this iteration.

## Definition Of Done For This Iteration

- Context retrieval is structured and cannot truncate silently.
- Financial reconciliation is deterministic, uses exact decimal arithmetic, and has golden
  tests.
- The model uses reconciled results rather than generating accounting logic.
- The generated PDF matches the deterministic Meridian results on manual inspection.
- Full semantic report validation and cross-source validation remain explicitly deferred.

## Plan For Later

### Semantic Report Validation

- Validate the structured report specification against reconciliation output before rendering.
- Check invoice count, totals, statuses, cutoff, and mandatory disclosures automatically.
- Generate a machine-readable report manifest or sidecar JSON so validation does not depend on
  parsing PDF text.
- Add a final-answer gate that prevents delivery when required financial facts are absent or
  inconsistent.

### Execution Postconditions

The runner currently treats any returned final answer as success. Add execution postconditions
without attempting to validate the report's financial contents yet.

- Record successful reconciliation only after `BillingSummaryTool` completes.
- Record report creation only after `PDFReportTool` writes a non-empty file.
- Raise exceptions for failed report input or PDF generation rather than returning error-looking
  strings that an agent can mistake for success.
- Add task metadata declaring required tools and the expected report filename.
- After the agent returns, verify that required tools succeeded and that the expected non-empty
  report exists under `output/`.
- Report `[FAIL]` when a postcondition fails and include verified tools and artifact paths in logs.
- Test missing, failed, and successful tool calls plus missing and empty report artifacts.

### Broader Financial Evals

- Add synthetic ledger fixtures for chargebacks, multiple currencies, corrections,
  overpayments, partial credits, malformed records, and conflicting account ownership.
- Add regression evals that score financial correctness and factual completeness separately from
  report-writing quality.
- Add escalation rules for unresolved issuance conflicts, unsupported adjustments, and other
  conditions that should block customer delivery.
- Detect payment reminders sent after final settlement and surface them as billing workflow
  exceptions. For example, `INV-2025-MH-022` received a second reminder after its payment and
  reconciliation completed.

### Cross-Source Reconciliation

- Reconcile billing against contracts and purchase orders.
- Incorporate materially relevant support, CRM, and email context.
- Investigate the post-expiry billing and auto-renewal dispute before making a broader
  customer-facing account assessment.
- Preserve provenance so each reported conclusion can be traced to its source records.

### Observability and Performance

- Capture the full agent run result, including model ID, prompt version, tool calls, step count,
  token usage, latency, source cutoff, and artifact checksum.
- Persist a compact run manifest for debugging and auditability.
- Track retrieval page counts and reconciliation warnings.
- Evaluate whether `CodeAgent` is still appropriate after calculations move into tools, or
  whether a simpler tool-calling agent would reduce code-format failures, latency, and cost.

### Report Hardening

- Validate report section schemas and table dimensions.
- Constrain output paths to the configured output directory.
- Escape untrusted text before passing it to ReportLab.
- Use atomic file writes.
- Improve wrapping and widths for wide invoice tables.
- Fail explicitly when requested report elements cannot be rendered.
