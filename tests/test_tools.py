"""Tests for the CSV reader and PDF report tools."""

import json

import pytest

from challenge.tools.csv_reader import CSVReaderTool, read_csv_source
from challenge.tools.pdf_report import PDFReportTool


class TestCSVReader:
    def test_list_sources(self):
        """CSVReaderTool raises an error with available sources for an unknown source."""
        tool = CSVReaderTool()
        with pytest.raises(ValueError, match="accounts"):
            tool.forward(source="nonexistent")

    def test_read_accounts(self):
        """Can read the accounts CSV."""
        result = read_csv_source("accounts")
        assert result["returned"] > 0
        assert "account_id" in result["rows"][0]

    def test_read_accounts_tool(self):
        """CSVReaderTool returns structured output for accounts."""
        tool = CSVReaderTool()
        result = tool.forward(source="accounts")
        assert result["total_matching"] >= 1
        assert result["rows"][0]["account_id"] == "MERID-001"

    def test_filter_by_account_id(self):
        """Can filter rows by account_id."""
        result = read_csv_source("accounts", account_id="MERID-001")
        assert result["total_matching"] == 1
        assert result["rows"][0]["account_id"] == "MERID-001"

    def test_read_billing(self):
        """Can read billing data."""
        result = read_csv_source("billing", limit=5)
        assert result["returned"] == 5
        assert len(result["rows"]) == 5

    def test_pagination_metadata(self):
        """Context pages expose enough metadata to retrieve the full result set."""
        first_page = read_csv_source("billing", account_id="MERID-001", limit=5)
        second_page = read_csv_source(
            "billing",
            account_id="MERID-001",
            limit=5,
            offset=first_page["next_offset"],
        )

        assert first_page["has_more"] is True
        assert first_page["next_offset"] == 5
        assert first_page["total_matching"] > first_page["returned"]
        assert first_page["rows"] != second_page["rows"]
        assert second_page["offset"] == 5

    def test_final_page_has_no_next_offset(self):
        """The final page explicitly signals that retrieval is complete."""
        first_page = read_csv_source("accounts", limit=1)
        final_page = read_csv_source(
            "accounts",
            limit=1,
            offset=first_page["total_matching"] - 1,
        )

        assert final_page["returned"] == 1
        assert final_page["has_more"] is False
        assert final_page["next_offset"] is None

    @pytest.mark.parametrize("limit, offset", [(0, 0), (-1, 0), (1, -1)])
    def test_invalid_pagination_values_raise_errors(self, limit, offset):
        """Pagination values must be valid before reading source data."""
        with pytest.raises(ValueError):
            read_csv_source("billing", limit=limit, offset=offset)

    def test_empty_result_has_complete_metadata(self):
        """Empty filters are represented as an empty structured page, not a text message."""
        result = read_csv_source("accounts", account_id="UNKNOWN-001")

        assert result == {
            "rows": [],
            "offset": 0,
            "returned": 0,
            "total_matching": 0,
            "has_more": False,
            "next_offset": None,
        }

    def test_all_sources_readable(self):
        """All registered data sources can be read."""
        from challenge.tools.csv_reader import DATA_SOURCES

        for source_name in DATA_SOURCES:
            result = read_csv_source(source_name, limit=1)
            assert result["returned"] >= 1, f"Source '{source_name}' returned no rows"


class TestPDFReport:
    def test_create_simple_report(self, tmp_path):
        """PDFReportTool creates a PDF file."""
        tool = PDFReportTool()

        # Override output dir for test
        import challenge.tools.pdf_report as pdf_module

        original_dir = pdf_module.OUTPUT_DIR
        pdf_module.OUTPUT_DIR = tmp_path

        try:
            sections = [
                {"type": "heading", "text": "Test Report"},
                {"type": "paragraph", "text": "This is a test paragraph."},
                {
                    "type": "table",
                    "headers": ["Name", "Value"],
                    "rows": [["Alpha", "100"], ["Beta", "200"]],
                },
            ]
            result = tool.forward(
                title="Test Report",
                filename="test_report.pdf",
                content_sections_json=json.dumps(sections),
            )
            assert "Report saved" in result
            assert (tmp_path / "test_report.pdf").exists()
            assert (tmp_path / "test_report.pdf").stat().st_size > 0
        finally:
            pdf_module.OUTPUT_DIR = original_dir

    def test_invalid_json(self):
        """PDFReportTool handles invalid JSON gracefully."""
        tool = PDFReportTool()
        result = tool.forward(
            title="Test",
            filename="test.pdf",
            content_sections_json="not valid json",
        )
        assert "ERROR" in result

    def test_non_array_json(self):
        """PDFReportTool rejects non-array JSON."""
        tool = PDFReportTool()
        result = tool.forward(
            title="Test",
            filename="test.pdf",
            content_sections_json='{"type": "heading"}',
        )
        assert "ERROR" in result

    def test_report_with_chart(self, tmp_path):
        """PDFReportTool can render charts."""
        tool = PDFReportTool()

        import challenge.tools.pdf_report as pdf_module

        original_dir = pdf_module.OUTPUT_DIR
        pdf_module.OUTPUT_DIR = tmp_path

        try:
            sections = [
                {"type": "heading", "text": "Chart Report"},
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Test Chart",
                    "labels": ["Q1", "Q2", "Q3"],
                    "datasets": [{"label": "Revenue", "data": [100, 150, 200]}],
                },
            ]
            result = tool.forward(
                title="Chart Report",
                filename="chart_report.pdf",
                content_sections_json=json.dumps(sections),
            )
            assert "Report saved" in result
            assert (tmp_path / "chart_report.pdf").exists()
        finally:
            pdf_module.OUTPUT_DIR = original_dir
