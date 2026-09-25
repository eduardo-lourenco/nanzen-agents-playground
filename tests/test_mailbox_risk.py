"""Mailbox lead retrieval: coverage, context, and honest filter limitations."""

import csv

import pytest

from challenge.tasks import TASKS
from challenge.tools import mailbox_risk


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    monkeypatch.setattr(mailbox_risk, "DATA_DIR", tmp_path)
    path = tmp_path / "mailbox_export.csv"

    def write(rows):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "email_id",
                    "timestamp",
                    "from",
                    "to",
                    "cc",
                    "bcc",
                    "subject",
                    "body",
                    "thread_id",
                    "reply_to_id",
                    "attachments",
                    "importance",
                    "read",
                    "labels",
                    "notes",
                ],
            )
            writer.writeheader()
            for index, row in enumerate(rows):
                writer.writerow(
                    {
                        "email_id": f"MSG-{index:05d}",
                        "timestamp": "2026-01-05 9:00:00",
                        "from": "buyer@unknown.example",
                        "to": "manager@vendor.example",
                        "subject": "Checking in",
                        "body": "Thanks for the quick update.",
                        "thread_id": f"THR-{index}",
                        **row,
                    }
                )

    return write


def test_large_mailbox_scans_all_rows_and_pages_candidates(mailbox):
    rows = [{} for _ in range(500)]
    rows[300] = {
        "subject": "Our next renewal",
        "body": "Usage has dropped. Our board will not approve the price increase.",
        "thread_id": "THR-RISK",
    }
    rows[450] = {"body": "We will not renew.", "thread_id": "THR-EXIT"}
    rows[400] = {"subject": "Please send pricing", "body": "Could you offer a discount?"}
    rows[499] = {"timestamp": "2026-03-02 19:58:00"}
    mailbox(rows)

    first = mailbox_risk.scan_mailbox(limit=1, audit_limit=3)
    second = mailbox_risk.scan_mailbox(offset=first["next_offset"], limit=1, audit_limit=3)
    assert first["scanned"] == 500
    assert first["as_of"] == "2026-03-02 19:58:00"
    assert first["candidate_count"] == 2
    assert {first["candidates"][0]["email_id"], second["candidates"][0]["email_id"]} == {
        "MSG-00300",
        "MSG-00450",
    }
    assert second["has_more"] is False
    assert second["next_offset"] is None
    assert first["below_threshold"] == 498
    assert first["audit_sample_size"] == 3
    assert first["audit_sample"] == second["audit_sample"]


def test_quoted_and_automated_mentions_are_not_candidates(mailbox):
    mailbox(
        [
            {
                "body": "All resolved, thanks.\n\nOn Monday someone wrote:\n> We will not renew.",
                "subject": "Follow-up",
            },
            {"body": "Our renewal is at risk due to pricing.", "labels": "auto,calendar"},
            {"subject": "Is the renewal on track?", "body": "Can we discuss pricing?"},
        ]
    )
    result = mailbox_risk.scan_mailbox()
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["email_id"] == "MSG-00002"
    assert result["excluded_automated"] == 1
    assert result["below_threshold"] == 1


def test_unexpected_wording_is_visible_in_nonmatch_audit(mailbox):
    mailbox([{"body": "We will be taking our business elsewhere after this term."}])
    result = mailbox_risk.scan_mailbox(audit_limit=1)
    assert result["candidate_count"] == 0
    assert result["below_threshold"] == 1
    assert result["audit_sample"][0]["email_id"] == "MSG-00000"
    assert "can miss genuine risks" in result["limitations"]


def test_thread_returns_full_original_context_and_later_resolution(mailbox):
    mailbox(
        [
            {
                "thread_id": "THR-A",
                "subject": "The renewal terms for our account",
                "timestamp": "2026-01-02 10:00:00",
                "body": "We will not renew unless the price changes.",
            },
            {
                "thread_id": "THR-OTHER-ID",
                "subject": "RE: The renewal terms for our account",
                "from": "manager@vendor.example",
                "to": "buyer@unknown.example",
                "timestamp": "2026-01-10 10:00:00",
                "body": "The revised offer works; we agreed to renew.",
            },
            {"thread_id": "THR-B", "body": "Unrelated."},
        ]
    )
    result = mailbox_risk.read_mailbox_thread("MSG-00000")
    assert [x["email_id"] for x in result["messages"]] == ["MSG-00000", "MSG-00001"]
    assert result["messages"][1]["body"] == "The revised offer works; we agreed to renew."
    assert result["subject_linked_ids"] == ["MSG-00001"]


def test_invalid_mailbox_fails_instead_of_reporting_no_risk(mailbox):
    mailbox([{"timestamp": "unknown", "body": "We will not renew."}])
    with pytest.raises(ValueError, match="Invalid timestamp"):
        mailbox_risk.scan_mailbox()


def test_renewal_task_requires_evidence_and_coverage():
    task = next(item for item in TASKS if item["name"] == "renewal_risk")
    assert "scan_renewal_leads" in task["prompt"]
    assert "read_mailbox_thread" in task["prompt"]
    assert "EVERY" in task["prompt"]
    assert "audit_sample" in task["prompt"]
    assert "create_report" in task["prompt"]
    assert "renewal_risk_mailbox_export.pdf" in task["prompt"]
