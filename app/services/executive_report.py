"""
DMS Computational BI Synthesis Engine v2 — Direct High-Speed Commercial Analytics.
Provides Fortune-500 grade, fully dynamic commercial intelligence briefings,
stateful multi-turn conversational analytics, and deterministic Chart.js specifications
when x-ai-analytics=False (sub-100ms, 0 LLM tokens, 100% zero data exfiltration).

Architecture Pillars (v2):
  Layer 1: Universal DMS Column Resolver — zero ₹0 bugs across all DMS tables
  Layer 2: Multi-Dataset Classifier & Fuser — fixes compound query blindness (dim_ds vs summary_ds)
  Layer 3: Mathematical Computation Engine — centralised pure-math commercial analytics
  Layer 3.5: Advanced Analytics Engine — z-scores, Gini, HHI, Pareto 80/20, tier classification
  Layer 4: Composable Briefing Block Assembler — 8 reusable blocks + data-driven dynamic directives
  Layer 5: Conversation Memory Manager — 20-turn multi-hop stateful memory thread
  Layer 6: Advanced In-Memory Cross-Questioning Engine — 10 follow-up patterns + fuzzy matching (<5ms)
  Layer 7: Smart Chart Spec Generator — dataset-aware, compound-query safe
  Conversational Fast-Path: Zero-latency (<1ms) greeting & capability handler
  Universal Typography: Zero raw ### / #### hashes, clean quotes, pristine formatting
"""
from __future__ import annotations

import dataclasses
import datetime
import decimal
import math
import re
import threading
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS & TYPOGRAPHY SANITIZER
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, decimal.Decimal):
        return float(v)
    try:
        cleaned = str(v).replace(",", "").replace("₹", "").replace("$", "").strip()
        return float(cleaned)
    except Exception:
        return 0.0


def _fmt_inr(v: Any) -> str:
    x = _safe_float(v)
    if x == 0:
        return "₹0"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 10_000_000:
        return f"{sign}₹{x / 10_000_000:.2f}Cr"
    if x >= 100_000:
        return f"{sign}₹{x / 100_000:.2f}L"
    if x >= 1_000:
        return f"{sign}₹{x / 1_000:.1f}K"
    return f"{sign}₹{x:,.0f}"


def _fmt_num(v: Any) -> str:
    x = _safe_float(v)
    if x == 0:
        return "0"
    if float(x).is_integer():
        return f"{int(x):,}"
    return f"{x:,.1f}"


def _clean_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _clean_question_title(question: str, fallback: str) -> str:
    cleaned = re.sub(
        r"^(show|get|list|display|find|give me|what are|who are|tell me|check)\s+",
        "",
        (question or "").strip(),
        flags=re.IGNORECASE,
    ).title()
    return cleaned if cleaned else fallback


def _clean_markdown_formatting(text: str) -> str:
    """
    Cleans markdown formatting:
    - Strips 4-byte astral plane emojis (> 0xFFFF) and problematic symbols that produce  replacement characters.
    - Removes raw markdown header hashes (###, ####).
    - Removes malformed quote asterisks (*"..."*).
    - Normalizes unicode bullet points (-) to standard markdown bullet lists (- ).
    """
    if not text:
        return ""
    # Strip astral plane emojis (> 0xFFFF) and problematic symbols (lightning, warning, scales, variation selectors)
    cleaned = re.sub(r"[\U00010000-\U0010ffff\u26a1\u26a0\u2696\ufe0f]", "", text)
    # Remove ### or #### or # at start of lines
    cleaned = re.sub(r"^(#{1,6})\s*", "", cleaned, flags=re.MULTILINE)
    # Remove * before or after quotes e.g. *"text"* -> "text" or *'text'* -> 'text'
    cleaned = re.sub(r'\*+"([^"]+)"\*+', r'"\1"', cleaned)
    cleaned = re.sub(r"\*+'([^']+)'\*+", r"'\1'", cleaned)
    # Normalize unicode bullets to standard markdown list dashes
    cleaned = re.sub(r"^[ \t]*-[ \t]*", "- ", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace(" - ", " - ")
    cleaned = cleaned.replace("- ", "- ")
    # Fix any leading spaces at start of lines
    cleaned = re.sub(r"^[ \t]+(?!- )", "", cleaned, flags=re.MULTILINE)
    # Clean up multiple spaces
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def _extract_time_context(question: str, rows: List[Dict[str, Any]], time_col: Optional[str]) -> str:
    """Extract human-readable time period from question or data timestamps."""
    q_low = (question or "").lower()

    # Named periods in question
    if "today" in q_low:
        return "Today"
    if "yesterday" in q_low:
        return "Yesterday"
    if "this week" in q_low or "current week" in q_low:
        return "This Week"
    if "last week" in q_low:
        return "Last Week"
    if "this month" in q_low or "current month" in q_low:
        return "This Month"
    if "last month" in q_low:
        return "Last Month"
    if "this quarter" in q_low or "current quarter" in q_low:
        return "Current Quarter"
    if "last quarter" in q_low:
        return "Last Quarter"
    if "this year" in q_low:
        return "This Year"
    if "last year" in q_low:
        return "Last Year"
    if "last 30 days" in q_low or "last 30d" in q_low:
        return "Last 30 Days"
    if "last 7 days" in q_low or "last 7d" in q_low:
        return "Last 7 Days"
    if "last 90 days" in q_low or "last 90d" in q_low:
        return "Last 90 Days"

    month_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*(\d{4})?\b",
        q_low,
    )
    if month_match:
        m_name = month_match.group(1).title()
        yr = month_match.group(2)
        return f"{m_name} {yr}".strip() if yr else m_name

    # Try inferring from rows
    if time_col and rows:
        dates = [str(r.get(time_col)) for r in rows if r.get(time_col)]
        if dates:
            first_d, last_d = dates[0][:10], dates[-1][:10]
            if first_d == last_d:
                return first_d
            return f"{first_d} to {last_d}"

    return "Current Reporting Period"


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1: UNIVERSAL DMS COLUMN RESOLVER
# ─────────────────────────────────────────────────────────────────────────────

VAL_COL_CANDIDATES = [
    "total_sales", "total_purchase_value", "total_primary_sales", "total_billed_value",
    "billed_value", "net_amount", "total_value", "grand_total", "total_amount",
    "amount", "value", "val", "sales", "claim_amount", "claimed_amount",
    "closing_stock_value", "opening_stock_value", "inward_value", "outward_value",
    "scheme_value", "discount_amount", "total_disc",
]

QTY_COL_CANDIDATES = [
    "total_qty", "quantity", "qty", "billed_qty", "units", "inward_qty",
    "outward_qty", "closing_stock", "closing_qty", "stock_qty", "dispatch_qty",
    "total_pieces", "pieces", "cases", "liquidated_qty",
]

INV_COUNT_CANDIDATES = [
    "invoice_count", "bill_count", "total_invoices", "order_count",
    "transaction_count", "vouchers", "claims_count", "grn_count",
]

OUTLET_COUNT_CANDIDATES = [
    "unique_outlets", "unique_dealers", "dealers_count", "outlets",
    "counters", "unique_distributors", "distributors_count", "stores",
]

ENTITY_NAME_CANDIDATES = [
    "distributor_name", "ds_name", "item_name", "itemdescription",
    "dealer_name", "customer_name", "vendor_name", "salesperson_name",
    "employeename", "party_name", "so_name", "scheme_name", "claim_type",
    "batch_no", "zone", "region", "area_name", "area", "city", "state", "name",
]

ENTITY_CODE_CANDIDATES = [
    "distributor_code", "ds_code", "item_code", "itemcode", "dealer_code",
    "vendor_code", "customer_code", "batch_code", "code", "id",
]

TIME_COL_CANDIDATES = [
    "purchase_month", "sales_month", "invoice_month", "invoice_date",
    "order_date", "date", "month", "period", "quarter", "created_at",
]


def _find_col(candidates: List[str], cols_map: Dict[str, str]) -> Optional[str]:
    """Resolve column name case-insensitively with exact match precedence."""
    for cand in candidates:
        if cand.lower() in cols_map:
            return cols_map[cand.lower()]
    for cand in candidates:
        for low_col, orig_col in cols_map.items():
            if cand.lower() in low_col or low_col in cand.lower():
                return orig_col
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2: MULTI-DATASET CLASSIFIER & FUSER (COMPOUND QUERY HANDLING)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_and_fuse_datasets(
    executed_data: List[Dict[str, Any]],
    module_hint: str = "",
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, float], Dict[str, bool]]:
    """
    Layer 2 — select ONE report module and derive verified metrics from it.

    Returns (primary_rows, primary_cols, kpis, metric_valid). Every headline
    metric comes from a single module via the metric guard, so a summary row can
    never be fused with an unrelated breakdown and produce a mismatched number.
    """
    primary_rows, primary_cols, kpis, metric_valid, _flag = _resolve_report_datasets(
        executed_data, module_hint
    )
    return primary_rows, primary_cols, kpis, metric_valid


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 & 3.5: MATHEMATICAL ENGINE & ADVANCED STATISTICAL PORTFOLIO ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class AdvancedMetrics:
    """Layer 3.5 — statistical & portfolio advanced analytics."""
    median_val: float
    std_dev: float
    z_scores: List[float]
    outlier_entities: List[Dict[str, Any]]
    coefficient_of_variation: float
    gini_coefficient: float
    hhi_index: float
    top_n_coverage: Dict[int, float]
    cumulative_share: List[float]
    entity_tiers: Dict[str, str]
    pareto_80_count: int

    @property
    def cv(self) -> float:
        return self.coefficient_of_variation


@dataclasses.dataclass
class ComputedAnalytics:
    """Layer 3 — full computed analytics payload passed to all briefing blocks."""
    total_val: float
    total_qty: float
    entity_count: int
    avg_ticket: float
    avg_realization: float
    invoice_count: int
    unique_outlets: int
    ranked_entities: List[Dict[str, Any]]
    top_3_share: float
    top_5_share: float
    concentration_risk: str
    summary_kpis: Dict[str, float]
    advanced: AdvancedMetrics
    module: str
    time_str: str
    metric_valid: Dict[str, bool] = dataclasses.field(default_factory=dict)


