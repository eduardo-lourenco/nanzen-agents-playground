"""Bounded, evidence-preserving candidate retrieval from a mailbox CSV.

Keyword matches are leads for an analyst, never a churn classification. The
non-matching audit sample makes the filter's limited recall visible.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from smolagents import Tool

from challenge.tools.csv_reader import DATA_DIR, DATA_SOURCES

REQUIRED_COLUMNS = {"email_id", "timestamp", "from", "to", "subject", "body", "thread_id"}
EXCLUDED_LABELS = {"auto", "calendar", "newsletter", "ooo"}
MAX_PAGE_SIZE = 25
MAX_AUDIT_SIZE = 10
MAX_EXCERPT = 1200

# Broad, configurable lead categories. No customer or mailbox-specific identifiers.
SIGNALS = {
    "renewal": re.compile(r"\b(?:non[- ]?renew\w*|renew\w*|churn|retention)\b", re.I),
    "alternatives": re.compile(
        r"\b(?:switch\w*|alternatives?|competitor\w*|replace\w*|other vendors?)\b", re.I
    ),
    "approval": re.compile(r"\b(?:approv\w*|board|procurement|sign[- ]?off)\b", re.I),
    "commercial": re.compile(
        r"\b(?:pric\w*|budget\w*|cost\w*|spend|rate|discount\w*|downgrad\w*)\b", re.I
    ),
    "adoption": re.compile(r"\b(?:usag\w*|utili[sz]\w*|seat\w*|adoption)\b", re.I),
    "service": re.compile(r"\b(?:cancel\w*|outage\w*|unresolv\w*|escalat\w*)\b", re.I),
}
EXPLICIT_EXIT = re.compile(
    r"\b(?:will not renew|won't renew|not renewing|plan to leave|moving to another vendor|"
    r"terminate the contract)\b",
    re.I,
)
QUOTE_START = re.compile(r"(?im)^\s*(?:On .+wrote:|-----Original Message-----|From: .+|> .*)$")


def _source_path(source: str) -> Path:
    if source not in DATA_SOURCES:
        raise ValueError(f"Unknown source: {source}")
    return DATA_DIR / DATA_SOURCES[source]


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not REQUIRED_COLUMNS <= set(reader.fieldnames):
            raise ValueError(f"Mailbox must contain columns: {sorted(REQUIRED_COLUMNS)}")
        seen_ids: set[str] = set()
        for row in reader:
            if None in row or any(not row[key] for key in REQUIRED_COLUMNS):
                raise ValueError("Malformed mailbox row: missing required value or extra column")
            if row["email_id"] in seen_ids:
                raise ValueError(f"Duplicate email_id: {row['email_id']}")
            seen_ids.add(row["email_id"])
            try:
                datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise ValueError(f"Invalid timestamp for {row['email_id']}") from exc
            yield row


def _new_text(body: str) -> str:
    """Conservatively drop conventional quoted history; never alter stored evidence."""
    match = QUOTE_START.search(body)
    return body[: match.start()].strip() if match else body.strip()


def _item(row: dict[str, str], excerpt: str, signals: list[str] | None = None) -> dict:
    item = {
        "email_id": row["email_id"],
        "timestamp": row["timestamp"],
        "from": row["from"],
        "to": row["to"],
        "thread_id": row["thread_id"],
        "subject": row["subject"],
        "excerpt": excerpt[:MAX_EXCERPT],
    }
    if signals is not None:
        item["signals"] = signals
    return item


def _subject(subject: str) -> str:
    return re.sub(r"^(?:(?:re|fw|fwd):\s*)+", "", subject.strip(), flags=re.I).casefold()


def _participants(row: dict[str, str]) -> set[str]:
    return set(
        re.findall(
            r"[\w.+-]+@[\w.-]+",
            " ".join(row.get(key, "") or "" for key in ("from", "to", "cc", "bcc")),
            flags=re.I,
        )
    )


def scan_mailbox(
    source: str = "mailbox_export", offset: int = 0, limit: int = 20, audit_limit: int = 10
) -> dict:
    """Scan every row; return one bounded page of leads and a stable non-match audit."""
    if offset < 0 or not 1 <= limit <= MAX_PAGE_SIZE or not 0 <= audit_limit <= MAX_AUDIT_SIZE:
        raise ValueError("Invalid offset, limit, or audit_limit")
    candidates: list[dict] = []
    audit: list[tuple[int, dict]] = []
    counts = {"scanned": 0, "excluded_automated": 0, "below_threshold": 0}
    cutoff: datetime | None = None
    for row in _rows(_source_path(source)):
        counts["scanned"] += 1
        timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        cutoff = max(cutoff, timestamp) if cutoff else timestamp
        labels = {label.strip().lower() for label in (row.get("labels") or "").split(",")}
        if labels & EXCLUDED_LABELS:
            counts["excluded_automated"] += 1
            continue
        text = row["subject"] + "\n" + _new_text(row["body"])
        matches = [name for name, pattern in SIGNALS.items() if pattern.search(text)]
        if len(matches) >= 2 or EXPLICIT_EXIT.search(text):
            candidates.append(_item(row, _new_text(row["body"]), matches))
        else:
            counts["below_threshold"] += 1
            if audit_limit:
                rank = int.from_bytes(hashlib.sha256(row["email_id"].encode()).digest()[:8], "big")
                audit.append((rank, _item(row, _new_text(row["body"]))))
                audit.sort(key=lambda entry: entry[0])
                if len(audit) > audit_limit:
                    audit.pop()

    # Multi-signal leads first; pagination remains deterministic across calls.
    candidates.sort(
        key=lambda item: (
            -len(item["signals"]),
            datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S"),
            item["email_id"],
        )
    )
    page = candidates[offset : offset + limit]
    next_offset = offset + len(page)
    return {
        "source": source,
        "as_of": cutoff.isoformat(sep=" ") if cutoff else None,
        **counts,
        "candidate_count": len(candidates),
        "offset": offset,
        "candidates": page,
        "has_more": next_offset < len(candidates),
        "next_offset": next_offset if next_offset < len(candidates) else None,
        "audit_sample": [item for _, item in audit],
        "audit_sample_size": len(audit),
        "limitations": (
            "Requires two signal categories or an explicit exit phrase. Keyword filtering "
            "and automated-label exclusions can miss genuine risks; audit is a sample only."
        ),
    }


def read_mailbox_thread(email_id: str, source: str = "mailbox_export") -> dict:
    """Fetch original thread and subject-related replies when thread IDs differ."""
    if not email_id:
        raise ValueError("email_id is required")
    path = _source_path(source)
    original = next((row for row in _rows(path) if row["email_id"] == email_id), None)
    if original is None:
        raise ValueError(f"No message for email_id={email_id}")
    subject = _subject(original["subject"])
    people = _participants(original)
    related = [
        row
        for row in _rows(path)
        if row["thread_id"] == original["thread_id"]
        or (
            len(subject) >= 20
            and len(subject.split()) >= 4
            and _subject(row["subject"]) == subject
            and len(_participants(row) & people) >= 2
        )
    ]
    related.sort(key=lambda row: datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S"))
    return {
        "source": source,
        "email_id": email_id,
        "thread_id": original["thread_id"],
        "messages": related,
        "subject_linked_ids": [
            row["email_id"] for row in related if row["thread_id"] != original["thread_id"]
        ],
    }


class MailboxRiskScanTool(Tool):
    name = "scan_renewal_leads"
    description = (
        "Scan a registered mailbox source completely for keyword leads. Returns a bounded "
        "page of candidate messages, coverage counts and a stable sample of below-threshold "
        "messages. "
        "Retrieve ALL candidate pages; keywords are NOT a risk verdict."
    )
    inputs = {
        "source": {
            "type": "string",
            "description": "Registered mailbox source, e.g. mailbox_export.",
            "nullable": True,
        },
        "offset": {
            "type": "integer",
            "description": "Candidate offset (default 0).",
            "nullable": True,
        },
        "limit": {
            "type": "integer",
            "description": "Page size, at most 25 (default 20).",
            "nullable": True,
        },
        "audit_limit": {
            "type": "integer",
            "description": "Non-match audit size, at most 10.",
            "nullable": True,
        },
    }
    output_type = "object"

    def forward(
        self,
        source: str = "mailbox_export",
        offset: int = 0,
        limit: int = 20,
        audit_limit: int = 10,
    ) -> dict:
        return scan_mailbox(source, offset, limit, audit_limit)


class MailboxThreadTool(Tool):
    name = "read_mailbox_thread"
    description = (
        "Read original messages matching a candidate's thread ID or subject and participants. "
        "Subject-linked replies are best-effort and identified separately."
    )
    inputs = {
        "email_id": {"type": "string", "description": "Email ID from a renewal lead."},
        "source": {
            "type": "string",
            "description": "Registered mailbox source.",
            "nullable": True,
        },
    }
    output_type = "object"

    def forward(self, email_id: str, source: str = "mailbox_export") -> dict:
        return read_mailbox_thread(email_id, source)
