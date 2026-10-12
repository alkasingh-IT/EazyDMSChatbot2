"""
DMS Enrichment — pre-LLM derived analytics.
Computes totals, growth, top/bottom performers and trend direction in Python
so the answer LLM receives authoritative numbers instead of doing math on raw rows.
"""
from __future__ import annotations
import logging
import datetime
import decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dms.enrich")

_VALUE_COL_HINTS = (
    "total_sales", "total_purchase_value", "total_primary_sales", "total_billed_value",
    "billed_value", "net_amount", "total_value", "grand_total", "total", "amount", "value",
)
_NAME_COL_HINTS = (
    "ds_name", "distributor_name", "item_name", "itemdescription",
    "dealer_name", "customer_name", "salesperson_name", "employeename", "staff_name", "so_name",
    "party_name", "vendor_name",
    "item_group", "item_division", "item_category", "product_category", "category",
    "ds_code", "dl_code", "itemcode", "vendor_code",
    "ds_city", "ds_state", "ds_zone", "zone", "region", "area_name", "area", "city", "state",
    "distributorid",
)
_TIME_COL_HINTS = ("purchase_month", "invoice_month", "sales_month", "month", "quarter")

_DETAIL_FLAG_SUFFIXES = ("this-month", "last-30d", "pending", "item-history")


def _safe_float(v: Any) -> float:
    try:
        if v is None or isinstance(v, bool):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0


_RATIO_TOKENS = ("pct", "percent", "ratio", "share")


def _is_ratio_col(col: str) -> bool:
    lc = str(col).lower()
    return any(t in lc for t in _RATIO_TOKENS)


def _is_id_col(col: str) -> bool:
    lc = str(col).lower()
    return lc == "id" or lc.endswith("_id") or lc.endswith("id")


def _column_is_numeric(rows: List[Dict[str, Any]], col: str) -> bool:
    """True if every non-null value in the column converts to a number.

    Handles Decimal / date / str cells returned by DB drivers — a column only
    qualifies when ALL non-null cells are numeric-convertible.
    """
    seen = False
    for r in rows:
        v = r.get(col)
        if v is None:
            continue
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float, decimal.Decimal)):
            seen = True
            continue
        if isinstance(v, (datetime.date, datetime.datetime)):
            return False
        try:
            float(str(v).replace(",", "").strip())
            seen = True
        except (TypeError, ValueError):
            return False
    return seen


def _fmt_inr(v: Any) -> str:
    x = _safe_float(v)
    neg = x < 0
    x = abs(x)
    if x >= 1e7:
        s = f"₹{x / 1e7:.2f}Cr"
    elif x >= 1e5:
        s = f"₹{x / 1e5:.2f}L"
    else:
        s = f"₹{x:,.0f}"
    return f"-{s}" if neg else s


