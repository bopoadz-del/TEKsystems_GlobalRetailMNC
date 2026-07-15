"""Document export proofs — PDF / DOCX / XLSX generation."""

from __future__ import annotations

import base64
import io

import pytest
from docx import Document
from openpyxl import load_workbook

from app.retailops.exports import (
    ExportDocument,
    ExportSection,
    ExportTable,
    build_export,
    document_from_custom,
    document_from_inventory_risk,
    document_from_operations_brief,
)
from app.retailops.kit.contract import ActionContext, ActionStatus, execute_action
from app.retailops.service import build_registry


def _ctx() -> ActionContext:
    return ActionContext(
        user_id="u_ops_manager",
        tenant_id="northstar",
        organisation_id="northstar",
        project_id="prj_export",
        permissions=["retail:read", "retail:analyse"],
        allowed_domains=["retail"],
    )


@pytest.mark.parametrize("fmt", ["pdf", "docx", "xlsx"])
def test_build_export_formats(fmt):
    doc = ExportDocument(
        title="Smoke Export",
        subtitle="unit test",
        sections=[
            ExportSection(
                heading="Signals",
                paragraphs=["Chilled aisle follow-up required."],
                bullets=["Place wet-floor signage", "Notify duty manager"],
            )
        ],
        tables=[
            ExportTable(
                headers=["sku", "risk"],
                rows=[["SKU-1", "stockout"], ["SKU-2", "overstock"]],
                name="Risks",
            )
        ],
    )
    built = build_export(doc, fmt)  # type: ignore[arg-type]
    assert built.byte_size > 40
    assert built.filename.endswith(f".{fmt}")
    assert built.content_type
    assert len(built.sha256) == 64
    if fmt == "pdf":
        assert built.data.startswith(b"%PDF")
    if fmt == "docx":
        parsed = Document(io.BytesIO(built.data))
        texts = [p.text for p in parsed.paragraphs]
        assert any("Smoke Export" in t for t in texts)
    if fmt == "xlsx":
        wb = load_workbook(io.BytesIO(built.data))
        assert "Overview" in wb.sheetnames
        assert "Risks" in wb.sheetnames


@pytest.mark.asyncio
async def test_export_document_action_custom_pdf():
    registry = build_registry()
    spec = registry.resolve("retail.export_document")
    assert spec is not None
    result = await execute_action(
        spec,
        _ctx(),
        {
            "format": "pdf",
            "document_kind": "custom",
            "title": "Custom PDF",
            "sections": [
                {
                    "heading": "Follow-up",
                    "bullets": ["Review chilled aisle cleaning schedule"],
                }
            ],
        },
    )
    assert result.status == ActionStatus.SUCCESS
    assert result.output["format"] == "pdf"
    assert result.output["filename"].endswith(".pdf")
    raw = base64.b64decode(result.output["document_base64"])
    assert raw.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_export_document_action_brief_docx():
    registry = build_registry()
    spec = registry.resolve("retail.export_document")
    result = await execute_action(
        spec,
        _ctx(),
        {
            "format": "docx",
            "document_kind": "operations_brief",
            "title": "Daily Ops Brief",
            "source_output": {
                "executive_summary": "Two supplier delays and one incident.",
                "priority_actions": [
                    {"priority": "high", "action": "Chase dairy OTIF"},
                ],
                "inventory_signals": [{"summary": "SKU-9 low cover"}],
                "promotion_signals": [],
                "supplier_signals": [{"summary": "Vendor late"}],
                "incidents": [{"summary": "Slip near chilled aisle"}],
                "missing_information": [],
                "evidence": [],
            },
        },
    )
    assert result.status == ActionStatus.SUCCESS
    raw = base64.b64decode(result.output["document_base64"])
    parsed = Document(io.BytesIO(raw))
    blob = "\n".join(p.text for p in parsed.paragraphs)
    assert "Daily Ops Brief" in blob
    assert "Chase dairy OTIF" in blob


@pytest.mark.asyncio
async def test_export_document_action_inventory_xlsx():
    registry = build_registry()
    spec = registry.resolve("retail.export_document")
    result = await execute_action(
        spec,
        _ctx(),
        {
            "format": "xlsx",
            "document_kind": "inventory_risk",
            "source_output": {
                "summary": "1 stockout risk",
                "risks": [
                    {
                        "sku": "MILK-1",
                        "store": "Riyadh Olaya",
                        "risk_type": "stockout",
                        "on_hand": 2,
                        "reorder_point": 12,
                        "notes": "cover below threshold",
                    }
                ],
                "assumptions": ["advisory learning not applied"],
            },
        },
    )
    assert result.status == ActionStatus.SUCCESS
    wb = load_workbook(io.BytesIO(base64.b64decode(result.output["document_base64"])))
    assert "Risks" in wb.sheetnames
    rows = list(wb["Risks"].iter_rows(values_only=True))
    assert rows[0][0] == "sku"
    assert rows[1][0] == "MILK-1"


def test_document_helpers_shape():
    brief = document_from_operations_brief(
        {
            "executive_summary": "ok",
            "priority_actions": [],
            "inventory_signals": [],
            "promotion_signals": [],
            "supplier_signals": [],
            "incidents": [],
        }
    )
    assert brief.sections
    risk = document_from_inventory_risk({"risks": [{"sku": "A", "risk_type": "overstock"}]})
    assert risk.tables and risk.tables[0].rows
    custom = document_from_custom(
        title="T",
        sections=[{"heading": "H", "paragraphs": ["p"]}],
        table={"headers": ["a"], "rows": [["1"]], "name": "T1"},
    )
    assert custom.tables[0].name == "T1"


@pytest.mark.asyncio
async def test_export_custom_requires_content():
    registry = build_registry()
    spec = registry.resolve("retail.export_document")
    result = await execute_action(
        spec,
        _ctx(),
        {"format": "pdf", "document_kind": "custom"},
    )
    assert result.status == ActionStatus.DEPENDENCY_REQUIRED
