"""PDFReportTool - generates PDF reports from structured content.

Agents use this tool to produce deliverables: account reviews, billing
summaries, risk assessments, etc. The tool accepts structured content
sections (headings, paragraphs, tables, charts) and renders them into
a professional PDF saved to the output/ directory.
"""

from __future__ import annotations

import io
import json
import logging
from html import escape
from pathlib import Path
from typing import Any

from smolagents import Tool

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output"

logger = logging.getLogger(__name__)


def build_pdf(
    title: str,
    content_sections: list[dict[str, Any]],
    author: str | None = None,
) -> bytes:
    """Build a PDF from structured content sections.

    Each section is a dict with a ``type`` key:
      - {"type": "heading", "text": "..."}
      - {"type": "paragraph", "text": "..."}
      - {"type": "table", "headers": [...], "rows": [[...], ...]}
      - {"type": "chart", "chart_type": "bar|line|pie",
            "title": "...", "labels": [...],
            "datasets": [{"label": "...", "data": [...]}]}
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        title=title,
        author=author or "Agent",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=18, spaceAfter=20)
    heading_style = ParagraphStyle(
        "DocHeading", parent=styles["Heading2"], fontSize=14, spaceAfter=10, spaceBefore=16
    )
    body_style = ParagraphStyle(
        "DocBody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=8
    )
    cell_style = ParagraphStyle("TableCell", parent=styles["Normal"], fontSize=8, leading=10)
    header_cell_style = ParagraphStyle(
        "TableHeader", parent=cell_style, fontName="Helvetica-Bold", textColor=colors.white
    )

    story: list[Any] = [Paragraph(title, title_style), Spacer(1, 12)]

    for section in content_sections:
        section_type = section.get("type", "paragraph")

        if section_type == "heading":
            story.append(Paragraph(section.get("text", ""), heading_style))

        elif section_type == "paragraph":
            story.append(Paragraph(section.get("text", ""), body_style))

        elif section_type == "table":
            headers = section.get("headers", [])
            rows = section.get("rows", [])
            table_data = [headers, *rows] if headers else rows
            if table_data:
                column_count = len(table_data[0])
                if not column_count or any(len(row) != column_count for row in table_data):
                    raise ValueError("Table rows must have the same nonzero number of columns")
                # SimpleDocTemplate's frame reserves 6pt on each side within doc.width.
                available_width = doc.width - 12
                minimum_column_width = 24
                if column_count * minimum_column_width > available_width:
                    raise ValueError("Table has too many columns to fit on the page")
                widths = [
                    min(32, max(8, max(len(str(row[index])) for row in table_data)))
                    for index in range(column_count)
                ]
                total_weight = sum(widths)
                remaining_width = available_width - column_count * minimum_column_width
                column_widths = [
                    minimum_column_width + remaining_width * weight / total_weight
                    for weight in widths
                ]
                wrapped_data = [
                    [
                        Paragraph(
                            escape(str(cell)).replace("\n", "<br/>"),
                            header_cell_style if headers and row_index == 0 else cell_style,
                        )
                        for cell in row
                    ]
                    for row_index, row in enumerate(table_data)
                ]
                t = Table(
                    wrapped_data,
                    colWidths=column_widths,
                    repeatRows=1 if headers else 0,
                    splitInRow=1,
                )
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, 0), 9),
                            ("FONTSIZE", (0, 1), (-1, -1), 8),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            (
                                "ROWBACKGROUNDS",
                                (0, 1),
                                (-1, -1),
                                [colors.white, colors.HexColor("#f5f5f5")],
                            ),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.extend([t, Spacer(1, 10)])

        elif section_type == "chart":
            chart_bytes = _render_chart(section)
            if chart_bytes:
                img = Image(io.BytesIO(chart_bytes), width=14 * cm, height=8 * cm)
                story.extend([img, Spacer(1, 10)])

    doc.build(story)
    return buf.getvalue()


def _render_chart(spec: dict[str, Any]) -> bytes | None:
    """Render a chart to PNG bytes using matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        chart_type = spec.get("chart_type", "bar")
        labels = spec.get("labels", [])
        datasets = spec.get("datasets", [])

        fig, ax = plt.subplots(figsize=(10, 5))

        if chart_type == "pie" and datasets:
            data = datasets[0].get("data", [])
            ax.pie(data, labels=labels, autopct="%1.1f%%", startangle=90)
        elif chart_type == "line":
            for ds in datasets:
                ax.plot(labels, ds.get("data", []), label=ds.get("label", ""), marker="o")
            ax.legend()
        else:  # bar
            import numpy as np

            x = np.arange(len(labels))
            width = 0.8 / max(len(datasets), 1)
            for i, ds in enumerate(datasets):
                offset = (i - len(datasets) / 2 + 0.5) * width
                ax.bar(x + offset, ds.get("data", []), width, label=ds.get("label", ""))
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha="right")
            ax.legend()

        ax.set_title(spec.get("title", ""))
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        return buf.getvalue()

    except Exception:
        logger.exception("Failed to render chart")
        return None


class PDFReportTool(Tool):
    """Tool for agents to generate PDF reports."""

    name = "create_report"
    description = (
        "Generate a PDF report and save it to the output/ directory.\n"
        "The report can include headings, paragraphs, data tables, and charts.\n"
        "Pass content as a JSON array of sections."
    )
    inputs = {
        "title": {
            "type": "string",
            "description": "Report title.",
        },
        "filename": {
            "type": "string",
            "description": "Output filename (e.g. 'billing_summary.pdf').",
        },
        "content_sections_json": {
            "type": "string",
            "description": (
                "JSON array of content sections. Each section has a 'type' key.\n"
                "Supported types:\n"
                '  {"type": "heading", "text": "Section Title"}\n'
                '  {"type": "paragraph", "text": "Body text..."}\n'
                '  {"type": "table", "headers": ["Col1", "Col2"], '
                '"rows": [["val1", "val2"], ...]}\n'
                '  {"type": "chart", "chart_type": "bar|line|pie", '
                '"title": "Chart Title", "labels": ["A", "B"], '
                '"datasets": [{"label": "Series 1", "data": [10, 20]}]}'
            ),
        },
        "author": {
            "type": "string",
            "description": "Author name. Optional.",
            "nullable": True,
        },
    }
    output_type = "string"

    def forward(
        self,
        title: str,
        filename: str,
        content_sections_json: str,
        author: str | None = None,
    ) -> str:
        try:
            content_sections = json.loads(content_sections_json)
        except (json.JSONDecodeError, TypeError) as exc:
            return f"ERROR: Invalid content_sections_json: {exc}"

        if not isinstance(content_sections, list):
            return "ERROR: content_sections_json must be a JSON array."

        try:
            pdf_bytes = build_pdf(title, content_sections, author=author)
        except Exception as exc:
            logger.exception("PDF generation failed")
            return f"ERROR: PDF generation failed: {exc}"

        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / filename
        output_path.write_bytes(pdf_bytes)

        return f"Report saved: {output_path}\nTitle: {title}\nSize: {len(pdf_bytes):,} bytes"
