"""Task definitions for ActorAgents.

Each task is a dict with:
  - name: identifier for the task
  - agent_name: name of the ActorAgent that will handle it
  - role: the agent's role description
  - prompt: the task prompt sent to the agent

Add your own tasks below or modify the existing ones.
"""

TASKS: list[dict] = [
    {
        "name": "billing_summary",
        "agent_name": "BillingAnalyst",
        "role": "Billing and payment analysis specialist",
        "prompt": (
            "Analyze the billing history for account MERID-001 (Meridian Health).\n"
            "1. Call reconcile_billing(account_id='MERID-001') and use its invoice rows and "
            "figures directly. Do not recompute billing totals.\n"
            "2. Create a PDF report called 'billing_summary_merid001.pdf' with:\n"
            "   - A concise billing summary that states the data cutoff and that amounts are "
            "gross and VAT-inclusive\n"
            "   - A table containing every reconciled invoice, including status and amounts\n"
            "   - Separate overdue and not-yet-due open balances\n"
            "   - Returned credits, disputes, and exceptions as factual notable findings"
        ),
    },
    {
        "name": "usage_trends",
        "agent_name": "UsageAnalyst",
        "role": "Product usage and adoption analyst",
        "prompt": (
            "Analyze product usage trends for account MERID-001 (Meridian Health).\n"
            "1. Read the product_usage data.\n"
            "2. Identify trends: is usage growing, flat, or declining?\n"
            "3. Break down usage by department if possible.\n"
            "4. Create a PDF report called 'usage_trends_merid001.pdf' with:\n"
            "   - A summary of overall usage trends\n"
            "   - A table showing usage over time\n"
            "   - A chart visualizing the trend"
        ),
    },
    {
        "name": "support_health",
        "agent_name": "SupportAnalyst",
        "role": "Customer support and satisfaction analyst",
        "prompt": (
            "Analyze support ticket history for account MERID-001 (Meridian Health).\n"
            "1. Read the support_tickets data.\n"
            "2. Categorize tickets by type/severity.\n"
            "3. Assess resolution times and identify recurring issues.\n"
            "4. Create a PDF report called 'support_health_merid001.pdf' with:\n"
            "   - A summary of support health\n"
            "   - A table of tickets with status and resolution\n"
            "   - Recommendations for improvement"
        ),
    },
    # -----------------------------------------------------------------------
    # TODO: Add your own tasks here during the live coding session.
    # Example:
    # {
    #     "name": "account_risk_assessment",
    #     "agent_name": "RiskAnalyst",
    #     "role": "Account risk and churn prediction analyst",
    #     "prompt": "...",
    # },
    # -----------------------------------------------------------------------
]