def _compute_advanced_metrics(
    ranked_entities: List[Dict[str, Any]],
    total_val: float,
) -> AdvancedMetrics:
    """Computes advanced statistical parameters without numpy dependencies."""
    n = len(ranked_entities)
    if n == 0:
        return AdvancedMetrics(
            median_val=0.0, std_dev=0.0, z_scores=[], outlier_entities=[],
            coefficient_of_variation=0.0, gini_coefficient=0.0, hhi_index=0.0,
            top_n_coverage={}, cumulative_share=[], entity_tiers={}, pareto_80_count=0,
        )

    vals = [_safe_float(e.get("val")) for e in ranked_entities]
    sorted_v = sorted(vals)

    # Median
    if n % 2 == 1:
        median_v = sorted_v[n // 2]
    else:
        median_v = (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2.0

    # Mean & Standard Deviation
    mean_v = total_val / n if n > 0 else 0.0
    variance = sum((v - mean_v) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    # Z-scores & Outlier Detection
    z_scores: List[float] = []
    outliers: List[Dict[str, Any]] = []
    for e in ranked_entities:
        v = _safe_float(e.get("val"))
        z = (v - mean_v) / std_dev if std_dev > 0 else 0.0
        z_round = round(z, 2)
        z_scores.append(z_round)
        if abs(z_round) > 2.0:
            outliers.append({**e, "z_score": z_round})

    # Coefficient of Variation
    cv = (std_dev / mean_v * 100.0) if mean_v > 0 else 0.0

    # Gini Coefficient
    if n <= 1 or total_val == 0:
        gini = 0.0
    else:
        cumsum = 0.0
        gini_num = 0.0
        for i, v in enumerate(sorted_v):
            cumsum += v
            gini_num += (2 * (i + 1) - n - 1) * v
        gini = round(gini_num / (n * total_val), 4) if total_val > 0 else 0.0
        gini = max(0.0, min(1.0, gini))

    # HHI Index & Robust Share Resolution
    shares = []
    for e in ranked_entities:
        s = _safe_float(e.get("share"))
        if s == 0.0 and total_val > 0:
            s = (_safe_float(e.get("val")) / total_val * 100.0)
        shares.append(s)
    hhi = round(sum(s ** 2 for s in shares), 1)

    # Cumulative share curve & top-N coverage
    cum_share: List[float] = []
    running = 0.0
    pareto_80_count = n
    for i, (e, s) in enumerate(zip(ranked_entities, shares)):
        running += s
        cum_share.append(round(running, 2))
        if running >= 80.0 and pareto_80_count == n:
            pareto_80_count = i + 1

    top_n_coverage: Dict[int, float] = {}
    for threshold in (1, 3, 5, 10):
        if threshold <= n:
            top_n_coverage[threshold] = round(cum_share[threshold - 1], 1)

    # Portfolio Tier Classification
    entity_tiers: Dict[str, str] = {}
    for e, s in zip(ranked_entities, shares):
        share = s
        name = e.get("name", "")
        if share >= 25.0:
            entity_tiers[name] = "ANCHOR"
        elif share >= 5.0:
            entity_tiers[name] = "CORE"
        elif share >= 1.0:
            entity_tiers[name] = "TAIL"
        else:
            entity_tiers[name] = "DORMANT"

    return AdvancedMetrics(
        median_val=round(median_v, 2),
        std_dev=round(std_dev, 2),
        z_scores=z_scores,
        outlier_entities=outliers,
        coefficient_of_variation=round(cv, 1),
        gini_coefficient=round(gini, 3),
        hhi_index=hhi,
        top_n_coverage=top_n_coverage,
        cumulative_share=cum_share,
        entity_tiers=entity_tiers,
        pareto_80_count=pareto_80_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# METRIC GUARD — single-source, verified metrics (never mix scopes)
# ─────────────────────────────────────────────────────────────────────────────
# The Direct-BI report must never show a number that cannot be traced to ONE
# dataset and that disagrees with the table rendered below it. A summary row is
# only trusted when it belongs to the SAME module as the breakdown AND agrees
# with the row-derived value within tolerance. Otherwise the row-derived value
# wins (it matches the table), and a metric with no source is omitted.

_METRIC_TOLERANCE = 0.02  # 2%


def _module_of(flag: Any) -> str:
    """'sc:dead-count' → 'sc'."""
    return str(flag or "").split(":")[0].strip().lower()


def _dataset_rows(ds: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ds.get("rows") or ds.get("rows_full") or []


def _dataset_cols(ds: Dict[str, Any]) -> List[str]:
    cols = ds.get("columns") or []
    if not cols and _dataset_rows(ds):
        first = _dataset_rows(ds)[0]
        if isinstance(first, dict):
            cols = list(first.keys())
    return [c for c in cols if c and not str(c).startswith("_")]


def _has_entity_col(cols: List[str]) -> bool:
    norms = {re.sub(r"[_\-\s]", "", c.lower()) for c in ENTITY_NAME_CANDIDATES}
    col_norms = {re.sub(r"[_\-\s]", "", str(c).lower()) for c in cols}
    return bool(norms & col_norms)


def _extract_dataset_metrics(ds: Dict[str, Any]) -> Tuple[Dict[str, float], bool]:
    """Return (metrics, is_summary) for ONE dataset.

    is_summary = a single aggregate row that is NOT an entity breakdown.
    """
    rows = _dataset_rows(ds)
    if not rows:
        return {}, False
    cols = _dataset_cols(ds)
    cols_map = {c.lower(): c for c in cols}
    val_col = _find_col(VAL_COL_CANDIDATES, cols_map)
    qty_col = _find_col(QTY_COL_CANDIDATES, cols_map)
    inv_col = _find_col(INV_COUNT_CANDIDATES, cols_map)
    out_col = _find_col(OUTLET_COUNT_CANDIDATES, cols_map)
    is_summary = len(rows) == 1 and not _has_entity_col(cols)

    m: Dict[str, float] = {}
    if is_summary:
        r0 = rows[0]
        if val_col: m["total_val"] = _safe_float(r0.get(val_col))
        if qty_col: m["total_qty"] = _safe_float(r0.get(qty_col))
        if inv_col: m["invoice_count"] = _safe_float(r0.get(inv_col))
        if out_col: m["unique_outlets"] = _safe_float(r0.get(out_col))
    else:
        if val_col: m["total_val"] = sum(_safe_float(r.get(val_col)) for r in rows)
        if qty_col: m["total_qty"] = sum(_safe_float(r.get(qty_col)) for r in rows)
        if inv_col: m["invoice_count"] = sum(_safe_float(r.get(inv_col)) for r in rows)
        if out_col: m["unique_outlets"] = float(len({_clean_str(r.get(out_col)) for r in rows if r.get(out_col)}))
    return m, is_summary


def _resolve_report_datasets(
    executed_data: List[Dict[str, Any]],
    module_hint: str = "",
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, float], Dict[str, bool], str]:
    """
    Pick ONE report module/flag and derive every headline metric from it alone.

    Returns (primary_rows, primary_cols, kpis, metric_valid, primary_flag).
    """
    valid_ds = [
        ds for ds in (executed_data or [])
        if isinstance(ds, dict) and not ds.get("error") and _dataset_rows(ds)
    ]
    if not valid_ds:
        return [], [], {}, {}, ""

    by_module: Dict[str, List[Dict[str, Any]]] = {}
    for ds in valid_ds:
        by_module.setdefault(_module_of(ds.get("flag")), []).append(ds)

    def _breakdown_rows(dss: List[Dict[str, Any]]) -> int:
        best = 0
        for d in dss:
            _m, is_sum = _extract_dataset_metrics(d)
            if not is_sum:
                best = max(best, len(_dataset_rows(d)))
        return best

    report_module = ""
    if module_hint and module_hint in by_module and _breakdown_rows(by_module[module_hint]) > 0:
        report_module = module_hint
    else:
        report_module = max(
            by_module,
            key=lambda m: (_breakdown_rows(by_module[m]),
                           sum(len(_dataset_rows(d)) for d in by_module[m])),
        )
    ds_group = by_module.get(report_module, [])

    breakdowns = [d for d in ds_group if not _extract_dataset_metrics(d)[1]]
    summaries = [d for d in ds_group if _extract_dataset_metrics(d)[1]]
    if breakdowns:
        primary = max(breakdowns, key=lambda d: len(_dataset_rows(d)))
    elif summaries:
        primary = summaries[0]
    else:
        primary = ds_group[0]

    primary_rows = _dataset_rows(primary)
    primary_cols = _dataset_cols(primary)
    primary_is_summary = _extract_dataset_metrics(primary)[1]
    row_metrics, _ = _extract_dataset_metrics(primary)
    sum_metrics, _ = (_extract_dataset_metrics(summaries[0]) if summaries else ({}, True))

    kpis: Dict[str, float] = {}
    valid: Dict[str, bool] = {}

    for metric in ("total_val", "total_qty", "invoice_count", "unique_outlets"):
        rv = row_metrics.get(metric)
        sv = sum_metrics.get(metric)
        if rv is None and sv is None:
            valid[metric] = False
            continue
        if primary_is_summary:
            kpis[metric] = rv
            valid[metric] = True
            continue
        if rv is not None and rv != 0:
            if sv is not None and sv != 0:
                diff = abs(sv - rv) / max(abs(rv), 1e-9)
                if diff <= _METRIC_TOLERANCE:
                    kpis[metric] = sv  # agree → summary authoritative
                else:
                    print(f"[exec-report] metric '{metric}' using row-derived {rv} "
                          f"(summary {sv} disagreed by {diff * 100:.1f}%)")
                    kpis[metric] = rv
            else:
                kpis[metric] = rv
            valid[metric] = True
        elif sv is not None:
            kpis[metric] = sv
            valid[metric] = True
        else:
            valid[metric] = False

    # invoice_count must NEVER be the number of breakdown rows (those are
    # entities, not bills). If there is no explicit count, omit it.
    if not primary_is_summary and "invoice_count" not in kpis:
        valid["invoice_count"] = False

    return primary_rows, primary_cols, kpis, valid, str(primary.get("flag") or "")


def _compute_analytics(
    rows: List[Dict[str, Any]],
    cols: List[str],
    summary_kpis: Dict[str, float],
    module: str,
    time_str: str,
    metric_valid: Optional[Dict[str, bool]] = None,
) -> ComputedAnalytics:
    """Transforms raw DB rows into an enriched analytical object.

    Headline metrics are taken from `summary_kpis` ONLY when the metric guard
    marked them valid (single, self-consistent source). Invalid metrics fall
    back to the row-derived value (often 0, so display gates omit them). This
    guarantees a shown number never contradicts the table rendered below it.
    """
    metric_valid = metric_valid or {}
    cols_map = {c.lower(): c for c in cols}
    val_col = _find_col(VAL_COL_CANDIDATES, cols_map)
    qty_col = _find_col(QTY_COL_CANDIDATES, cols_map)
    name_col = _find_col(ENTITY_NAME_CANDIDATES, cols_map)
    code_col = _find_col(ENTITY_CODE_CANDIDATES, cols_map)
    inv_col = _find_col(INV_COUNT_CANDIDATES, cols_map)
    out_col = _find_col(OUTLET_COUNT_CANDIDATES, cols_map)

    raw_total_val = sum(_safe_float(r.get(val_col)) for r in rows) if val_col else 0.0
    raw_total_qty = sum(_safe_float(r.get(qty_col)) for r in rows) if qty_col else 0.0

    def _resolved(name: str, raw: float) -> float:
        if name in summary_kpis and metric_valid.get(name, True):
            return _safe_float(summary_kpis[name])
        return raw

    # 1. Authoritative Totals (single source, verified)
    total_val = _resolved("total_val", raw_total_val)
    total_qty = _resolved("total_qty", raw_total_qty)

    # 2. Entity ranking & shares
    entity_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = _clean_str(r.get(name_col)) if name_col else ""
        if not name:
            name = _clean_str(r.get(code_col)) if code_col else "General Entity"
        if not name:
            continue

        v = _safe_float(r.get(val_col)) if val_col else 0.0
        q = _safe_float(r.get(qty_col)) if qty_col else 0.0
        cd = _clean_str(r.get(code_col)) if code_col else ""
        meta = ""
        for m_key in ("category", "item_group", "zone", "region", "city", "brand", "division"):
            if m_key in cols_map and r.get(cols_map[m_key]):
                meta = str(r[cols_map[m_key]])
                break

        if name not in entity_map:
            entity_map[name] = {"name": name, "code": cd, "val": 0.0, "qty": 0.0, "meta": meta}
        entity_map[name]["val"] += v
        entity_map[name]["qty"] += q

    ranked_entities = sorted(entity_map.values(), key=lambda x: x["val"], reverse=True)
    entity_count = len(ranked_entities) if ranked_entities else len(rows)

    for e in ranked_entities:
        e["share"] = (e["val"] / total_val * 100.0) if total_val > 0 else 0.0

    # 3. Concentrations
    top_3_val = sum(e["val"] for e in ranked_entities[:3])
    top_5_val = sum(e["val"] for e in ranked_entities[:5])
    top_3_share = (top_3_val / total_val * 100.0) if total_val > 0 else 0.0
    top_5_share = (top_5_val / total_val * 100.0) if total_val > 0 else 0.0

    if top_3_share > 70.0:
        concentration_risk = "HIGH"
    elif top_3_share > 45.0:
        concentration_risk = "MODERATE"
    else:
        concentration_risk = "BALANCED"

    # 4. Invoice & outlet counts (verified single-source; never count breakdown rows as orders)
    if "invoice_count" in summary_kpis and metric_valid.get("invoice_count", True):
        inv_count = int(_safe_float(summary_kpis["invoice_count"]))
    elif inv_col:
        inv_count = int(sum(_safe_float(r.get(inv_col)) for r in rows))
    elif not _has_entity_col(cols):
        inv_count = len(rows)
    else:
        inv_count = 0

    if "unique_outlets" in summary_kpis and metric_valid.get("unique_outlets", True):
        unique_outlets = int(_safe_float(summary_kpis["unique_outlets"]))
    elif out_col:
        unique_outlets = len({r.get(out_col) for r in rows if r.get(out_col)})
    else:
        unique_outlets = 0

    # 5. Averages
    avg_ticket = (total_val / inv_count) if inv_count > 0 else 0.0
    avg_realization = (total_val / total_qty) if total_qty > 0 else 0.0

    # 6. Advanced analytics
    advanced = _compute_advanced_metrics(ranked_entities, total_val)

    return ComputedAnalytics(
        total_val=total_val,
        total_qty=total_qty,
        entity_count=entity_count,
        avg_ticket=avg_ticket,
        avg_realization=avg_realization,
        invoice_count=inv_count,
        unique_outlets=unique_outlets,
        ranked_entities=ranked_entities,
        top_3_share=round(top_3_share, 1),
        top_5_share=round(top_5_share, 1),
        concentration_risk=concentration_risk,
        summary_kpis=summary_kpis,
        advanced=advanced,
        module=module,
        time_str=time_str,
        metric_valid=metric_valid,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 5: CONVERSATION MEMORY MANAGER (MULTI-TURN)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ConversationTurn:
    """Single analytical turn in a multi-turn conversation."""
    turn_index: int
    question: str
    module: str
    time_str: str
    kpis: Dict[str, Any]
    ranked_entities: List[Dict[str, Any]]
    pareto: Dict[str, Any]
    advanced_metrics: Optional[AdvancedMetrics]
    timestamp: datetime.datetime


@dataclasses.dataclass
class ConversationMemory:
    """Full multi-turn conversation analytical thread."""
    staff_uid: str
    conversation_id: str
    turns: List[ConversationTurn]
    entity_registry: Dict[str, Dict[str, Any]]
    created_at: datetime.datetime

    def latest_turn(self) -> Optional[ConversationTurn]:
        return self.turns[-1] if self.turns else None

    def find_turn_by_module(self, module: str) -> Optional[ConversationTurn]:
        latest = self.latest_turn()
        for turn in reversed(self.turns):
            if turn.module == module and turn != latest:
                return turn
        for turn in reversed(self.turns):
            if turn.module == module:
                return turn
        return None

    def find_entity_fuzzy(self, query: str) -> Optional[Dict[str, Any]]:
        q_low = query.lower()
        for name, data in self.entity_registry.items():
            if name.lower() in q_low or q_low in name.lower():
                return data
        for name, data in self.entity_registry.items():
            words = name.lower().split()
            if any(len(w) > 3 and w in q_low for w in words):
                return data
        return None

    def add_turn(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        if len(self.turns) > 20:
            self.turns.pop(0)
        for e in turn.ranked_entities:
            nm = e.get("name")
            if nm:
                self.entity_registry[nm] = {
                    "turn_index": turn.turn_index,
                    "val": e.get("val"),
                    "share": e.get("share"),
                    "qty": e.get("qty"),
                    "code": e.get("code"),
                    "module": turn.module,
                    "meta": e.get("meta", ""),
                }


_CONVERSATION_MEMORIES: Dict[Tuple[str, str], ConversationMemory] = {}
_MEMORY_LOCK = threading.Lock()
_MEMORY_CAP = 1000


def _get_memory(staff_uid: str, conversation_id: str) -> Optional[ConversationMemory]:
    key = (staff_uid or "", conversation_id or "")
    with _MEMORY_LOCK:
        return _CONVERSATION_MEMORIES.get(key)


def _save_memory(memory: ConversationMemory) -> None:
    key = (memory.staff_uid or "", memory.conversation_id or "")
    with _MEMORY_LOCK:
        if len(_CONVERSATION_MEMORIES) > _MEMORY_CAP:
            oldest = min(
                _CONVERSATION_MEMORIES.keys(),
                key=lambda k: _CONVERSATION_MEMORIES[k].created_at,
            )
            del _CONVERSATION_MEMORIES[oldest]
        _CONVERSATION_MEMORIES[key] = memory


def _push_turn_to_memory(
    staff_uid: str,
    conversation_id: str,
    analytics: ComputedAnalytics,
    question: str,
) -> None:
    """Persist computed analytics into the conversation memory thread."""
    if not staff_uid or not conversation_id:
        return

    mem = _get_memory(staff_uid, conversation_id)
    if mem is None:
        mem = ConversationMemory(
            staff_uid=staff_uid,
            conversation_id=conversation_id,
            turns=[],
            entity_registry={},
            created_at=datetime.datetime.now(),
        )

    turn_index = len(mem.turns)
    top_3_val = sum(_safe_float(e["val"]) for e in analytics.ranked_entities[:3])
    turn = ConversationTurn(
        turn_index=turn_index,
        question=question,
        module=analytics.module,
        time_str=analytics.time_str,
        kpis={
            "total_val": analytics.total_val,
            "total_qty": analytics.total_qty,
            "entity_count": analytics.entity_count,
            "avg_ticket": analytics.avg_ticket,
            "avg_realization": analytics.avg_realization,
            "invoice_count": analytics.invoice_count,
            "unique_outlets": analytics.unique_outlets,
        },
        ranked_entities=analytics.ranked_entities,
        pareto={
            "top_3_share": analytics.top_3_share,
            "top_3_val": top_3_val,
            "top_5_share": analytics.top_5_share,
            "concentration_risk": analytics.concentration_risk,
            "hhi_index": analytics.advanced.hhi_index,
            "gini": analytics.advanced.gini_coefficient,
            "pareto_80_count": analytics.advanced.pareto_80_count,
        },
        advanced_metrics=analytics.advanced,
        timestamp=datetime.datetime.now(),
    )
    mem.add_turn(turn)
    _save_memory(mem)


# ─────────────────────────────────────────────────────────────────────────────
# MODULE CONFIG — DMS DOMAIN SPECIFIC VOCABULARY & DIRECTIVES
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ModuleConfig:
    """Per-module vocabulary and template metadata for DMS domains."""
    module: str
    domain_label: str
    entity_noun: str
    entity_noun_plural: str
    value_label: str
    leaderboard_title: str
    medal_labels: List[str]

    def build_directives(self, analytics: ComputedAnalytics) -> str:
        """
        Fully DYNAMIC directives — computed from real data, not static text.
        Each directive uses actual calculated values from ComputedAnalytics.
        """
        ents = analytics.ranked_entities
        top1 = ents[0] if ents else {}
        top1_name = top1.get("name", f"Lead {self.entity_noun}")
        top1_val = _safe_float(top1.get("val"))
        top1_share = _safe_float(top1.get("share"))
        top2 = ents[1] if len(ents) > 1 else {}
        top2_name = top2.get("name", f"Runner-Up {self.entity_noun}")
        top2_val = _safe_float(top2.get("val"))
        adv = analytics.advanced
        total_val = analytics.total_val
        avg_ticket = analytics.avg_ticket

        directives: List[str] = []
        lines = [" Prescriptive Commercial Directives\n"]

        if self.module in ("secondary_sales", "purchases", "primary_sales"):
            if top1_name and top1_share > 0:
                buffer_days = max(7, round(top1_share / 5))
                lines.append(
                    f"- 1. Lead Anchor Buffer Protocol: Guarantee a {buffer_days}-day forward safety stock "
                    f"cover for {top1_name} (contributes {top1_share:.1f}% of throughput). "
                    f"Any stockout event destroys {top1_share:.1f}% of current run-rate revenue."
                )
            if top2_name and top2_val > 0:
                target_ticket = avg_ticket * 1.2 if avg_ticket > 0 else 0.0
                lines.append(
                    f"- 2. Counter Basket Uplift: Leverage the high offtake of {top1_name} to introduce "
                    f"dealer combo packs with {top2_name}. Target lifting average ticket beyond "
                    f"{_fmt_inr(target_ticket)} per invoice."
                )
            if adv.pareto_80_count <= 2 and analytics.entity_count > 3:
                lines.append(
                    f"- 3. Pareto De-Risking Action: Top {adv.pareto_80_count} {self.entity_noun_plural} deliver "
                    f"80% of revenue. Deploy promotional scheme slabs to activate the remaining "
                    f"{analytics.entity_count - adv.pareto_80_count} accounts in the CORE and TAIL tiers."
                )
            else:
                lines.append(
                    f"- 3. Channel Liquidation Parity: Reconcile secondary offtake against warehouse stock balances "
                    f"to prevent aging batch stagnation across regional distribution hubs."
                )

        elif self.module in ("stock_movement", "stock_clearance"):
            if top1_name and top1_share > 0:
                lines.append(
                    f"- 1. Priority Liquidation Focus: {top1_name} holds {top1_share:.1f}% of total stock position. "
                    f"Initiate dealer clearance discounts to rotate older inventory batches before near-expiry thresholds."
                )
            if adv.outlier_entities:
                outlier_name = adv.outlier_entities[0].get("name", "Top Outlier")
                lines.append(
                    f"- 2. Warehouse Stock Balancing: {outlier_name} shows abnormal volume variance (+{adv.outlier_entities[0].get('z_score', 0):.1f}σ). "
                    f"Rebalance distribution quotas across surrounding regional depots."
                )
            lines.append(
                f"- 3. Dead Stock Rationalization: Conduct stock audits on items in DORMANT tier (<1% share) "
                f"to recover blocked working capital."
            )

        elif self.module == "claims":
            if top1_name and top1_share > 0:
                lines.append(
                    f"- 1. Expedited Settlement Priority: Prioritize settlement audits for {top1_name} "
                    f"(accounts for {top1_share:.1f}% of total claim value) to unblock distributor credit limits."
                )
            lines.append(
                f"- 2. Dispute Root-Cause Governance: Review documentation for top rejected claims to streamline "
                f"approval TAT and eliminate repeat claim filing discrepancies."
            )
            lines.append(
                f"- 3. Reconciliation Cadence: Synchronize claim credits with monthly primary billing invoices to maintain "
                f"seamless supply order flow."
            )

        else:
            if top1_name and top1_share > 0:
                lines.append(
                    f"- 1. Core Account Protection: Ensure uninterrupted order execution and service priority for {top1_name}."
                )
            if avg_ticket > 0:
                lines.append(
                    f"- 2. Average Order Lift: Current average transaction ticket is {_fmt_inr(avg_ticket)}. "
                    f"Push toward {_fmt_inr(avg_ticket * 1.2)} via tiered incentive slabs."
                )
            lines.append(
                f"- 3. Portfolio Diversification: Accelerate dealer adoption across lower-tier accounts to improve distribution parity."
            )

        return "\n".join(lines)

    def build_cross_inquiries(self, analytics: ComputedAnalytics) -> str:
        """Dynamic cross-inquiry suggestions using actual entity names from data."""
        ents = analytics.ranked_entities
        top1_name = ents[0].get("name", "#1") if ents else "#1"
        top2_name = ents[1].get("name", "#2") if len(ents) > 1 else "#2"
        time_str = analytics.time_str

        base = [" Contextual Cross-Inquiries\n"]

        if self.module in ("secondary_sales", "purchases", "primary_sales"):
            base += [
                f'- "Compare #1 and #2"',
                f'- "How did {top2_name} perform in {time_str}?"',
                f'- "What if {top1_name} grew 20%?"',
                f'- "Show me CORE tier only"',
                f'- "Break this down by brand"',
                f'- "Why is concentration high?"',
            ]
        elif self.module in ("stock_movement", "stock_clearance"):
            base += [
                f'- "Compare closing stock for #1 and #2"',
                f'- "Which items are in DORMANT tier?"',
                f'- "Show near-expiry batches"',
                f'- "Breakdown stock movement by warehouse"',
            ]
        elif self.module == "claims":
            base += [
                f'- "Compare approved vs pending claims"',
                f'- "Show claims breakdown for {top1_name}"',
                f'- "Which claim types have highest rejection?"',
            ]
        else:
            base += [
                f'- "Compare #1 and #2"',
                f'- "Show long-tail contributors"',
                f'- "What if {top1_name} grew 15%?"',
            ]

        return "\n".join(base[:6])


_MODULE_CONFIGS: Dict[str, ModuleConfig] = {
    "secondary_sales": ModuleConfig(
        module="secondary_sales",
        domain_label="Secondary Sales",
        entity_noun="Distributor",
        entity_noun_plural="Distributors",
        value_label="Offtake Sales",
        leaderboard_title="Top Liquidating Distributors",
        medal_labels=["#1 Lead Distributor", "#2 Runner-Up", "#3 Third Contributor", " #4 Distributor", " #5 Distributor"],
    ),
    "purchases": ModuleConfig(
        module="purchases",
        domain_label="Purchases & Inward",
        entity_noun="Vendor / Supplier",
        entity_noun_plural="Vendors / Suppliers",
        value_label="Purchase Inward Value",
        leaderboard_title="Top Replenishment Vendors",
        medal_labels=["#1 Lead Vendor", "#2 Secondary Supplier", "#3 Third Supplier", " #4 Vendor", " #5 Vendor"],
    ),
    "primary_sales": ModuleConfig(
        module="primary_sales",
        domain_label="Primary Sales",
        entity_noun="Distributor",
        entity_noun_plural="Distributors",
        value_label="Primary Invoiced Sales",
        leaderboard_title="Top Primary Billing Distributors",
        medal_labels=["#1 Lead Distributor", "#2 Runner-Up", "#3 Third Contributor", " #4 Distributor", " #5 Distributor"],
    ),
    "stock_movement": ModuleConfig(
        module="stock_movement",
        domain_label="Stock Movement",
        entity_noun="Item / SKU",
        entity_noun_plural="Items / SKUs",
        value_label="Inventory Position Value",
        leaderboard_title="Top Stock Volume Items",
        medal_labels=["#1 Lead Inventory SKU", "#2 Runner-Up SKU", "#3 Third SKU", " #4 SKU", " #5 SKU"],
    ),
    "stock_clearance": ModuleConfig(
        module="stock_clearance",
        domain_label="Stock Clearance & Aging",
        entity_noun="Batch / SKU",
        entity_noun_plural="Batches / SKUs",
        value_label="Clearance Value",
        leaderboard_title="Priority Clearance Batches",
        medal_labels=["#1 Critical Batch", "#2 Secondary Batch", "#3 Third Batch", " #4 Batch", " #5 Batch"],
    ),
    "claims": ModuleConfig(
        module="claims",
        domain_label="Claims Management",
        entity_noun="Distributor / Claim Type",
        entity_noun_plural="Claims / Accounts",
        value_label="Claim Settlement Value",
        leaderboard_title="Top Outstanding Claim Accounts",
        medal_labels=["#1 Primary Claim Counter", "#2 Second Counter", "#3 Third Counter", " #4 Counter", " #5 Counter"],
    ),
    "schemes": ModuleConfig(
        module="schemes",
        domain_label="Trade Schemes & Promos",
        entity_noun="Scheme",
        entity_noun_plural="Schemes",
        value_label="Scheme Discount / Uplift",
        leaderboard_title="Top Active Trade Schemes",
        medal_labels=["#1 Lead Promotion", "#2 Secondary Scheme", "#3 Third Scheme", " #4 Scheme", " #5 Scheme"],
    ),
    "masters": ModuleConfig(
        module="masters",
        domain_label="Master Registries",
        entity_noun="Account",
        entity_noun_plural="Accounts",
        value_label="Commercial Volume",
        leaderboard_title="Top Registered Accounts",
        medal_labels=["#1 Lead Account", "#2 Runner-Up Account", "#3 Third Account", " #4 Account", " #5 Account"],
    ),
    "generic": ModuleConfig(
        module="generic",
        domain_label="Commercial Intelligence",
        entity_noun="Entity",
        entity_noun_plural="Entities",
        value_label="Commercial Value",
        leaderboard_title="Top Contributing Entities",
        medal_labels=["#1 Lead Contributor", "#2 Runner-Up", "#3 Third Entity", " #4 Entity", " #5 Entity"],
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4: COMPOSABLE BRIEFING BLOCK ASSEMBLER
# ─────────────────────────────────────────────────────────────────────────────

def _block_executive_digest(
    analytics: ComputedAnalytics,
    config: ModuleConfig,
    question: str,
) -> str:
    """Block 1 — High-level strategic briefing with contextual title."""
    clean_title = _clean_question_title(question, config.domain_label)
    top1 = analytics.ranked_entities[0] if analytics.ranked_entities else {}
    top1_name = top1.get("name", "")
    top1_share = _safe_float(top1.get("share"))

    intro_map = {
        "secondary_sales": "Consolidated secondary distributor offtake to retail network",
        "purchases": "Primary supplier inward dispatches and inventory replenishment",
        "primary_sales": "Consolidated company-to-distributor primary billing throughput",
        "stock_movement": "Warehouse inventory balance and warehouse flow position",
        "stock_clearance": "Aging inventory risk evaluation and near-expiry batch audit",
        "claims": "Commercial claim submissions, approvals, and pending settlement balances",
        "schemes": "Trade promotion performance, scheme discounts, and dealer uptake",
        "masters": "Master network registration, counter coverage, and active status",
        "generic": "Commercial operational activity records",
    }
    intro = intro_map.get(analytics.module, "Operational activity records")

    val_str = f"**{_fmt_inr(analytics.total_val)}**" if analytics.total_val > 0 else "no measurable commercial value"
    qty_str = f" ({_fmt_num(analytics.total_qty)} units)" if analytics.total_qty > 0 else ""
    inv_str = f" across **{analytics.invoice_count} logged bills/transactions**" if analytics.invoice_count > 1 else ""
    top1_str = f" Velocity is anchored by **{top1_name}**, commanding **{top1_share:.1f}%** of total commercial throughput." if top1_name and top1_share > 0 else ""

    return (
        f"Executive Strategic Briefing: {clean_title}\n\n"
        f"{intro} covering **{analytics.time_str}**:\n\n"
        f"Operational Digest: Realized {config.value_label.lower()} reached {val_str}"
        f"{inv_str} across {analytics.entity_count} {config.entity_noun_plural.lower()}{qty_str}.{top1_str}"
    )


def _block_kpi_snapshot(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """Block 2 — Multi-dimensional KPI command panel."""
    total_val = analytics.total_val
    total_qty = analytics.total_qty
    entity_count = analytics.entity_count
    avg_ticket = analytics.avg_ticket
    avg_real = analytics.avg_realization
    inv_count = analytics.invoice_count
    outlets = analytics.unique_outlets
    adv = analytics.advanced

    if total_val > 1_000_000:
        status = " High Velocity — Strong Commercial Momentum"
    elif total_val > 250_000:
        status = " Moderate Throughput — Active Growth"
    elif total_val > 50_000:
        status = " Building Cadence — Below Potential Target"
    elif total_val > 0:
        status = " Low Throughput — Attention Required"
    else:
        status = ""

    lines = [f" {config.domain_label} KPI Command Snapshot\n"]

    if total_val > 0:
        lines.append(f"- Net {config.value_label}: {_fmt_inr(total_val)}")
    if total_qty > 0:
        lines.append(f"- Physical Volume: {_fmt_num(total_qty)} units")
    lines.append(f"- Active {config.entity_noun_plural}: {entity_count}")
    if inv_count > 1:
        lines.append(f"- Transaction Count: {inv_count:,} bills/vouchers")
    if outlets > 0:
        lines.append(f"- Counter Reach: {outlets:,} unique accounts")
    if avg_ticket > 0:
        lines.append(f"- Average Order Value (AOV): {_fmt_inr(avg_ticket)} per bill")
    if avg_real > 0:
        lines.append(f"- Average Unit Realization: {_fmt_inr(avg_real)} per unit")
    if analytics.top_3_share > 0 and entity_count >= 3:
        lines.append(f"- Top-3 Concentration: {analytics.top_3_share:.1f}% of total {config.value_label.lower()}")
    if adv.coefficient_of_variation > 0:
        lines.append(f"- Distribution Spread (CV): {adv.coefficient_of_variation:.1f}% ({'Highly Unequal' if adv.coefficient_of_variation > 80 else 'Moderate Variance' if adv.coefficient_of_variation > 40 else 'Even Spread'})")
    if status:
        lines.append(f"- Commercial Health Signal: {status}")

    return "\n".join(lines)


def _block_leaderboard(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """Block 3 — Top-5 ranked entity leaderboard with tier tags."""
    ents = analytics.ranked_entities
    top5 = ents[:5]
    total_val = analytics.total_val
    adv = analytics.advanced

    lines = [f" {config.leaderboard_title}\n"]
    medals = config.medal_labels

    for idx, e in enumerate(top5):
        nm = e.get("name", f"{config.entity_noun} #{idx+1}")
        cd = e.get("code", "")
        val = _safe_float(e.get("val"))
        qty = _safe_float(e.get("qty"))
        share = _safe_float(e.get("share"))
        meta = e.get("meta", "")
        tier = adv.entity_tiers.get(nm, "")

        title_part = f"{nm} (Code: {cd})" if (cd and cd != nm) else nm
        qty_str = f" - {_fmt_num(qty)} units" if qty > 0 else ""
        meta_str = f" - {meta}" if meta else ""
        tier_str = f" [{tier}]" if tier else ""
        m_label = medals[idx] if idx < len(medals) else f" #{idx+1}"

        lines.append(f"- {m_label} — {title_part}: {_fmt_inr(val)} ({share:.1f}% share{qty_str}{meta_str}){tier_str}")

    # Long-tail summary
    remaining = ents[5:]
    if remaining and total_val > 0:
        rem_val = sum(_safe_float(e.get("val")) for e in remaining)
        rem_share = rem_val / total_val * 100.0 if total_val > 0 else 0.0
        rem_qty = sum(_safe_float(e.get("qty")) for e in remaining)
        qty_str = f" - {_fmt_num(rem_qty)} units" if rem_qty > 0 else ""
        avg_tail = rem_val / len(remaining) if remaining else 0.0
        lines.append(
            f"- Long-Tail ({len(remaining)} other {config.entity_noun_plural.lower()}): "
            f"{_fmt_inr(rem_val)} combined ({rem_share:.1f}% share{qty_str} - avg {_fmt_inr(avg_tail)}/{config.entity_noun})"
        )

    return "\n".join(lines)


def _block_pareto_diagnostic(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """Block 4 — Concentration risk with HHI + Gini + computed interpretation."""
    adv = analytics.advanced
    top1 = analytics.ranked_entities[0] if analytics.ranked_entities else {}
    top1_name = top1.get("name", f"Lead {config.entity_noun}")
    top1_share = _safe_float(top1.get("share"))

    # HHI interpretation
    if adv.hhi_index > 2500:
        hhi_label = "HIGHLY CONCENTRATED"
    elif adv.hhi_index > 1500:
        hhi_label = "MODERATELY CONCENTRATED"
    else:
        hhi_label = "COMPETITIVE SPREAD"

    # Gini interpretation
    gini_label = "HIGH inequality" if adv.gini_coefficient > 0.6 else ("MODERATE inequality" if adv.gini_coefficient > 0.4 else "LOW inequality — healthy spread")

    lines = [" Strategic Pareto Concentration Diagnostic\n"]

    if analytics.concentration_risk == "HIGH":
        lines.append(
            f"- High Portfolio Concentration Alert: Top 3 {config.entity_noun_plural.lower()} command "
            f"**{analytics.top_3_share:.1f}%** of total {config.value_label.lower()}. "
            f"**{top1_name}** alone accounts for **{top1_share:.1f}%**. "
            f"HHI = **{adv.hhi_index:,.0f}** ({hhi_label}). Gini = **{adv.gini_coefficient:.2f}** ({gini_label})."
        )
        lines.append(
            f"- Pareto 80/20: Only **{adv.pareto_80_count} {config.entity_noun_plural.lower()}** needed to reach 80% of total throughput — "
            f"{'extreme single-account dependence' if adv.pareto_80_count == 1 else 'tight anchor risk'}. "
            f"Prioritise diversification across CORE and TAIL tiers."
        )
    elif analytics.concentration_risk == "MODERATE":
        lines.append(
            f"- Moderate Portfolio Concentration: Top 3 {config.entity_noun_plural.lower()} contribute "
            f"**{analytics.top_3_share:.1f}%** of total. HHI = **{adv.hhi_index:,.0f}** ({hhi_label}). "
            f"Manageable concentration — monitor top accounts for stockout or credit friction."
        )
    else:
        lines.append(
            f"- Balanced Commercial Spread Verified: Volume is well-distributed across your "
            f"active portfolio, with top 3 {config.entity_noun_plural.lower()} contributing **{analytics.top_3_share:.1f}%**. "
            f"HHI = **{adv.hhi_index:,.0f}** ({hhi_label}). Broad commercial risk diversification confirmed."
        )

    return "\n".join(lines)


def _block_anomaly_alert(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """Block 5 — Statistical outlier detection with z-scores."""
    adv = analytics.advanced
    if not adv.outlier_entities:
        return ""

    lines = [" Statistical Anomaly Detection\n"]
    for e in adv.outlier_entities[:3]:
        nm = e.get("name", "Unknown")
        z = e.get("z_score", 0.0)
        val = _safe_float(e.get("val"))
        share = _safe_float(e.get("share"))
        direction = "overperformer" if z > 0 else "underperformer"
        lines.append(
            f"- {'High ' if z > 0 else 'Low '} Outlier — {nm}: "
            f"z-score **{z:+.1f}σ** — statistical {direction}, generating {_fmt_inr(val)} ({share:.1f}% share). "
            f"{'Monitor for supply chain reliance.' if z > 0 else 'Investigate root cause: stockout, pricing, or ordering lapse.'}"
        )
    return "\n".join(lines)


def _block_portfolio_segmentation(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """Block 6 — ANCHOR/CORE/TAIL/DORMANT tier distribution."""
    adv = analytics.advanced
    if len(analytics.ranked_entities) < 4:
        return ""

    tiers: Dict[str, List[str]] = {"ANCHOR": [], "CORE": [], "TAIL": [], "DORMANT": []}
    for e in analytics.ranked_entities:
        nm = e.get("name", "")
        tier = adv.entity_tiers.get(nm, "DORMANT")
        tiers[tier].append(nm)

    lines = [f" Portfolio Tier Segmentation ({config.entity_noun} Classification)\n"]

    tier_def = {
        "ANCHOR": "≥25% share — Revenue-critical, protect",
        "CORE": "5–25% share — Growth candidates, expand",
        "TAIL": "1–5% share — Basket lift candidates",
        "DORMANT": "<1% share — Evaluate for reactivation",
    }
    for tier, names in tiers.items():
        if names:
            sample = ", ".join(names[:2])
            suffix = f" and {len(names) - 2} more" if len(names) > 2 else ""
            lines.append(
                f"- {tier} ({tier_def[tier]}): {len(names)} {config.entity_noun_plural.lower()} — {sample}{suffix}"
            )

    return "\n".join(lines)


def _assemble_briefing(
    analytics: ComputedAnalytics,
    config: ModuleConfig,
    question: str,
) -> str:
    """Layer 4 compositor — conditionally assembles all blocks into final briefing."""
    sections: List[str] = []

    # Block 1: Always
    sections.append(_block_executive_digest(analytics, config, question))

    # Block 2: Always
    sections.append(_block_kpi_snapshot(analytics, config))

    # Block 3: Leaderboard — when ≥ 2 entities
    if len(analytics.ranked_entities) >= 2:
        sections.append(_block_leaderboard(analytics, config))

    # Block 4: Pareto diagnostic — when ≥ 3 entities
    if len(analytics.ranked_entities) >= 3:
        sections.append(_block_pareto_diagnostic(analytics, config))

    # Block 5: Anomaly alert — when outliers detected
    anomaly_block = _block_anomaly_alert(analytics, config)
    if anomaly_block:
        sections.append(anomaly_block)

    # Block 6: Portfolio segmentation — when ≥ 4 entities
    seg_block = _block_portfolio_segmentation(analytics, config)
    if seg_block:
        sections.append(seg_block)

    # Block 7: Dynamic directives (computed from data)
    directives = config.build_directives(analytics)
    if directives:
        sections.append(directives)

    # Block 8: Dynamic cross-inquiry suggestions
    sections.append(config.build_cross_inquiries(analytics))

    return "\n\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# MODULE TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _detect_module_type(flag_name: str, question: str, cols: List[str]) -> str:
    """Classify request into exact DMS business module."""
    f = (flag_name or "").lower()
    q = (question or "").lower()
    cols_l = [c.lower() for c in cols]

    # Flag matching
    if f.startswith("pur") or "purchase" in f or "inward" in f:
        return "purchases"
    if f.startswith("pr") or "primary" in f:
        return "primary_sales"
    if f.startswith("sm") or "stock_movement" in f or "movement" in f:
        return "stock_movement"
    if f.startswith("sch") or "scheme" in f:
        return "schemes"
    if f.startswith("sc") or "clearance" in f or "expiry" in f:
        return "stock_clearance"
    if f.startswith("clm") or "claim" in f:
        return "claims"
    if f.startswith("mst") or "master" in f:
        return "masters"
    if f.startswith("ss") or "secondary" in f:
        return "secondary_sales"

    # Question text fallback
    if any(k in q for k in ("purchase", "purchases", "inward", "grn", "vendor")):
        return "purchases"
    if any(k in q for k in ("primary sale", "primary order", "primary dispatch", "indent")):
        return "primary_sales"
    if any(k in q for k in ("closing stock", "stock movement", "warehouse stock", "inventory balance")):
        return "stock_movement"
    if any(k in q for k in ("clearance", "near expiry", "aging stock", "slow moving")):
        return "stock_clearance"
    if any(k in q for k in ("claim", "claims", "settlement", "rate difference")):
        return "claims"
    if any(k in q for k in ("scheme", "schemes", "trade promo", "discount slab")):
        return "schemes"
    if any(k in q for k in ("secondary", "offtake", "dealer sales", "retail sales")):
        return "secondary_sales"
    if any(k in q for k in ("master", "catalog", "registered distributor", "dealer list")):
        return "masters"

    # Column inspection fallback
    if any("purchase" in c for c in cols_l):
        return "purchases"
    if any("claim" in c for c in cols_l):
        return "claims"
    if any("stock" in c for c in cols_l):
        return "stock_movement"
    if any("scheme" in c for c in cols_l):
        return "schemes"

    return "generic"


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 6: ADVANCED IN-MEMORY CROSS-QUESTIONING ENGINE (10 PATTERNS, <5ms)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_cross_questioning(
    staff_uid: str,
    conversation_id: str,
    question: str,
) -> Optional[str]:
    """
    Evaluates in-memory cross-questioning against conversation memory.
    Returns executive briefing response string in <5ms with zero LLM tokens and zero DB queries.
    Covers 10 distinct analytical cross-questioning patterns.
    """
    mem = _get_memory(staff_uid, conversation_id)
    if not mem or not mem.turns:
        return None

    turn = mem.latest_turn()
    if not turn:
        return None

    q = (question or "").strip().lower()
    entities = turn.ranked_entities
    kpis = turn.kpis
    pareto = turn.pareto
    total_val = _safe_float(kpis.get("total_val"))
    total_qty = _safe_float(kpis.get("total_qty"))
    time_str = turn.time_str
    adv = turn.advanced_metrics

    # ── Pattern H: What-If Scenario Projection ────────────────────────────────
    scenario_match = re.search(
        r"what\s+if\s+(?:the\s+)?([a-zA-Z0-9_\s]+?)\s+(grew|dropped|increased|fell|declined)\s+(by\s+)?(\d+(?:\.\d+)?)%",
        q,
    )
    if scenario_match and entities:
        target_name_raw = scenario_match.group(1).strip()
        direction = scenario_match.group(2)
        growth_pct = float(scenario_match.group(4)) / 100.0
        if direction in ("dropped", "fell", "declined"):
            growth_pct = -growth_pct

        target_ent = None
        if target_name_raw in ("top", "#1", "first", "lead", "leader"):
            target_ent = entities[0]
        elif target_name_raw in ("runner up", "#2", "second"):
            target_ent = entities[1] if len(entities) > 1 else entities[0]
        else:
            for e in entities:
                if target_name_raw.lower() in e.get("name", "").lower():
                    target_ent = e
                    break
        if not target_ent:
            target_ent = entities[0]

        ent_name = target_ent.get("name", "Target Entity")
        old_val = _safe_float(target_ent.get("val"))
        old_share = _safe_float(target_ent.get("share"))
        new_val = max(0.0, old_val * (1.0 + growth_pct))
        val_gain = new_val - old_val
        new_total = max(1.0, total_val + val_gain)
        new_share = (new_val / new_total * 100.0)

        other_vals = [_safe_float(e.get("val")) for e in entities if e.get("name") != ent_name]
        new_top3 = new_val + sum(sorted(other_vals, reverse=True)[:2])
        new_top3_share = (new_top3 / new_total * 100.0) if new_total > 0 else 0.0

        return (
            f"Scenario Analysis: What If **{ent_name}** Grew {growth_pct*100:+.0f}%?\n\n"
            f"Hypothetical projection applied to **{ent_name}** in **{time_str}**:\n\n"
            f" Before vs After Projection:\n"
            f"- **{ent_name} Revenue:** {_fmt_inr(old_val)} → **{_fmt_inr(new_val)}** ({val_gain:+,.0f})\n"
            f"- **{ent_name} Share:** {old_share:.1f}% → **{new_share:.1f}%** ({new_share - old_share:+.1f}pp)\n"
            f"- **Total Territory Revenue:** {_fmt_inr(total_val)} → **{_fmt_inr(new_total)}** ({val_gain:+,.0f})\n"
            f"- **Top-3 Concentration:** {_safe_float(pareto.get('top_3_share')):.1f}% → **{new_top3_share:.1f}%** ({new_top3_share - _safe_float(pareto.get('top_3_share')):+.1f}pp)\n\n"
            f" Scenario Implications:\n"
            f"- A **{growth_pct*100:+.0f}% change** in **{ent_name}** shifts total territory revenue by **{_fmt_inr(val_gain)}**.\n"
            f"- Share adjusts from **{old_share:.1f}%** → **{new_share:.1f}%**."
        )

    # ── Pattern A: Head-to-Head Comparison (#1 vs #2) ─────────────────────────
    is_comparison = bool(
        re.search(r"\b(compare|comparison|difference|gap|vs|versus|variance)\b", q)
        and any(t in q for t in ("1", "2", "top", "lead", "runner", "first", "second", "both"))
    )
    if is_comparison and len(entities) >= 2:
        top1 = entities[0]
        top2 = entities[1]
        v1, v2 = _safe_float(top1.get("val")), _safe_float(top2.get("val"))
        s1, s2 = _safe_float(top1.get("share")), _safe_float(top2.get("share"))
        q1, q2 = _safe_float(top1.get("qty")), _safe_float(top2.get("qty"))
        gap = abs(v1 - v2)
        ratio = (v1 / v2) if v2 > 0 else 1.0

        return (
            f"Head-to-Head Commercial Comparison: #1 vs #2\n\n"
            f"Comparing lead contributors for **{time_str}**:\n\n"
            f" Comparative Contribution Breakdown:\n"
            f"- **#1 — {top1.get('name')}:** {_fmt_inr(v1)} ({s1:.1f}% share"
            f"{f' - {_fmt_num(q1)} units' if q1 > 0 else ''})\n"
            f"- **#2 — {top2.get('name')}:** {_fmt_inr(v2)} ({s2:.1f}% share"
            f"{f' - {_fmt_num(q2)} units' if q2 > 0 else ''})\n\n"
            f" Commercial Variance & Gap Diagnostic:\n"
            f"- **Revenue Differential:** {_fmt_inr(gap)} commercial lead for **{top1.get('name')}**.\n"
            f"- **Multiplication Factor:** **{top1.get('name')}** operates at **{ratio:.1f}x** the throughput of **{top2.get('name')}**.\n"
            f"- **Combined Share:** Together, these top 2 represent **{s1 + s2:.1f}%** of total commercial volume."
        )

    # ── Pattern B: Specific Rank or Top Account Inquiry ───────────────────────
    # Matches: "who is top", "top distributor", "#1", "#2", "second", "third", etc.
    target_rank = None
    if re.search(r"\b(who\s+is|what\s+is|show|tell\s+me|name)\s+(?:the\s+)?(top|leader|lead|#?1|first)\b", q) or q in ("top", "#1", "who is top", "top distributor", "top 1"):
        target_rank = 1
    elif re.search(r"\b(who\s+is|what\s+is|show|tell\s+me)\s+(?:the\s+)?(#?2|second|runner\s*up)\b", q):
        target_rank = 2
    elif re.search(r"\b(who\s+is|what\s+is|show|tell\s+me)\s+(?:the\s+)?(#?3|third)\b", q):
        target_rank = 3
    else:
        rank_match = re.search(r"\b(?:who\s+is|what\s+is|how\s+did|show)\s+(?:the\s+)?#?([1-9]|10)(?:nd|rd|th)?\b", q)
        if rank_match:
            target_rank = int(rank_match.group(1))

    if target_rank is not None and entities and target_rank <= len(entities):
        e = entities[target_rank - 1]
        nm = e.get("name")
        val = _safe_float(e.get("val"))
        share = _safe_float(e.get("share"))
        qty = _safe_float(e.get("qty"))
        tier = adv.entity_tiers.get(nm, "CORE") if adv else "CORE"

        next_diff_line = ""
        if target_rank > 1:
            diff_above = abs(val - _safe_float(entities[target_rank - 2].get("val")))
            next_diff_line = f"\n\n Growth Opportunity:\n- To match #{target_rank-1} ({entities[target_rank-2].get('name')}), an incremental lift of **{_fmt_inr(diff_above)}** is required."
        elif len(entities) > 1:
            lead_over_second = abs(val - _safe_float(entities[1].get("val")))
            next_diff_line = f"\n\n Market Dominance:\n- Holds a **{_fmt_inr(lead_over_second)}** lead over #2 ({entities[1].get('name')})."

        return (
            f"Contributor Rank Profile: #{target_rank} — {nm}\n\n"
            f"Performance metrics for **{nm}** in **{time_str}**:\n\n"
            f" Commercial Standing:\n"
            f"- **Territory Rank:** #{target_rank} of {len(entities)} active accounts\n"
            f"- **Realized Revenue:** {_fmt_inr(val)} ({share:.1f}% share)\n"
            f"{f'- **Physical Volume:** {_fmt_num(qty)} units\n' if qty > 0 else ''}"
            f"- **Portfolio Classification:** **{tier}** Tier"
            f"{next_diff_line}"
        )

    # ── Pattern C: Total KPIs / Summary Inquiry ──────────────────────────────
    if re.search(r"\b(total|overall|aggregate|sum|how\s+much)\s+(sales|revenue|value|purchases|turnover|volume|amount)\b", q) or q in ("total", "total sales", "total value"):
        avg_val = total_val / len(entities) if entities else 0.0
        return (
            f"Aggregated Portfolio Performance Overview\n\n"
            f"Commercial totals recorded for **{time_str}**:\n\n"
            f" Key Portfolio Aggregates:\n"
            f"- **Total Revenue Realized:** **{_fmt_inr(total_val)}**\n"
            f"{f'- **Total Physical Volume:** **{_fmt_num(total_qty)} units**\n' if total_qty > 0 else ''}"
            f"- **Active Commercial Accounts:** **{len(entities)} contributors**\n"
            f"- **Average Revenue per Account:** **{_fmt_inr(avg_val)}**\n\n"
            f"Top contributor **{entities[0].get('name') if entities else 'N/A'}** accounts for **{_safe_float(entities[0].get('share')) if entities else 0.0:.1f}%** of this aggregate."
        )

    # ── Pattern D: Entity Count / Scope Inquiry ──────────────────────────────
    if re.search(r"\b(how\s+many|count\s+of|number\s+of)\s+(entities|distributors|accounts|dealers|records|skus|customers)\b", q):
        return (
            f"Portfolio Scope & Coverage\n\n"
            f"Portfolio coverage for **{time_str}**:\n\n"
            f"- **Active Transacting Accounts:** **{len(entities)} accounts**\n"
            f"- **Top Tier (Anchor):** **{sum(1 for e in entities if adv and adv.entity_tiers.get(e.get('name')) == 'ANCHOR')} accounts**\n"
            f"- **Core Performing Tier:** **{sum(1 for e in entities if adv and adv.entity_tiers.get(e.get('name')) == 'CORE')} accounts**\n"
            f"- **Long-Tail / At-Risk Tier:** **{sum(1 for e in entities if adv and adv.entity_tiers.get(e.get('name')) in ('TAIL', 'DORMANT'))} accounts**"
        )

    # ── Pattern E: Prescriptive Commercial Directives ────────────────────────
    if re.search(r"\b(directive|directives|action|actions|recommend|recommendations|prescriptive|next\s+steps|what\s+should\s+i\s+do)\b", q):
        top1 = entities[0] if entities else {}
        top1_name = top1.get("name", "Lead Account")
        top1_share = _safe_float(top1.get("share"))
        lines = [
            f"Prescriptive Directives for {time_str}\n\n",
            f"- **1. Lead Buffer Protocol:** Maintain safety stock coverage for **{top1_name}** (drives {top1_share:.1f}% of throughput).\n",
            f"- **2. Core Expansion Drive:** Run targeted reorder promotions across CORE accounts to dilute concentration risk.\n",
            f"- **3. Long-Tail Reactivation:** Review the bottom {max(1, len(entities)//3)} accounts for minimum order compliance."
        ]
        return "".join(lines)

    # ── Pattern F: Concentration & Pareto Diagnostics ────────────────────────
    if re.search(r"\b(pareto|concentration|concentrated|risk|hhi|gini|80\s*20)\b", q):
        top1 = entities[0] if entities else {}
        top1_name = top1.get("name", "Top Account")
        top1_share = _safe_float(top1.get("share"))
        t3 = _safe_float(pareto.get("top_3_share"))
        hhi = adv.hhi_index if adv else 0.0
        gini = adv.gini_coefficient if adv else 0.0

        return (
            f"Strategic Concentration Risk Analysis\n\n"
            f"Concentration diagnostics for **{time_str}**:\n\n"
            f" Concentration Indicators:\n"
            f"- **Top-1 Share:** **{top1_name}** commands **{top1_share:.1f}%** of total commercial volume.\n"
            f"- **Top-3 Combined Share:** **{t3:.1f}%** across the top 3 accounts.\n"
            f"- **Herfindahl–Hirschman Index (HHI):** **{hhi:,.0f}** ({'High Concentration' if hhi > 2500 else 'Moderate Concentration' if hhi > 1500 else 'Competitive Spread'}).\n"
            f"- **Gini Coefficient:** **{gini:.2f}** ({'Severe inequality' if gini > 0.6 else 'Moderate variance'}).\n\n"
            f" Prescriptive Mitigation:\n"
            f"- Introduce reorder promotional incentives for accounts in the CORE tier to diversify commercial throughput."
        )

    # ── Pattern G: Average Ticket / Benchmark Inquiry ─────────────────────────
    if re.search(r"\b(average|avg|ticket|mean|benchmark)\b", q):
        avg_ticket = total_val / len(entities) if entities else 0.0
        return (
            f"Commercial Benchmark & Ticket Size Diagnostics\n\n"
            f"Benchmark analysis for **{time_str}**:\n\n"
            f"- **Average Revenue per Contributor:** **{_fmt_inr(avg_ticket)}**\n"
            f"- **Top Performer Run-Rate:** **{_fmt_inr(_safe_float(entities[0].get('val')) if entities else 0.0)}** ({(_safe_float(entities[0].get('val')) / avg_ticket if avg_ticket > 0 else 1.0):.1f}x territory mean)\n"
            f"- **Above-Average Accounts:** **{sum(1 for e in entities if _safe_float(e.get('val')) >= avg_ticket)}** of {len(entities)} contributors"
        )

    # ── Pattern I: Long-Tail / Bottom Performers ─────────────────────────────
    if re.search(r"\b(long\s*tail|remaining|other|rest\s+of|tail|bottom|lowest|least|laggards)\b", q) and len(entities) >= 2:
        bottom_count = min(3, len(entities) - 1)
        bottom_entities = entities[-bottom_count:]
        b_lines = [
            f"Bottom Performing Contributor Diagnostic\n\n",
            f"Lowest performing contributors recorded for **{time_str}**:\n\n",
        ]
        for idx, e in enumerate(reversed(bottom_entities)):
            rank_num = len(entities) - idx
            b_lines.append(f"- **#{rank_num} — {e.get('name')}:** {_fmt_inr(e.get('val'))} ({_safe_float(e.get('share')):.1f}% share)\n")
        b_lines.append(f"\n Recommended Action: Evaluate credit lines and reorder cycles for these accounts.")
        return "".join(b_lines)

    # ── Pattern J: Portfolio Tier Filter ─────────────────────────────────────
    tier_match = re.search(r"\b(anchor|core|tail|dormant)\b", q)
    if tier_match and adv and adv.entity_tiers:
        target_tier = tier_match.group(1).upper()
        matching = [e for e in entities if adv.entity_tiers.get(e.get("name")) == target_tier]

        lines = [
            f"Portfolio Segmentation Filter: {target_tier} Tier\n\n",
            f"Displaying **{len(matching)} accounts** classified in the **{target_tier}** tier for **{time_str}**:\n\n",
        ]
        if matching:
            tier_val = sum(_safe_float(e.get("val")) for e in matching)
            lines.append(f"- **Tier Contribution:** {_fmt_inr(tier_val)} ({(tier_val/total_val*100.0 if total_val > 0 else 0):.1f}% of territory)\n\n")
            lines.append(" Classified Entities:\n")
            for e in matching[:8]:
                lines.append(f"- **{e.get('name')}:** {_fmt_inr(e.get('val'))} ({_safe_float(e.get('share')):.1f}% share)\n")
        else:
            lines.append(f"No accounts currently fall into the {target_tier} tier.\n")

        return "".join(lines)

    # ── Pattern K: Fuzzy Entity Deep-Dive ────────────────────────────────────
    matched_entity = mem.find_entity_fuzzy(q)
    if matched_entity and not any(k in q for k in ("compare", "versus", "vs", "what if")):
        nm = next((k for k, v in mem.entity_registry.items() if v == matched_entity), "Account")
        val = _safe_float(matched_entity.get("val"))
        share = _safe_float(matched_entity.get("share"))
        qty = _safe_float(matched_entity.get("qty"))
        cd = matched_entity.get("code", "")
        tier = adv.entity_tiers.get(nm, "") if adv else ""

        return (
            f"Operational Profile: {nm}\n\n"
            f"Records for **{nm}**{f' (Code: {cd})' if cd else ''} in **{time_str}**:\n\n"
            f" Key Performance Indicators:\n"
            f"- **Realized Revenue:** {_fmt_inr(val)} ({share:.1f}% territory share)\n"
            f"{f'- **Liquidated Volume:** {_fmt_num(qty)} units\n' if qty > 0 else ''}"
            f"{f'- **Portfolio Tier:** **{tier}**\n' if tier else ''}\n"
            f" Recommended Focus:\n"
            f"- Ensure steady replenishment cadence and sync billing terms with secondary liquidation pace."
        )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATIONAL & GREETING FAST-PATH ENGINE
# ─────────────────────────────────────────────────────────────────────────────

_BUSINESS_KEYWORDS = {
    "sale", "sales", "order", "orders", "sku", "skus", "secondary", "primary",
    "purchase", "purchases", "inward", "grn", "stock", "inventory", "clearance",
    "expiry", "claim", "claims", "scheme", "schemes", "distributor", "distributors",
    "dealer", "dealers", "vendor", "vendors", "supplier", "suppliers", "retailer",
    "retailers", "counter", "counters", "invoice", "invoices", "billing", "billings",
    "revenue", "balance", "voucher", "batch", "batches", "warehouse", "zone",
    "region", "top", "bottom", "trend", "breakdown", "report", "kpi", "growth",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "today", "yesterday", "tomorrow",
    "week", "month", "quarter", "year",
}


def handle_general_or_greeting(question: str, staff_context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Detects and responds to greetings, conversational chitchat, identity questions,
    and capability inquiries without executing BI flags or database queries.
    Returns formatted string if handled, or None if question should enter analytical pipeline.
    """
    if not question:
        return None

    raw_q = question.strip()
    clean_q = re.sub(r"[^\w\s]", " ", raw_q.lower())
    words = [w for w in clean_q.split() if w]
    if not words:
        return None

    # If any business keyword is present, let it pass to analytical engine
    if any(w in _BUSINESS_KEYWORDS for w in words):
        return None

    joined_q = " ".join(words)

    # Extract user name
    staff_name = ""
    if isinstance(staff_context, dict):
        raw_name = staff_context.get("name") or staff_context.get("fullName") or ""
        if raw_name and raw_name.lower() not in ("unknown", "there", "none"):
            staff_name = raw_name.split()[0].title()

    greeting_prefix = f"Hello {staff_name}! " if staff_name else "Hello! "

    # 1. Identity ("who are you", "who am i", "what is this")
    if re.search(r"\b(who\s+am\s+i|my\s+profile|my\s+identity)\b", joined_q):
        if staff_context:
            return (
                f"Logged-in DMS Profile\n\n"
                f"- User Name: {staff_context.get('name', 'Authenticated User')}\n"
                f"- Designation: {staff_context.get('designation', 'Commercial Staff')}\n"
                f"- Territory Scope: Assigned Distribution Hierarchy\n\n"
                f"All sales analytics, warehouse stock, and purchase inward are scoped to your assigned permissions."
            )
        return (
            " DMS Staff Profile\n\n"
            "You are authenticated in the Distributor Management System (DMS) portal. "
            "Your access is automatically scoped to your assigned territory and distributor hierarchy."
        )

    if re.search(r"\b(who\s+are\s+(you|u)|what\s+are\s+(you|u)|what\s+is\s+your\s+name|introduce\s+yourself|tell\s+me\s+about\s+yourself)\b", joined_q):
        return (
            f" DMS Commercial Intelligence Assistant\n\n"
            f"{greeting_prefix}I am the Executive DMS Intelligence Assistant, engineered to deliver instant "
            f"commercial analytics, stock flow balances, and distributor intelligence across your territory hierarchy.\n\n"
            f" Core Analytical Capabilities:\n"
            f"- Secondary Sales: Distributor-to-dealer liquidation, ticket sizes, and volume throughput.\n"
            f"- Purchases & Inward: Manufacturer-to-distributor dispatches, inward velocity, and vendor replenishment.\n"
            f"- Primary Sales: Company billing throughput, order fulfillment rates, and parity tracking.\n"
            f"- Stock Movement & Health: Warehouse opening/closing balances, inward vs outward flow, and safety buffers.\n"
            f"- Stock Clearance: Aging inventory risk evaluation, near-expiry batch audit, and clearance slabs.\n"
            f"- Claims Management: Rate difference and damage claim settlement cycles and approval tracking.\n"
            f"- Trade Schemes: Trade promotion discount utilization, dealer adoption, and scheme ROI.\n\n"
            f"Ask any question directly, such as: \"Show secondary sales this month\" or \"Top 5 distributors\"."
        )

    # 2. Well-being / Conversational ("how are you", "how are u", "how's it going", "what's up")
    if re.search(r"\b(how\s+(are|r)\s+(you|u)|how\s+are\s+you\s+doing|how\s+is\s+it\s+going|hows\s+it\s+going|whats\s+up|wassup|sup|kaisa\s+hai|kaise\s+ho)\b", joined_q):
        return (
            f"Operational Status: Optimal\n\n"
            f"{greeting_prefix}I am functioning at peak analytical capacity and ready to crunch your distributor and warehouse data! \n\n"
            f"How can I assist your commercial operations today? Feel free to ask about:\n"
            f"- Secondary billings & dealer liquidation\n"
            f"- Purchase inward & supplier replenishment\n"
            f"- Warehouse closing stock & inventory balances\n"
            f"- Outstanding trade claims & settlement status"
        )

    # 3. Help / Capabilities ("help", "what can you do", "guide", "features")
    if re.search(r"\b(help|what\s+can\s+(you|u)\s+do|what\s+can\s+i\s+ask|how\s+can\s+you\s+help|guide|features|options|commands|sample\s+questions)\b", joined_q) or joined_q in ("help", "guide", "menu"):
        return (
            f"DMS Intelligence Guide & Capabilities\n\n"
            f"{greeting_prefix}Here is a quick reference of questions and analyses you can run across your DMS network:\n\n"
            f"- Secondary Sales: \"Show secondary sales for this month\", \"Top 5 distributors by offtake\"\n"
            f"- Purchases: \"Show primary purchases for last 30 days\", \"Top inward vendors\"\n"
            f"- Primary Sales: \"Primary sales order billing trend\", \"Distributor order dispatches\"\n"
            f"- Stock Movement: \"Closing stock position by warehouse\", \"Inventory flow this month\"\n"
            f"- Stock Clearance: \"Near-expiry stock batches\", \"Aging inventory clearance summary\"\n"
            f"- Claims: \"Pending trade claims amount\", \"Approved vs rejected claims by type\"\n"
            f"- Schemes: \"Active trade schemes performance\", \"Dealer scheme uptake\"\n\n"
            f" Interactive Tip: You can also ask follow-up questions to drill into previous reports (e.g. \"Compare #1 and #2\" or \"What if top distributor grew 20%?\")."
        )

    # 4. Appreciation / Acknowledgement ("thank you", "thanks", "great", "awesome", "ok")
    if re.search(r"\b(thank\s+(you|u)|thanks|thx|ty|great|awesome|perfect|good\s*job|well\s*done|nice|cool|superb|brilliant)\b", joined_q) and len(words) <= 4:
        return (
            f"Glad to Assist!\n\n"
            f"You're very welcome! Let me know whenever you need further deep-dives, distributor comparisons, or stock reports. Have a successful and high-performing commercial day! "
        )

    if joined_q in ("ok", "okay", "got it", "noted", "understood", "alright", "all right"):
        return (
            f"Noted\n\n"
            f"Standing by. Whenever you're ready, feel free to ask for your next DMS briefing or inventory report."
        )

    # 5. Farewell ("bye", "goodbye", "see you")
    if re.search(r"\b(bye|goodbye|see\s+(you|ya)|cya|talk\s+to\s+you\s+later|good\s*night|exit|quit)\b", joined_q) and len(words) <= 4:
        return (
            f"Goodbye & Have a Productive Day!\n\n"
            f"Signing off. Reach back out anytime you need real-time distributor intelligence, stock reports, or claim updates. Good luck with your commercial targets! "
        )

    # 6. General Greetings ("hi", "hello", "hey", "namaste", "good morning", etc.)
    greeting_tokens = {
        "hi", "hello", "hey", "hiya", "hola", "howdy", "namaste", "namaskar",
        "greetings", "morning", "afternoon", "evening", "yo", "sup"
    }
    if any(w in greeting_tokens for w in words) and len(words) <= 5:
        return (
            f"DMS Commercial Intelligence: Welcome\n\n"
            f"{greeting_prefix}I am your DMS Commercial Intelligence Assistant. "
            f"I provide real-time distributor tracking, purchase replenishment insights, stock movement analytics, and trade claim diagnostics.\n\n"
            f"Recommended Inquiries to Get Started:\n"
            f"- Secondary Sales: \"Show secondary sales for this month and top 5 distributors\"\n"
            f"- Purchases & Inward: \"Total purchase inward value for the last 30 days\"\n"
            f"- Stock Position: \"Closing stock balance across warehouses\"\n"
            f"- Trade Claims: \"Pending claim amount and settlement status\"\n"
            f"- Performance: \"Top performing distributors by sales throughput\"\n\n"
            f"What data would you like to review today?"
        )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRYPOINT: 8-LAYER PIPELINE DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def generate_executive_report(
    question: str,
    merged_exec: Dict[str, Any],
    staff_context: Optional[Dict[str, Any]] = None,
    first_flag: Optional[str] = None,
    descriptions: Optional[List[Tuple[str, str]]] = None,
    output_lang: str = "auto",
    executed_data: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    staff_uid: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Produce an articulate, consultative, executive-ready commercial briefing in sub-100ms.
    100% deterministic (0 LLM tokens). Zero data exfiltration.
    Uses the 8-Layer Computational BI Synthesis Pipeline.
    """
    # Fast-path: Greetings & Conversational Chitchat (<1ms)
    greeting_answer = handle_general_or_greeting(question, staff_context=staff_context)
    if greeting_answer:
        return _clean_markdown_formatting(greeting_answer)

    # Fast-path: In-Memory Cross-Questioning (<5ms)
    if staff_uid and conversation_id:
        cq_answer = resolve_cross_questioning(staff_uid, conversation_id, question)
        if cq_answer:
            return _clean_markdown_formatting(cq_answer)

    # Layer 2: Classify & Fuse all datasets (single-source, verified metrics)
    flag = first_flag or (descriptions[0][0] if descriptions else "")
    datasets_to_fuse = executed_data if executed_data else [merged_exec]
    rows, cols, summary_kpis, metric_valid = _classify_and_fuse_datasets(datasets_to_fuse, _module_of(flag))

    # Fallback to merged_exec rows if classification yielded nothing
    if not rows and merged_exec:
        rows = [r for r in (merged_exec.get("rows") or []) if isinstance(r, dict)]
        cols = [c for c in (merged_exec.get("columns") or []) if c and not c.startswith("_")]

    # Zero-data response
    if not rows:
        flag = first_flag or (descriptions[0][0] if descriptions else "analytics")
        flag_desc = descriptions[0][1] if descriptions else "Commercial Analytics"
        clean_q = _clean_question_title(question, flag_desc)
        time_str = _extract_time_context(question, [], None)
        return _clean_markdown_formatting(
            f"Field Intelligence Briefing: {clean_q}\n\n"
            f"I reviewed the records for **{flag_desc}** covering **{time_str}**, "
            f"but found no matching transactions within your assigned territory hierarchy.\n\n"
            f" Recommended Next Inquiries\n\n"
            f"- Try widening the date window (e.g. \"Show secondary sales for the last 90 days\")\n"
            f"- Verify active distributor coverage and assigned accounts\n"
            f"- Inspect warehouse stock balances and purchase order dispatches"
        )

    # Detect module type
    cols_map = {c.lower(): c for c in cols}
    time_col = _find_col(TIME_COL_CANDIDATES, cols_map)
    time_str = _extract_time_context(question, rows, time_col)
    mod_type = _detect_module_type(flag, question, cols)

    # Layer 3 & 3.5: Compute analytics
    analytics = _compute_analytics(rows, cols, summary_kpis, mod_type, time_str, metric_valid)

    # Layer 5: Push turn to conversation memory
    if staff_uid and conversation_id:
        _push_turn_to_memory(staff_uid, conversation_id, analytics, question)

    # Layer 4: Assemble briefing
    config = _MODULE_CONFIGS.get(mod_type, _MODULE_CONFIGS["generic"])
    raw_briefing = _assemble_briefing(analytics, config, question)
    return _clean_markdown_formatting(raw_briefing)


# ─────────────────────────────────────────────────────────────────────────────
# BRANDED REPORT CARD (structured briefing payload) + CONCISE BI NARRATIVE
# ─────────────────────────────────────────────────────────────────────────────

_MODULE_ICONS = {
    "secondary_sales": "��", "purchases": "��", "primary_sales": "��",
    "stock_movement": "��", "stock_clearance": "⏳", "claims": "��",
    "schemes": "��", "masters": "��️", "generic": "��",
}

_MODULE_VALUE_LABELS = {
    "secondary_sales": "Total Secondary Sales",
    "purchases": "Total Purchase Value",
    "primary_sales": "Total Primary Sales",
    "stock_movement": "Inventory Position Value",
    "stock_clearance": "Clearance Value",
    "claims": "Claim Settlement Value",
    "schemes": "Scheme Discount / Uplift",
    "masters": "Commercial Volume",
    "generic": "Total Value",
}


def _date_range_from_rows(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Scan rows for a date-ish column and return (min, max) ISO dates."""
    if not rows:
        return "", ""
    candidates = []
    for col in list(rows[0].keys()):
        vals = []
        for r in rows[:60]:
            s = _clean_str(r.get(col))
            if re.match(r"^\d{4}-\d{2}-\d{2}", s):
                vals.append(s[:10])
        if len(vals) >= 2:
            candidates.append((min(vals), max(vals)))
    if candidates:
        return min(c[0] for c in candidates), max(c[1] for c in candidates)
    return "", ""


# ─────────────────────────────────────────────────────────────────────────────
# TIME-SERIES DETECTION & TREND REPORTING
# ─────────────────────────────────────────────────────────────────────────────
# Monthly / daily breakdowns are NOT an entity breakdown: ranking them as
# "distributors" produces nonsense (General Entity 100%, fake concentration).
# When the primary rows are a time series we report a TREND instead.

def _find_time_col(rows: List[Dict[str, Any]], cols: List[str]) -> Optional[str]:
    cols_map = {c.lower(): c for c in cols}
    time_col = _find_col(TIME_COL_CANDIDATES, cols_map)
    if time_col:
        return time_col
    for c in cols:
        s = _clean_str((rows[0] or {}).get(c)) if rows else ""
        if re.match(r"^\d{4}[-/]\d{2}", s):
            return c
    return None


def _is_time_series(rows: List[Dict[str, Any]], cols: List[str]) -> bool:
    """True when rows are a period breakdown with no real categorical entity."""
    if len(rows) < 3:
        return False
    if not _find_time_col(rows, cols):
        return False
    cols_map = {c.lower(): c for c in cols}
    name_col = _find_col(ENTITY_NAME_CANDIDATES, cols_map)
    if name_col:
        distinct = {_clean_str(r.get(name_col)) for r in rows[:50] if r.get(name_col)}
        if len(distinct) > 1:
            return False
    return True


def _time_series_points(rows: List[Dict[str, Any]], cols: List[str]) -> List[Tuple[str, float, float]]:
    """(period_label, value, qty) sorted chronologically."""
    time_col = _find_time_col(rows, cols)
    if not time_col:
        return []
    cols_map = {c.lower(): c for c in cols}
    val_col = _find_col(VAL_COL_CANDIDATES, cols_map)
    qty_col = _find_col(QTY_COL_CANDIDATES, cols_map)
    pts: List[Tuple[str, float, float]] = []
    for r in rows:
        label = _clean_str(r.get(time_col))
        if not label:
            continue
        pts.append((
            label,
            _safe_float(r.get(val_col)) if val_col else 0.0,
            _safe_float(r.get(qty_col)) if qty_col else 0.0,
        ))
    pts.sort(key=lambda p: p[0])
    return pts


def _build_read_trend(analytics: ComputedAnalytics, config: ModuleConfig,
                      pts: List[Tuple[str, float, float]]) -> str:
    labels = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    total = sum(vals)
    n = len(pts)
    peak_i = max(range(n), key=lambda i: vals[i])
    low_i = min(range(n), key=lambda i: vals[i])
    first, last = vals[0], vals[-1]
    chg = ((last - first) / abs(first) * 100.0) if first else 0.0
    qty_total = sum(p[2] for p in pts)

    parts: List[str] = []
    opening = (
        f"Your **{config.domain_label.lower()}** for **{labels[0]} to {labels[-1]}** totals "
        f"**{_fmt_inr(total)}**"
    )
    if qty_total > 0:
        opening += f" across **{_fmt_num(qty_total)} units**"
    opening += f" over **{n} periods**."
    parts.append(opening)

    if total > 0:
        parts.append(
            f"**{labels[peak_i]}** was the strongest period at **{_fmt_inr(vals[peak_i])}** "
            f"({vals[peak_i] / total * 100:.1f}% of the total), while **{labels[low_i]}** was the softest "
            f"at **{_fmt_inr(vals[low_i])}**."
        )

    direction = "up" if chg > 0.5 else ("down" if chg < -0.5 else "broadly flat")
    parts.append(
        f"First period vs last period the trend is **{direction} {abs(chg):.1f}%** "
        f"({_fmt_inr(first)} → {_fmt_inr(last)})."
    )
    if total > 0:
        parts.append(f"Average per period is **{_fmt_inr(total / n)}**.")
    return "\n\n".join(parts)


def _build_phase1_trend_briefing(analytics: ComputedAnalytics, config: ModuleConfig, question: str,
                                 pts: List[Tuple[str, float, float]]) -> Dict[str, Any]:
    """Branded card payload for a period breakdown (trend, not leaderboard)."""
    labels = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    qtys = [p[2] for p in pts]
    total = sum(vals)
    n = len(pts)
    peak_i = max(range(n), key=lambda i: vals[i])
    low_i = min(range(n), key=lambda i: vals[i])
    first, last = vals[0], vals[-1]
    chg = ((last - first) / abs(first) * 100.0) if first else 0.0
    qty_total = sum(qtys)

    tiles: List[Dict[str, str]] = [{"icon": "orders", "value": f"{n}", "label": "Periods"}]
    if qty_total > 0:
        tiles.append({"icon": "units", "value": _fmt_num(qty_total), "label": "Units"})
    tiles.append({"icon": "value", "value": labels[peak_i], "label": "Peak period"})

    ranked = sorted(pts, key=lambda p: p[1], reverse=True)
    leaders: List[Dict[str, Any]] = []
    for i, (label, v, q) in enumerate(ranked[:8]):
        leaders.append({
            "rank": i + 1,
            "name": label,
            "value": _fmt_inr(v),
            "share": round((v / total * 100.0) if total > 0 else 0.0, 1),
            "units": _fmt_num(q),
        })

    direction = "up" if chg > 0.5 else ("down" if chg < -0.5 else "flat")
    standouts = [
        {"icon": "trend", "title": f"Peak: {labels[peak_i]}",
         "text": f"{_fmt_inr(vals[peak_i])} in this period — the highest of the range."},
        {"icon": "pulse", "title": f"Trend: {direction}",
         "text": f"First vs last period moved {chg:+.1f}% ({_fmt_inr(first)} → {_fmt_inr(last)})."},
    ]
    actions = [
        {"icon": "shield", "title": f"Repeat the {labels[peak_i]} playbook",
         "body": f"Study what drove {_fmt_inr(vals[peak_i])} in {labels[peak_i]} and apply it to weaker periods."},
        {"icon": "spread", "title": f"Lift {labels[low_i]}",
         "body": f"{labels[low_i]} was the softest at {_fmt_inr(vals[low_i])}; a targeted push here narrows the gap."},
    ]
    explore = [
        f"Why did {labels[low_i]} dip?",
        f"What if {labels[peak_i]} grew 20%?",
        "Compare with the same period last year",
        "Show the month-over-month change",
    ]

    date_from, date_to = labels[0], labels[-1]
    return {
        "title": _clean_question_title(question, config.domain_label),
        "intro": f"{config.domain_label} trend over time",
        "icon": _MODULE_ICONS.get(analytics.module, "��"),
        "value": _fmt_inr(total) if total > 0 else "",
        "value_label": _MODULE_VALUE_LABELS.get(analytics.module, f"Total {config.value_label}"),
        "date_from": date_from,
        "date_to": date_to,
        "tiles": tiles[:4],
        "biggest": {"label": "Peak period", "name": labels[peak_i], "share": round((vals[peak_i] / total * 100.0) if total > 0 else 0.0, 1)},
        "leaders": leaders,
        "tiers": [],
        "standouts": standouts[:3],
        "actions": actions[:3],
        "explore": explore,
        "avg_bits": [f"Avg. per period: {_fmt_inr(total / n)}"] if total > 0 else [],
        "footnote": f"Trend computed from your own territory data for {labels[0]} to {labels[-1]}.",
    }


_CURRENT_PREV_PAIRS = [
    # (side-A column, side-B column) — period-comparison datasets in DMS flags
    ("current_total", "previous_total"),
    ("current_month_sales", "last_month_sales"),
    ("this_month_total", "last_month_total"),
    ("current_value", "previous_value"),
    ("this_period", "last_period"),
]


def _label_from_col(col: str) -> str:
    """Factual side label derived from the data column itself."""
    c = (col or "").lower()
    if "current" in c or "this" in c:
        return "Current period"
    if "prev" in c or "last" in c:
        return "Previous period"
    return (col or "").replace("_", " ").title()[:40]


def _build_dms_comparison_card(
    question: str,
    descriptions: Optional[List[Tuple[str, str]]],
    executed_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Purpose-built compact diff card for comparison answers (à-la-carte, SFA-style).
    Two supported data shapes — both read ONLY real executed values:
      A) Period comparison (compare-periods / growth flags): ONE row with paired
         current/previous columns → tiles [A, B, delta].
      B) Entity comparison (distributor-compare): TWO rows with a name + value
         column → tiles per entity + delta.
    Returns {} when neither shape fits — caller falls back to the reduced card.
    """
    usable = [ds for ds in (executed_data or [])
              if isinstance(ds, dict) and not ds.get("error")]
    if not usable:
        return {}
    ds = usable[0]
    rows = ds.get("rows_full") or ds.get("rows") or []
    cols = ds.get("columns") or []
    if not rows:
        return {}

    # ── Case A: paired current/previous columns in a single row ─────────────
    if len(rows) == 1:
        row = rows[0]
        a_col = b_col = None
        # explicit known pairs first
        for ca, cb in _CURRENT_PREV_PAIRS:
            if ca in cols and cb in cols:
                a_col, b_col = ca, cb
                break
        if a_col is None:
            # generic detection: base col + prev/last variant of the same base
            lowered = {c.lower(): c for c in cols}
            for c in cols:
                cl = c.lower()
                for tag in ("prev", "previous", "last"):
                    if tag in cl:
                        base = cl.replace(tag, "").replace("previous", "").replace("_", "_")
                        cand = None
                        for c2 in cols:
                            c2l = c2.lower()
                            if c2l != cl and (c2l in base or base.replace("_", "") == c2l.replace("_", "")):
                                cand = c2
                                break
                        if cand:
                            a_col, b_col = cand, c
                            break
                if a_col:
                    break
        if a_col and b_col is not None:
            va = _safe_float(row.get(a_col))
            vb = _safe_float(row.get(b_col))
            label_a = _label_from_col(a_col)
            label_b = _label_from_col(b_col)
            # Prefer the flag's OWN stored change metric (its denominator is
            # authoritative); fall back to computing the raw delta.
            stored = None
            for cand in ("change_pct", "growth_pct"):
                if cand in cols and row.get(cand) is not None:
                    stored = _safe_float(row.get(cand))
                    break
            diff = vb - va
            if stored is not None:
                delta_str = f"{stored:+.1f}%"
                delta_label = "Change"
                pct_abs = abs(stored)
            else:
                pct = (diff / va * 100.0) if va else 0.0
                sign = "+" if diff > 0 else ("-" if diff < 0 else "")
                delta_str = f"{sign}{_fmt_inr(abs(diff))}"
                delta_label = f"{pct:+.1f}% change"
                pct_abs = abs(pct)
            sign = "+" if diff > 0 else ("-" if diff < 0 else "")
            return {
                "kind": "diff",
                "title": _clean_question_title(question, "Comparison"),
                "intro": "Side-by-side comparison",
                "icon": "��",
                "value": "",
                "value_label": "",
                "date_from": "",
                "date_to": "",
                "tiles": [
                    {"icon": "units", "value": _fmt_inr(va), "label": label_a},
                    {"icon": "orders", "value": _fmt_inr(vb), "label": label_b},
                    {"icon": "skus", "value": delta_str, "label": delta_label},
                ],
                "biggest": {"label": "Higher", "name": (label_b if diff > 0 else (label_a if diff < 0 else "Equal")),
                            "share": pct_abs},
                "leaders": [],
                "tiers": [],
                "standouts": [],
                "actions": [],
                "explore": [
                    "Show both sides distributor-wise",
                    "Show both sides item-wise",
                    "Show the month-wise trend across both sides",
                    "Which items drove the biggest change?",
                    "Compare the quantities instead of values",
                ],
                "avg_bits": [],
                "footnote": "Both values are computed from your own territory data.",
            }

    # ── Case B: two-entity comparison (e.g. distributor-compare) ────────────
    name_col = next((c for c in ("ds_name", "dealer_name", "item_name", "itemdescription", "ledgername")
                     if c in cols), None)
    val_col = next((c for c in ("total", "total_billed_value", "total_primary_sales", "total_sales")
                    if c in cols), None)
    if name_col and val_col and len(rows) == 2:
        r1, r2 = rows[0], rows[1]
        n1, n2 = str(r1.get(name_col) or "Side A"), str(r2.get(name_col) or "Side B")
        v1, v2 = _safe_float(r1.get(val_col)), _safe_float(r2.get(val_col))
        diff = v2 - v1
        pct = (diff / v1 * 100.0) if v1 else 0.0
        sign = "+" if diff > 0 else ("-" if diff < 0 else "")
        return {
            "kind": "diff",
            "title": _clean_question_title(question, "Comparison"),
            "intro": "Head-to-head comparison",
            "icon": "⚖️",
            "value": "",
            "value_label": "",
            "date_from": "",
            "date_to": "",
            "tiles": [
                {"icon": "units", "value": _fmt_inr(v1), "label": n1[:40]},
                {"icon": "orders", "value": _fmt_inr(v2), "label": n2[:40]},
                {"icon": "skus", "value": f"{sign}{_fmt_inr(abs(diff))}", "label": f"{pct:+.1f}% change"},
            ],
            "biggest": {"label": "Higher", "name": (n2 if diff > 0 else (n1 if diff < 0 else "Equal")),
                        "share": round(abs(pct), 1)},
            "leaders": [],
            "tiers": [],
            "standouts": [],
            "actions": [],
            "explore": [
                "Show both sides item-wise",
                "Show both sides dealer-wise",
                "Which items drove the difference?",
                "Compare them month-wise",
                "Compare the quantities instead of values",
            ],
            "avg_bits": [],
            "footnote": "Values computed from your own territory data.",
        }

    return {}


def build_phase1_briefing(
    question: str,
    descriptions: Optional[List[Tuple[str, str]]],
    executed_data: List[Dict[str, Any]],
    first_flag: Optional[str] = None,
    shape: str = "analytical",
) -> Dict[str, Any]:
    """
    Structured branded report-card payload (tiles, leaders, tiers, standouts,
    actions, explore). Deterministic, zero LLM tokens. Used by BOTH the ON path
    (built in Phase 2) and the OFF path (built inline).

    `shape` (response-shape engine) selects the card variant, SFA-style à-la-carte:
      - comparison → purpose-built diff card (side-by-side tiles + delta + winner)
      - ranking    → tiles + leaders + explore (no tiers/standouts/actions)
      - trend      → time-series card (auto-detected) or compact tiles + explore
      - lookup     → single headline tile + explore
      - general    → {} (no data involved)
    Failed builds fall back to the reduced full card (safe default).
    """
    shape = (shape or "analytical").strip().lower() or "analytical"
    if shape == "general":
        return {}
    if shape == "comparison":
        # À-la-carte: comparisons get their own purpose-built diff card
        # (side-by-side tiles + delta), NOT a trimmed full card. If the data
        # doesn't fit a diff shape, fall through to the reduced full card.
        try:
            diff_card = _build_dms_comparison_card(question, descriptions, executed_data)
            if diff_card:
                return diff_card
        except Exception as _de:
            print(f"[briefing] comparison card failed: {_de}")
    try:
        flag = first_flag or ((descriptions or [])[0][0] if descriptions else "")
        rows, cols, kpis, metric_valid = _classify_and_fuse_datasets(executed_data, _module_of(flag))
        if not rows:
            return {}
        mod_type = _detect_module_type(flag, question, cols)
        time_col = _find_col(TIME_COL_CANDIDATES, {c.lower(): c for c in cols})
        time_str = _extract_time_context(question, rows, time_col)
        analytics = _compute_analytics(rows, cols, kpis, mod_type, time_str, metric_valid)
        config = _MODULE_CONFIGS.get(mod_type, _MODULE_CONFIGS["generic"])
    except Exception as _e:
        print(f"[briefing] build failed: {_e}")
        return {}

    # Period breakdowns (monthly/daily) get a TREND report, never an entity leaderboard.
    if _is_time_series(rows, cols):
        _pts = _time_series_points(rows, cols)
        if _pts:
            return _build_phase1_trend_briefing(analytics, config, question, _pts)

    icon = _MODULE_ICONS.get(mod_type, "��")
    value_label = _MODULE_VALUE_LABELS.get(mod_type, f"Total {config.value_label}")

    # Tiles
    tiles: List[Dict[str, str]] = []
    if analytics.total_qty > 0:
        tiles.append({"icon": "units", "value": _fmt_num(analytics.total_qty), "label": "Units"})
    if analytics.module in ("secondary_sales", "purchases", "primary_sales") and analytics.invoice_count > 0:
        tiles.append({"icon": "orders", "value": f"{analytics.invoice_count:,}", "label": "Transactions"})
    elif analytics.invoice_count > 1:
        tiles.append({"icon": "orders", "value": f"{analytics.invoice_count:,}", "label": "Transactions"})
    if analytics.entity_count > 1:
        tiles.append({"icon": "skus", "value": f"{analytics.entity_count:,}", "label": f"Active {config.entity_noun_plural}"})
    if analytics.unique_outlets > 0:
        tiles.append({"icon": "outlets", "value": f"{analytics.unique_outlets:,}", "label": "Accounts"})

    # Leaders
    ents = analytics.ranked_entities
    leaders: List[Dict[str, Any]] = []
    if ents and analytics.total_val > 0:
        for e in ents[:5]:
            leaders.append({
                "rank": e.get("rank") if e.get("rank") else (len(leaders) + 1),
                "name": e.get("name") or f"{config.entity_noun} {len(leaders) + 1}",
                "value": _fmt_inr(_safe_float(e.get("val"))),
                "share": round(_safe_float(e.get("share")), 1),
                "units": _fmt_num(_safe_float(e.get("qty"))),
            })
        remaining = ents[5:]
        if remaining:
            rem_val = sum(_safe_float(e.get("val")) for e in remaining)
            leaders.append({
                "rest": True,
                "name": f"Next {len(remaining)} {config.entity_noun_plural.lower()}",
                "value": _fmt_inr(rem_val),
                "share": round(rem_val / analytics.total_val * 100, 1),
                "units": _fmt_num(sum(_safe_float(e.get("qty")) for e in remaining)),
            })

    # Portfolio tiers
    tiers: List[Dict[str, Any]] = []
    if len(ents) >= 5:
        tier_names = {"ANCHOR": "must-protect", "CORE": "steady earners", "TAIL": "small but active", "DORMANT": "barely moving"}
        tier_bands = {"ANCHOR": "≥25% of value", "CORE": "5 to 25%", "TAIL": "1 to 5%", "DORMANT": "<1%"}
        grouped: Dict[str, List[str]] = {"ANCHOR": [], "CORE": [], "TAIL": [], "DORMANT": []}
        for e in ents:
            grouped[analytics.advanced.entity_tiers.get(e.get("name", ""), "DORMANT")].append(e.get("name", ""))
        for tier in ("ANCHOR", "CORE", "TAIL", "DORMANT"):
            names = grouped[tier]
            if names:
                sample = ", ".join(names[:2])
                suffix = f" and {len(names) - 2} more" if len(names) > 2 else ""
                tiers.append({
                    "tier": tier, "band": tier_bands[tier], "meaning": tier_names[tier],
                    "count": len(names), "label": f"{sample}{suffix}",
                })

    # Standouts
    standouts: List[Dict[str, str]] = []
    top1_name = (ents[0].get("name") if ents else "") or ""
    top1_share = _safe_float(ents[0].get("share")) if ents else 0.0
    adv = analytics.advanced
    if analytics.concentration_risk == "HIGH":
        standouts.append({"icon": "pulse", "title": "High concentration",
                          "text": f"Top 3 {config.entity_noun_plural.lower()} give {analytics.top_3_share:.1f}% of the total; {top1_name} alone sits at {top1_share:.1f}%."})
    elif analytics.concentration_risk == "MODERATE":
        standouts.append({"icon": "pulse", "title": "Moderate concentration",
                          "text": f"Top 3 {config.entity_noun_plural.lower()} contribute {analytics.top_3_share:.1f}%. Watch the top few for stockout or churn."})
    else:
        standouts.append({"icon": "pulse", "title": "Well spread",
                          "text": f"No single {config.entity_noun.lower()} dominates; top 3 only make {analytics.top_3_share:.1f}%."})
    if adv.outlier_entities:
        oe = adv.outlier_entities[0]
        oz = _safe_float(oe.get("z_score", 0.0))
        if oz > 0:
            standouts.append({"icon": "trend", "title": f"Outperformer: {oe.get('name', 'Unknown')}",
                              "text": f"{oz:+.1f}σ vs peers at {_fmt_inr(_safe_float(oe.get('val')))}. Worth protecting and studying."})
        else:
            standouts.append({"icon": "trend", "title": f"Underperformer: {oe.get('name', 'Unknown')}",
                              "text": f"{oz:+.1f}σ vs peers at {_fmt_inr(_safe_float(oe.get('val')))}. Check pricing, stock or demand."})

    # Actions
    actions: List[Dict[str, str]] = []
    if top1_name and top1_share > 0:
        buffer_days = max(7, round(top1_share / 5))
        actions.append({"icon": "shield", "title": f"Protect {top1_name}",
                        "body": f"It drives {top1_share:.1f}% of the total — keep {buffer_days}-day cover on every cycle."})
    if len(ents) > 1:
        top2_name = ents[1].get("name", "")
        top2_val = _safe_float(ents[1].get("val"))
        if top2_name and top2_val > 0:
            actions.append({"icon": "link", "title": "Bundle and lift",
                            "body": f"Pair {top1_name} with {top2_name}; target {_fmt_inr(top2_val)} to {_fmt_inr(top2_val * 1.25)} (+25%)."})
    if adv.gini_coefficient > 0.6:
        tail_count = sum(1 for e in ents if adv.entity_tiers.get(e.get("name", ""), "DORMANT") in ("TAIL", "DORMANT"))
        if tail_count:
            actions.append({"icon": "spread", "title": "Spread the risk",
                            "body": f"The mix is uneven (Gini {adv.gini_coefficient:.2f}). Activate {tail_count} low-share accounts with a targeted push."})

    explore = [
        "Compare #1 and #2",
        f"How did {ents[1].get('name', 'the runner-up') if len(ents) > 1 else 'it'} perform?",
        f"What if {ents[0].get('name', 'the top account')} grew 20%?" if ents else "Run a growth scenario",
        "Show me the CORE tier only",
        "Why is concentration high?",
    ]

    avg_bits: List[str] = []
    if analytics.entity_count > 1 and analytics.avg_ticket > 0:
        avg_bits.append(f"Avg. per {config.entity_noun.lower()}: {_fmt_inr(analytics.avg_ticket)}")
    if analytics.total_qty > 0 and analytics.avg_realization > 0:
        avg_bits.append(f"Avg. per unit: {_fmt_inr(analytics.avg_realization)}")

    date_from, date_to = _date_range_from_rows(rows)
    biggest_label = f"Biggest {config.entity_noun.lower()}"

    payload = {
        "title": _clean_question_title(question, config.domain_label),
        "intro": f"{config.domain_label} overview",
        "icon": icon,
        "value": _fmt_inr(analytics.total_val) if analytics.total_val > 0 else "",
        "value_label": value_label,
        "date_from": date_from,
        "date_to": date_to,
        "tiles": tiles[:4],
        "biggest": {"label": biggest_label, "name": (top1_name if analytics.total_val > 0 else ""),
                    "share": round(top1_share, 1)},
        "leaders": leaders[:6],
        "tiers": tiers,
        "standouts": standouts[:3],
        "actions": actions[:3],
        "explore": explore,
        "avg_bits": avg_bits,
        "footnote": f"All values are computed from your own territory data for {analytics.time_str}.",
    }

    if shape in ("ranking", "trend", "lookup", "comparison"):
        # Narrow shapes: keep headline tiles + explore chips, drop deep-dive blocks.
        # Ranking keeps its leaders; comparison keeps leaders too (the narrative
        # carries the side-by-side markdown table); trend/lookup drop them.
        if shape in ("trend", "lookup"):
            payload["leaders"] = []
        payload["tiles"] = (payload.get("tiles") or [])[:1] if shape == "lookup" else (payload.get("tiles") or [])[:2]
        if not payload["tiles"] and analytics.total_val > 0:
            # Aggregate-only datasets have no natural tiles — synthesise one
            # headline tile from the computed total so the card still renders.
            payload["tiles"] = [{"icon": "units", "value": _fmt_inr(analytics.total_val), "label": "Total"}]
        payload["tiers"] = []
        payload["standouts"] = []
        payload["actions"] = []

    return payload


def _build_read(analytics: ComputedAnalytics, config: ModuleConfig) -> str:
    """
    Concise, plain-language synthesis for the report card's analysis panel.
    The card already shows KPIs/leaders/mix/standouts/actions, so this only adds
    interpretation (the "so what") and never repeats those sections.
    """
    ents = analytics.ranked_entities
    top1 = ents[0] if ents else {}
    top1_name = top1.get("name", "")
    top1_share = _safe_float(top1.get("share"))
    adv = analytics.advanced
    total_val = analytics.total_val
    noun = config.entity_noun.lower()
    noun_plural = config.entity_noun_plural.lower()

    parts: List[str] = []
    if total_val > 0:
        opening = f"Your **{config.domain_label.lower()}** for **{analytics.time_str}** comes to **{_fmt_inr(total_val)}**"
        if analytics.total_qty > 0:
            opening += f" across **{_fmt_num(analytics.total_qty)} units**"
        if analytics.entity_count > 1:
            opening += f" from **{analytics.entity_count} {noun_plural}**"
        opening += "."
    else:
        opening = f"Here is the picture for your **{config.domain_label.lower()}** in **{analytics.time_str}**."
    parts.append(opening)

    if top1_name and top1_share > 0:
        if analytics.concentration_risk == "HIGH":
            parts.append(
                f"**{top1_name}** leads with **{top1_share:.1f}%**, and the top 3 together make "
                f"**{analytics.top_3_share:.1f}%** of the total — a concentrated picture, so a stockout or "
                f"churn on the leaders would be felt immediately."
            )
        elif analytics.concentration_risk == "MODERATE":
            parts.append(
                f"**{top1_name}** leads with **{top1_share:.1f}%**, while the top 3 contribute "
                f"**{analytics.top_3_share:.1f}%**, a reasonably balanced spread."
            )
        else:
            parts.append(
                f"**{top1_name}** leads with **{top1_share:.1f}%**, but no single {noun} dominates "
                f"(top 3 = **{analytics.top_3_share:.1f}%**), so activity is well spread."
            )

    if adv.outlier_entities:
        oe = adv.outlier_entities[0]
        nm = oe.get("name", "") or "One entry"
        z = _safe_float(oe.get("z_score", 0.0))
        if z > 0:
            parts.append(f"**{nm}** is running well ahead of its peers — the clearest story to lean into.")
        else:
            parts.append(f"**{nm}** is trailing its peers — the first place to check pricing, stock and demand.")

    if adv.gini_coefficient > 0.6 and len(ents) > 5:
        parts.append("The mix is uneven, so widening the active base would reduce risk.")
    elif analytics.avg_ticket > 0:
        parts.append(f"Average value per {noun} is **{_fmt_inr(analytics.avg_ticket)}**.")

    return "\n\n".join(parts)


def generate_bi_analysis(
    question: str,
    merged_exec: Dict[str, Any],
    staff_context: Optional[Dict[str, Any]] = None,
    first_flag: Optional[str] = None,
    descriptions: Optional[List[Tuple[str, str]]] = None,
    output_lang: str = "auto",
    executed_data: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    staff_uid: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Concise narrative for the Direct-BI report card's analysis panel.
    Deterministic, 0 LLM tokens, and deliberately non-duplicative.
    """
    greeting_answer = handle_general_or_greeting(question, staff_context=staff_context)
    if greeting_answer:
        return _clean_markdown_formatting(greeting_answer)
    if staff_uid and conversation_id:
        cq_answer = resolve_cross_questioning(staff_uid, conversation_id, question)
        if cq_answer:
            return _clean_markdown_formatting(cq_answer)

    flag = first_flag or ((descriptions or [])[0][0] if descriptions else "")
    datasets_to_fuse = executed_data if executed_data else [merged_exec]
    rows, cols, kpis, metric_valid = _classify_and_fuse_datasets(datasets_to_fuse, _module_of(flag))

    if not rows and merged_exec:
        rows = [r for r in (merged_exec.get("rows") or []) if isinstance(r, dict)]
        cols = [c for c in (merged_exec.get("columns") or []) if c and not c.startswith("_")]

    if not rows:
        clean_q = _clean_question_title(question, "Commercial Inquiry")
        time_str = _extract_time_context(question, [], None)
        return _clean_markdown_formatting(
            f"**{clean_q}**\n\n"
            f"No activity was recorded in your area for **{time_str}**. "
            f"Try a wider date window, or confirm with your team that this is expected."
        )

    cols_map = {c.lower(): c for c in cols}
    time_col = _find_col(TIME_COL_CANDIDATES, cols_map)
    time_str = _extract_time_context(question, rows, time_col)
    mod_type = _detect_module_type(flag, question, cols)
    analytics = _compute_analytics(rows, cols, kpis, mod_type, time_str, metric_valid)

    if staff_uid and conversation_id:
        _push_turn_to_memory(staff_uid, conversation_id, analytics, question)

    config = _MODULE_CONFIGS.get(mod_type, _MODULE_CONFIGS["generic"])
    # Period breakdowns get a trend narrative, not an entity leaderboard.
    if _is_time_series(rows, cols):
        _pts = _time_series_points(rows, cols)
        if _pts:
            return _clean_markdown_formatting(_build_read_trend(analytics, config, _pts))

    return _clean_markdown_formatting(_build_read(analytics, config))


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 7: SMART DATASET-AWARE CHART SPEC GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def build_deterministic_chart_spec(
    question: str,
    merged_exec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministically recommend and generate an optimized Chart.js visualization spec
    without invoking any LLM, matching the exact schema required by DMSAIChat.jsx.
    """
    rows = (merged_exec.get("rows") or [])[:30]
    cols = [c for c in (merged_exec.get("columns") or []) if c and not c.startswith("_")]
    if not rows or not cols:
        return {}

    cols_map = {c.lower(): c for c in cols}

    def _is_num(v: Any) -> bool:
        if v is None or isinstance(v, bool):
            return False
        if isinstance(v, (int, float, decimal.Decimal)):
            return True
        try:
            float(str(v).replace(",", ""))
            return True
        except (TypeError, ValueError):
            return False

    numeric_cols = [c for c in cols if any(_is_num(r.get(c)) for r in rows)]
    categorical_cols = [c for c in cols if c not in numeric_cols]
    x_opts = categorical_cols or cols
    y_opts = numeric_cols or cols

    val_col = _find_col(VAL_COL_CANDIDATES, cols_map)
    time_col = _find_col(TIME_COL_CANDIDATES, cols_map)
    name_col = _find_col(ENTITY_NAME_CANDIDATES, cols_map)

    # 1. Time-series queries -> Line Chart
    if time_col and val_col and len(rows) >= 2:
        return {
            "chart_type": "line",
            "x": time_col,
            "y": val_col,
            "suggested_x": time_col,
            "suggested_y": val_col,
            "suggested_x_options": x_opts,
            "suggested_y_options": y_opts,
            "rows": rows,
        }

    # 2. Few categories (2 to 6 distinct values) -> Doughnut / Pie Chart
    if name_col and val_col:
        distinct_keys = {str(r.get(name_col)) for r in rows if r.get(name_col)}
        if 2 <= len(distinct_keys) <= 6:
            return {
                "chart_type": "pie",
                "x": name_col,
                "y": val_col,
                "suggested_x": name_col,
                "suggested_y": val_col,
                "suggested_x_options": x_opts,
                "suggested_y_options": y_opts,
                "rows": rows,
            }

    # 3. Entity ranking -> Bar Chart
    if name_col and val_col:
        return {
            "chart_type": "bar",
            "x": name_col,
            "y": val_col,
            "suggested_x": name_col,
            "suggested_y": val_col,
            "suggested_x_options": x_opts,
            "suggested_y_options": y_opts,
            "rows": rows,
        }

    # 4. Fallback
    numeric_col = val_col
    label_col = name_col
    if not numeric_col:
        for c in cols:
            if any(isinstance(r.get(c), (int, float, decimal.Decimal)) for r in rows):
                numeric_col = c
                break

    if not label_col:
        for c in cols:
            if c != numeric_col:
                label_col = c
                break

    if label_col and numeric_col:
        return {
            "chart_type": "bar",
            "x": label_col,
            "y": numeric_col,
            "suggested_x": label_col,
            "suggested_y": numeric_col,
            "suggested_x_options": x_opts,
            "suggested_y_options": y_opts,
            "rows": rows,
        }

    return {}
