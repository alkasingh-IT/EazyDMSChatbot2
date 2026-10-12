"""
DMS Export Routes — XLSX export (plain + AI-smart).
POST /api/export/xlsx   { columns, rows, filename }
POST /api/export/smart  { prompt, columns, rows, filename }
"""
import io
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.llm import call_llm_json

router = APIRouter(prefix="/api/export")


def _sanitize_filename(name: Optional[str], default_name: str = "export.xlsx") -> str:
    if not name:
        return default_name
    # Strip path separators, quotes, CRLF, and unsafe chars
    clean = re.sub(r"[^\w\.\-]", "_", name.strip())
    if not clean.endswith(".xlsx"):
        clean += ".xlsx"
    return clean[:128] if clean else default_name


class XlsxRequest(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    filename: Optional[str] = Field(default="export.xlsx", max_length=128)


class SmartXlsxRequest(BaseModel):
    prompt: str = Field(..., max_length=1000)
    columns: List[str]
    rows: List[Dict[str, Any]]
    filename: Optional[str] = Field(default="report.xlsx", max_length=128)


COLUMN_LABEL_MAP = {
    "ds_code": "Distributor Code",
    "ds_name": "Distributor Name",
    "dl_code": "Dealer Code",
    "dealer_name": "Dealer Name",
    "itemcode": "Item Code",
    "item_name": "Item Name",
    "item_group": "Item Group",
    "item_division": "Item Division",
    "salesperson_name": "Salesperson Name",
    "ds_city": "Distributor City",
    "ds_state": "Distributor State",
    "ds_zone": "Distributor Zone",
    "vendor_code": "Vendor Code",
    "vendor_name": "Vendor Name",
    "party_name": "Party Name",
}


def _make_xlsx(columns: List[str], rows: List[Dict[str, Any]],
               sort_col: Optional[str] = None,
               highlight_col: Optional[str] = None) -> bytes:
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")

    wb = openpyxl.Workbook()
    ws = wb.active

    # Sort rows if requested
    working_rows = list(rows)
    if sort_col and sort_col in columns:
        def _sort_key(r):
            v = r.get(sort_col)
            try:
                return (0, float(v))
            except (TypeError, ValueError):
                return (1, str(v or ""))
        working_rows = sorted(working_rows, key=_sort_key, reverse=True)

    # Header
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    for ci, col in enumerate(columns, 1):
        display_label = COLUMN_LABEL_MAP.get(col, col.replace("_", " ").title())
        cell = ws.cell(row=1, column=ci, value=display_label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Determine value range for highlight column
    hl_values: List[float] = []
    if highlight_col and highlight_col in columns:
        for r in working_rows:
            try:
                hl_values.append(float(r.get(highlight_col) or 0))
            except (TypeError, ValueError):
                hl_values.append(0.0)

    hl_min = min(hl_values) if hl_values else 0
    hl_max = max(hl_values) if hl_values else 1
    hl_range = max(hl_max - hl_min, 1)

    alt_fill   = PatternFill("solid", fgColor="F0F4FF")
    plain_fill = PatternFill("solid", fgColor="FFFFFF")

    for ri, row_data in enumerate(working_rows, 2):
        row_fill = alt_fill if ri % 2 == 0 else plain_fill
        for ci, col in enumerate(columns, 1):
            val = row_data.get(col)
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.fill = row_fill

            if hl_values and col == highlight_col:
                t = (hl_values[ri - 2] - hl_min) / hl_range  # 0=min 1=max
                if t < 0.33:
                    cell.fill = PatternFill("solid", fgColor="FFCCCC")
                elif t < 0.67:
                    cell.fill = PatternFill("solid", fgColor="FFF3CC")
                else:
                    cell.fill = PatternFill("solid", fgColor="CCFFCC")

    # Auto column widths
    for ci, col in enumerate(columns, 1):
        letter = get_column_letter(ci)
        max_len = len(col) + 2
        for ri in range(2, len(working_rows) + 2):
            v = ws.cell(row=ri, column=ci).value
            if v is not None:
                max_len = max(max_len, len(str(v)) + 2)
        ws.column_dimensions[letter].width = min(max_len, 42)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/xlsx")
async def export_xlsx(req: XlsxRequest):
    if not req.rows:
        raise HTTPException(400, detail="No rows to export.")
    raw = _make_xlsx(req.columns, req.rows)
    safe_filename = _sanitize_filename(req.filename, "export.xlsx")
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post("/smart")
async def export_smart(req: SmartXlsxRequest):
    if not req.rows:
        raise HTTPException(400, detail="No rows to export.")

    system = (
        "You are a spreadsheet formatting assistant for a DMS analytics platform.\n"
        "Given a user prompt and dataset columns, return JSON with:\n"
        '  "sort_by": "<column name or null>",\n'
        '  "highlight_col": "<column name or null>"\n'
        "Only use column names that exist in the provided list. Return ONLY valid JSON."
    )
    user = (
        f"User prompt: {req.prompt}\n"
        f"Available columns: {json.dumps(req.columns)}\n"
        f"Sample rows (first 3): {json.dumps(req.rows[:3], default=str)}"
    )
    spec = call_llm_json(system=system, user=user)
    sort_col  = spec.get("sort_by")   if isinstance(spec, dict) else None
    hl_col    = spec.get("highlight_col") if isinstance(spec, dict) else None
    if sort_col not in req.columns: sort_col = None
    if hl_col   not in req.columns: hl_col   = None

    raw = _make_xlsx(req.columns, req.rows, sort_col=sort_col, highlight_col=hl_col)
    safe_filename = _sanitize_filename(req.filename, "report.xlsx")
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
