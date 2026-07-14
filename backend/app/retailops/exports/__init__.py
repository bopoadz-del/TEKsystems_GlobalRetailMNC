"""Office-document export builders (PDF / DOCX / XLSX).

Generates in-memory artefacts for ActionRegistry export actions. The Render
filesystem is ephemeral, so callers receive base64 payloads (or stream via the
export HTTP endpoint) rather than durable server paths.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

ExportFormat = Literal["pdf", "docx", "xlsx"]

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass
class ExportSection:
    heading: str
    paragraphs: List[str] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)


@dataclass
class ExportTable:
    headers: List[str]
    rows: List[List[str]]
    name: str = "Sheet1"


@dataclass
class ExportDocument:
    title: str
    subtitle: str = ""
    sections: List[ExportSection] = field(default_factory=list)
    tables: List[ExportTable] = field(default_factory=list)
    footer: str = "CEREBRUM RetailOps — generated artefact"


@dataclass
class BuiltExport:
    filename: str
    content_type: str
    format: ExportFormat
    data: bytes

    @property
    def byte_size(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def to_public_dict(self, *, include_base64: bool = True) -> Dict[str, Any]:
        import base64

        out: Dict[str, Any] = {
            "filename": self.filename,
            "content_type": self.content_type,
            "format": self.format,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if include_base64:
            out["document_base64"] = base64.b64encode(self.data).decode("ascii")
        return out


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "export").strip().lower()).strip("-")
    return (s or "export")[:48]


def build_export(document: ExportDocument, fmt: ExportFormat) -> BuiltExport:
    if fmt == "pdf":
        data = _build_pdf(document)
    elif fmt == "docx":
        data = _build_docx(document)
    elif fmt == "xlsx":
        data = _build_xlsx(document)
    else:
        raise ValueError(f"unsupported export format: {fmt}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"{slugify(document.title)}-{stamp}.{fmt}"
    return BuiltExport(
        filename=filename,
        content_type=CONTENT_TYPES[fmt],
        format=fmt,
        data=data,
    )


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _build_docx(document: ExportDocument) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading(document.title, level=0)
    if document.subtitle:
        doc.add_paragraph(document.subtitle)
    for section in document.sections:
        doc.add_heading(section.heading, level=1)
        for para in section.paragraphs:
            doc.add_paragraph(para)
        for bullet in section.bullets:
            doc.add_paragraph(bullet, style="List Bullet")
    for table in document.tables:
        doc.add_heading(table.name, level=1)
        rows = [table.headers, *table.rows]
        if not table.headers:
            continue
        t = doc.add_table(rows=len(rows), cols=len(table.headers))
        for r_idx, row in enumerate(rows):
            for c_idx, cell in enumerate(row):
                if c_idx < len(t.rows[r_idx].cells):
                    t.rows[r_idx].cells[c_idx].text = str(cell)
    doc.add_paragraph(document.footer)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def _build_xlsx(document: ExportDocument) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    # Overview sheet
    ws = wb.active
    ws.title = "Overview"
    ws.append(["Title", document.title])
    if document.subtitle:
        ws.append(["Subtitle", document.subtitle])
    ws.append(["Generated", datetime.now(timezone.utc).isoformat()])
    ws.append([])
    for section in document.sections:
        ws.append([section.heading])
        for para in section.paragraphs:
            ws.append(["", para])
        for bullet in section.bullets:
            ws.append(["•", bullet])
        ws.append([])

    if document.tables:
        for table in document.tables:
            name = (table.name or "Data")[:31]
            sheet = wb.create_sheet(title=name)
            if table.headers:
                sheet.append(list(table.headers))
            for row in table.rows:
                # Pad / trim to header width
                width = len(table.headers) if table.headers else len(row)
                padded = [str(row[i]) if i < len(row) else "" for i in range(width)]
                sheet.append(padded)
    else:
        # Ensure at least one data-ish sheet for empty tables
        ws.append(["Note", "No tabular rows were supplied for this export."])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF (stdlib-friendly minimal writer — text lines + simple tables as text)
# ---------------------------------------------------------------------------

def _pdf_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _wrap_line(text: str, width: int = 90) -> List[str]:
    text = " ".join((text or "").split())
    if not text:
        return [""]
    words = text.split(" ")
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _iter_pdf_lines(document: ExportDocument) -> List[str]:
    lines: List[str] = [document.title]
    if document.subtitle:
        lines.append(document.subtitle)
    lines.append("")
    for section in document.sections:
        lines.append(section.heading)
        lines.append("-" * min(72, max(8, len(section.heading))))
        for para in section.paragraphs:
            lines.extend(_wrap_line(para))
            lines.append("")
        for bullet in section.bullets:
            for i, part in enumerate(_wrap_line(bullet, 86)):
                lines.append(("• " if i == 0 else "  ") + part)
        lines.append("")
    for table in document.tables:
        lines.append(table.name)
        lines.append("-" * min(72, max(8, len(table.name))))
        if table.headers:
            lines.append(" | ".join(str(h) for h in table.headers))
        for row in table.rows:
            lines.append(" | ".join(str(c) for c in row))
        lines.append("")
    lines.append(document.footer)
    return lines


def _build_pdf(document: ExportDocument) -> bytes:
    """Build a simple multi-page text PDF without extra dependencies."""
    all_lines = _iter_pdf_lines(document)
    lines_per_page = 48
    pages: List[List[str]] = [
        all_lines[i : i + lines_per_page]
        for i in range(0, max(1, len(all_lines)), lines_per_page)
    ]
    if not pages:
        pages = [[document.title or "RetailOps Export"]]

    page_ids: List[int] = []
    content_by_page: List[Tuple[int, bytes]] = []
    next_id = 3
    for page_lines in pages:
        page_id = next_id
        content_id = next_id + 1
        next_id += 2
        page_ids.append(page_id)
        parts = ["BT", "/F1 11 Tf", "14 TL", "1 0 0 1 48 800 Tm"]
        first = True
        for line in page_lines:
            escaped = _pdf_escape(line[:120])
            if first:
                parts.append(f"({escaped}) Tj")
                first = False
            else:
                parts.append("T*")
                parts.append(f"({escaped}) Tj")
        parts.append("ET")
        stream = "\n".join(parts).encode("latin-1", errors="replace")
        content_by_page.append((content_id, stream))

    font_id = next_id
    max_id = font_id
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    bodies: Dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1"),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, (content_id, stream) in zip(page_ids, content_by_page):
        bodies[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode("latin-1")
        bodies[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {0: 0}
    for i in range(1, max_id + 1):
        offsets[i] = len(out)
        out.extend(f"{i} 0 obj\n".encode("latin-1"))
        out.extend(bodies[i])
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {max_id + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for i in range(1, max_id + 1):
        out.extend(f"{offsets[i]:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(out)


# ---------------------------------------------------------------------------
# Document assembly from retail payloads
# ---------------------------------------------------------------------------

def document_from_custom(
    *,
    title: str,
    subtitle: str = "",
    sections: Optional[Sequence[Dict[str, Any]]] = None,
    table: Optional[Dict[str, Any]] = None,
    tables: Optional[Sequence[Dict[str, Any]]] = None,
) -> ExportDocument:
    parsed_sections = [
        ExportSection(
            heading=str(s.get("heading") or "Section"),
            paragraphs=[str(p) for p in (s.get("paragraphs") or [])],
            bullets=[str(b) for b in (s.get("bullets") or [])],
        )
        for s in (sections or [])
    ]
    parsed_tables: List[ExportTable] = []
    if table:
        parsed_tables.append(
            ExportTable(
                headers=[str(h) for h in (table.get("headers") or [])],
                rows=[[str(c) for c in row] for row in (table.get("rows") or [])],
                name=str(table.get("name") or "Data"),
            )
        )
    for t in tables or []:
        parsed_tables.append(
            ExportTable(
                headers=[str(h) for h in (t.get("headers") or [])],
                rows=[[str(c) for c in row] for row in (t.get("rows") or [])],
                name=str(t.get("name") or "Data"),
            )
        )
    return ExportDocument(
        title=title or "RetailOps Export",
        subtitle=subtitle,
        sections=parsed_sections,
        tables=parsed_tables,
    )


def document_from_operations_brief(source: Dict[str, Any], *, title: str = "") -> ExportDocument:
    sections = [
        ExportSection(
            heading="Executive summary",
            paragraphs=[str(source.get("executive_summary") or "No summary provided.")],
        ),
        ExportSection(
            heading="Priority actions",
            bullets=[
                f"{a.get('priority', 'n/a')}: {a.get('action', a)}"
                if isinstance(a, dict)
                else str(a)
                for a in (source.get("priority_actions") or [])
            ]
            or ["None recorded."],
        ),
    ]
    for key, label in (
        ("inventory_signals", "Inventory signals"),
        ("promotion_signals", "Promotion signals"),
        ("supplier_signals", "Supplier signals"),
        ("incidents", "Incidents"),
    ):
        items = source.get(key) or []
        bullets = []
        for item in items:
            if isinstance(item, dict):
                bullets.append(
                    item.get("summary")
                    or item.get("text")
                    or item.get("action")
                    or str(item)
                )
            else:
                bullets.append(str(item))
        sections.append(ExportSection(heading=label, bullets=bullets or ["None."]))
    missing = source.get("missing_information") or []
    if missing:
        sections.append(
            ExportSection(heading="Missing information", bullets=[str(m) for m in missing])
        )
    return ExportDocument(
        title=title or "Operations Brief",
        subtitle="Generated from retail.generate_operations_brief output",
        sections=sections,
    )


def document_from_inventory_risk(source: Dict[str, Any], *, title: str = "") -> ExportDocument:
    risks = source.get("risks") or source.get("items") or []
    headers = ["sku", "store", "risk_type", "on_hand", "reorder_point", "notes"]
    rows: List[List[str]] = []
    bullets: List[str] = []
    for risk in risks:
        if not isinstance(risk, dict):
            bullets.append(str(risk))
            continue
        rows.append(
            [
                str(risk.get("sku") or ""),
                str(risk.get("store") or ""),
                str(risk.get("risk_type") or risk.get("type") or ""),
                str(risk.get("on_hand") if risk.get("on_hand") is not None else ""),
                str(
                    risk.get("reorder_point")
                    if risk.get("reorder_point") is not None
                    else risk.get("applied_reorder_point") or ""
                ),
                str(risk.get("notes") or risk.get("summary") or "")[:120],
            ]
        )
        bullets.append(
            f"{risk.get('sku')} @ {risk.get('store')}: {risk.get('risk_type') or risk.get('type')}"
        )
    assumptions = source.get("assumptions") or []
    sections = [
        ExportSection(
            heading="Summary",
            paragraphs=[
                str(source.get("summary") or f"{len(rows)} inventory risk row(s) exported.")
            ],
            bullets=bullets[:40] or ["No risks listed."],
        )
    ]
    if assumptions:
        sections.append(
            ExportSection(heading="Assumptions", bullets=[str(a) for a in assumptions])
        )
    return ExportDocument(
        title=title or "Inventory Risk Report",
        subtitle="Generated from retail.analyse_inventory_risk output",
        sections=sections,
        tables=[ExportTable(headers=headers, rows=rows, name="Risks")] if rows else [],
    )


def document_from_learning_summary(source: Dict[str, Any], *, title: str = "") -> ExportDocument:
    profiles = source.get("profiles") or []
    headers = ["module", "entity_type", "entity_key", "confidence", "sample_count", "version"]
    rows: List[List[str]] = []
    for p in profiles:
        if not isinstance(p, dict):
            continue
        rows.append(
            [
                str(p.get("module") or ""),
                str(p.get("entity_type") or ""),
                str(p.get("entity_key") or ""),
                str(p.get("confidence") or ""),
                str(p.get("sample_count") if p.get("sample_count") is not None else ""),
                str(p.get("version") if p.get("version") is not None else ""),
            ]
        )
    return ExportDocument(
        title=title or "Learning Summary",
        subtitle="Advisory learning profiles — not automatic source-system writes",
        sections=[
            ExportSection(
                heading="Advisory notice",
                paragraphs=[
                    "Profiles below are advisory only. They require verification "
                    "and confirmation before operating parameters change."
                ],
                bullets=[f"{len(rows)} profile(s) included."],
            )
        ],
        tables=[ExportTable(headers=headers, rows=rows, name="Profiles")] if rows else [],
    )
