"""ActorAgent - a task-oriented agent with shared context access.

Each ActorAgent receives a task, reads from the shared CSV context via the
CSVReaderTool, and can produce PDF reports via the PDFReportTool. Multiple
ActorAgents can run concurrently, all sharing the same data directory.
"""

from __future__ import annotations

import logging

from smolagents import CodeAgent

from challenge.tools import BillingSummaryTool, CSVReaderTool, PDFReportTool

logger = logging.getLogger(__name__)


INSTRUCTIONS_TEMPLATE = """\
You are an ActorAgent — an autonomous analyst that accomplishes tasks by reading
data from a shared context and producing reports.

## Your identity
- Name: {agent_name}
- Role: {role}

## Available data sources
You have access to CSV data via the `read_context` tool. Available sources:
  - accounts: customer master data (account_id, name, industry, segment, etc.)
  - billing: invoicing events, payments, amounts, statuses
  - product_usage: weekly product usage metrics per department
  - support_tickets: support interactions and ticket history
  - crm_interactions: CRM activity log (calls, meetings, notes)
  - emails: email communications
  - contracts: pricing and contract terms
  - purchase_orders: purchase order records

## How to work
1. Read the task carefully.
2. Use `read_context` to gather the data you need. Filter by account_id when relevant.
3. Analyze the data in code — compute aggregates, find patterns, identify issues.
4. Use `create_report` to produce a PDF with your findings.
5. Return a short summary of what you found.

## Rules
- Always ground your analysis in the actual data — never fabricate numbers.
- When creating reports, include relevant data tables and charts.
- Be concise in your summaries.
"""


class ActorAgent:
    """A task-oriented agent that reads shared context and produces reports."""

    def __init__(
        self,
        name: str,
        role: str,
        model: object,
        tools: list | None = None,
        max_steps: int = 15,
    ):
        self.name = name
        self.role = role

        # Default tools: context retrieval, deterministic billing reconciliation, and reporting.
        default_tools = [CSVReaderTool(), BillingSummaryTool(), PDFReportTool()]
        all_tools = default_tools + (tools or [])

        self.agent = CodeAgent(
            tools=all_tools,
            model=model,
            instructions=INSTRUCTIONS_TEMPLATE.format(agent_name=name, role=role),
            additional_authorized_imports=[
                "json",
                "csv",
                "datetime",
                "collections",
                "statistics",
                "math",
                "re",
            ],
            max_steps=max_steps,
        )

    def run(self, task: str) -> str:
        """Execute a task and return the agent's response."""
        logger.info("[%s] Starting task: %s", self.name, task[:100])
        result = self.agent.run(task)
        logger.info("[%s] Task completed", self.name)
        return result