def _growth_pct(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _trend_label(pct: Optional[float]) -> str:
    if pct is None:
        return "N/A (no prior-period data)"
    if pct > 20:
        return f"Strong growth (+{pct}%)"
    if pct > 5:
        return f"Growing (+{pct}%)"
    if pct > -5:
        return f"Flat ({pct:+.1f}%)"
    if pct > -20:
        return f"Declining ({pct:.1f}%)"
    return f"Sharp decline ({pct:.1f}%)"


def _pick(cols: List[str], hints) -> Optional[str]:
    avail = {str(c): str(c) for c in cols}
    lower = {str(c).lower(): str(c) for c in cols}
    for h in hints:
        if h in avail:
            return avail[h]
        if h in lower:
            return lower[h]
    for c in cols:
        lc = str(c).lower()
        for h in hints:
            if h in lc:
                return str(c)
    return None


def _row_label(row: Dict[str, Any], value_col: Optional[str], time_col: Optional[str]) -> str:
    """Human label for a row: prefer name-ish columns, fall back to time col."""
    for name_key in ("ds_name", "distributor_name", "item_name", "itemdescription", "dealer_name",
                     "customer_name", "salesperson_name", "employeename", "party_name", "vendor_name"):
        val = row.get(name_key)
        if val is not None and str(val).strip():
            code_key = {"ds_name": "ds_code", "item_name": "itemcode", "dealer_name": "dl_code"}.get(name_key)
            code_val = row.get(code_key) if code_key else None
            if code_val and str(code_val).strip() and str(code_val).strip() != str(val).strip():
                return f"{str(val).strip()} ({str(code_val).strip()})"
            return str(val).strip()

    parts: List[str] = []
    for c, v in row.items():
        if value_col and c == value_col:
            continue
        if time_col and c == time_col:
            continue
        if c.startswith("_"):
            continue
        if isinstance(v, (int, float)) or v is None:
            continue
        s = str(v).strip()
        if s:
            parts.append(s)
    if not parts and time_col and row.get(time_col) is not None:
        parts.append(str(row[time_col]))
    return " | ".join(parts[:3]) if parts else "(unnamed)"


def _extract_growth(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find current/previous pairs produced by *-growth / compare-periods flags."""
    pair_sets = [
        ("current_month_sales", "last_month_sales", "growth_pct"),
        ("current_total", "previous_total", "change_pct"),
        ("current_period", "previous_period", "change_pct"),
        ("current", "previous", "change_pct"),
    ]
    for r in rows[:3]:
        if not isinstance(r, dict):
            continue
        lower_keys = {str(k).lower(): k for k in r}
        for cur_k, prev_k, pct_k in pair_sets:
            ck = lower_keys.get(cur_k.lower())
            pk = lower_keys.get(prev_k.lower())
            if ck is not None and pk is not None:
                cur, prev = _safe_float(r.get(ck)), _safe_float(r.get(pk))
                gk = lower_keys.get(pct_k.lower())
                pct = _safe_float(r.get(gk)) if gk is not None else _growth_pct(cur, prev)
                return {
                    "current": cur,
                    "previous": prev,
                    "change_pct": pct,
                    "direction": _trend_label(pct),
                }
    return None


def enrich_flag_result(flag: str, desc: str, execution: Dict[str, Any]) -> Dict[str, Any]:
    """Derive totals / top-N / trend facts from one flag execution (Python-side math)."""
    rows = [r for r in (execution.get("rows") or []) if isinstance(r, dict)]
    cols = [c for c in (execution.get("columns") or []) if c]
    out: Dict[str, Any] = {
        "flag": flag,
        "description": desc,
        "row_count": execution.get("row_count", len(rows)),
        "error": execution.get("error"),
    }
    if not rows or not cols:
        return out

    val_col = _pick(cols, _VALUE_COL_HINTS)
    time_col = _pick([c for c in cols if c != val_col], _TIME_COL_HINTS)

    # Totals per numeric column (cap at 6 columns to keep prompt small).
    # Skip ID-like and ratio-like columns — summing them produces meaningless facts.
    numeric_sums: Dict[str, float] = {}
    for c in cols:
        if c.startswith("_"):
            continue
        if c != val_col and (_is_id_col(c) or _is_ratio_col(c)):
            continue
        if c == val_col or _column_is_numeric(rows, c):
            numeric_sums[c] = sum(_safe_float(r.get(c)) for r in rows)
    out["totals"] = {c: round(v, 2) for c, v in list(numeric_sums.items())[:6]}

    if val_col:
        ranked = sorted(
            rows,
            key=lambda r: _safe_float(r.get(val_col)),
            reverse=True,
        )
        total_val = sum(_safe_float(r.get(val_col)) for r in ranked)
        top_n = []
        for i, r in enumerate(ranked[:5], 1):
            entry = {
                "rank": i,
                "name": _row_label(r, val_col, time_col),
                "value": round(_safe_float(r.get(val_col)), 2),
                "value_fmt": _fmt_inr(r.get(val_col)),
            }
            if total_val:
                entry["share_pct"] = round(_safe_float(r.get(val_col)) * 100.0 / total_val, 1)
            top_n.append(entry)
        out["value_column"] = val_col
        out["grand_total"] = round(total_val, 2)
        out["grand_total_fmt"] = _fmt_inr(total_val)
        out["top_performers"] = top_n
        if len(ranked) >= 2:
            worst = ranked[-1]
            out["lowest_performer"] = {
                "name": _row_label(worst, val_col, time_col),
                "value": round(_safe_float(worst.get(val_col)), 2),
                "value_fmt": _fmt_inr(worst.get(val_col)),
            }

    # Trend series from month/quarter columns (>= 3 points).
    # Compare first half vs second half averages using clean, non-overlapping splits.
    if time_col and val_col and len(rows) >= 3:
        series = [(str(r.get(time_col)), _safe_float(r.get(val_col))) for r in rows if r.get(time_col) is not None]
        if len(series) >= 3:
            half = max(1, len(series) // 2)
            first_avg = sum(v for _, v in series[:half]) / half
            second = series[len(series) - half:]
            last_avg = sum(v for _, v in second) / half
            direction_pct = _growth_pct(last_avg, first_avg)
            out["trend_series"] = {"label_column": time_col, "points": series[:24]}
            out["trend_direction"] = _trend_label(direction_pct)

    growth = _extract_growth(rows)
    if growth:
        out["period_comparison"] = growth

    if flag.endswith(tuple(_DETAIL_FLAG_SUFFIXES)):
        out["note"] = (
            f"Detail query — {out['row_count']} rows returned; totals above are computed "
            f"from the returned rows only."
        )
    return out


def build_analytical_context(question: str, merged_exec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the authoritative fact pack handed to the answer LLM.
    merged_exec is the merged multi-flag execution built by routes/chat.py.
    """
    descriptions = merged_exec.get("descriptions") or []
    execs_by_flag: Dict[str, Dict[str, Any]] = {}

    all_rows = merged_exec.get("rows") or []
    for r in all_rows:
        f = r.get("_flag")
        if f and f not in execs_by_flag:
            execs_by_flag[f] = {"rows": [], "columns": [], "row_count": 0}
    for r in all_rows:
        f = r.get("_flag")
        if f:
            execs_by_flag[f]["rows"].append({k: v for k, v in r.items() if not k.startswith("_")})
    for f, e in execs_by_flag.items():
        e["columns"] = list(e["rows"][0].keys()) if e["rows"] else []
        e["row_count"] = len(e["rows"])

    enriched_flags = []
    for flag, desc in descriptions:
        base_exec = execs_by_flag.get(flag)
        if base_exec is None:
            base_exec = {"rows": [], "columns": [], "row_count": 0, "error": "no data"}
        enriched_flags.append(enrich_flag_result(flag, desc, base_exec))

    ctx: Dict[str, Any] = {
        "flags": enriched_flags,
        "data_quality": [
            ef["flag"] for ef in enriched_flags if ef.get("error")
        ],
    }

    insights: List[str] = []
    for ef in enriched_flags:
        if ef.get("error"):
            continue
        gt = ef.get("grand_total_fmt")
        if gt:
            insights.append(f"{ef['description']}: total {gt} across {ef['row_count']} rows.")
        for tp in (ef.get("top_performers") or [])[:1]:
            share = f" ({tp['share_pct']}% of total)" if tp.get("share_pct") is not None else ""
            insights.append(f"{ef['description']}: top — {tp['name']} at {tp['value_fmt']}{share}.")
        pc = ef.get("period_comparison")
        if pc:
            insights.append(
                f"{ef['description']}: current {_fmt_inr(pc['current'])} vs previous "
                f"{_fmt_inr(pc['previous'])} → {pc['direction']}."
            )
        td = ef.get("trend_direction")
        if td:
            insights.append(f"{ef['description']}: overall trend {td}.")
    ctx["insights"] = insights
    return ctx


def format_for_llm(ctx: Dict[str, Any]) -> str:
    """Render the enrichment context as a compact text block for the LLM prompt."""
    if not ctx or not ctx.get("flags"):
        return ""
    lines = ["AUTHORITATIVE FACTS (computed by Python — use these numbers as-is, do NOT recompute):"]
    for ef in ctx["flags"]:
        if ef.get("error"):
            lines.append(f"- [{ef['flag']}] no data ({ef['error']})")
            continue
        if ef.get("grand_total_fmt"):
            lines.append(f"- [{ef['flag']}] grand total: {ef['grand_total_fmt']} ({ef['row_count']} rows)")
        for c, v in (ef.get("totals") or {}).items():
            lines.append(f"  · sum({c}) = {v:,.2f}")
        for tp in ef.get("top_performers") or []:
            share = f", {tp['share_pct']}% of total" if tp.get("share_pct") is not None else ""
            lines.append(f"  · #{tp['rank']} {tp['name']} = {tp['value_fmt']}{share}")
        lp = ef.get("lowest_performer")
        if lp:
            lines.append(f"  · lowest: {lp['name']} = {lp['value_fmt']}")
        pc = ef.get("period_comparison")
        if pc:
            lines.append(
                f"  · vs previous period: {_fmt_inr(pc['current'])} vs {_fmt_inr(pc['previous'])} → {pc['direction']}"
            )
        if ef.get("trend_direction"):
            pts = (ef.get("trend_series") or {}).get("points") or []
            series_txt = ", ".join(f"{lab}={_fmt_inr(v)}" for lab, v in pts[:12])
            lines.append(f"  · trend ({ef['trend_direction']}): {series_txt}")
        if ef.get("note"):
            lines.append(f"  · note: {ef['note']}")
    if ctx.get("data_quality"):
        lines.append(f"- Data quality: could not fetch data for: {', '.join(ctx['data_quality'])}")
    logger.info("[ENRICH] fact pack built: %d lines", len(lines))
    return "\n".join(lines)
