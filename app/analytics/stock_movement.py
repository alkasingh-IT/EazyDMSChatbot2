"""
DMS Stock Movement Analytics Module — Highly Customizable.
Source Table: tbl_stock_movement_item_wise_report_ai_@userid
RBAC is enforced during temp table generation.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from ..db import run_query
from ._rbac import build_params

def _get_table(userid: str) -> str:
    """Get user-specific temp table name for stock movement."""
    uid_safe = str(userid).replace('-', '_')
    return f"tbl_stock_movement_item_wise_report_ai_{uid_safe}"

def _sm_dynamic_filters(p: dict, qp: dict) -> str:
    """Extract common dynamic filters."""
    clauses = []
    if p.get("item_code") or p.get("itemcode"):
        clauses.append("\"Item Code\" ILIKE :sm_itemcode")
        qp["sm_itemcode"] = f"%{p.get('item_code') or p.get('itemcode')}%"
    if p.get("distributor_code") or p.get("ds_code"):
        clauses.append("\"ds_code\" ILIKE :sm_dscode")
        qp["sm_dscode"] = f"%{p.get('distributor_code') or p.get('ds_code')}%"
    if p.get("zone"):
        clauses.append("\"Zone\" ILIKE :sm_zone")
        qp["sm_zone"] = f"%{p['zone']}%"
    if p.get("state"):
        clauses.append("\"State\" ILIKE :sm_state")
        qp["sm_state"] = f"%{p['state']}%"
    if p.get("division"):
        clauses.append("\"Item Division\" ILIKE :sm_division")
        qp["sm_division"] = f"%{p['division']}%"

    if clauses:
        return " AND " + " AND ".join(clauses)
    return ""

def _get_period_days(p: dict) -> int:
    """Calculate period days for velocity metrics."""
    if p.get("date_from") and p.get("date_to"):
        try:
            d1 = datetime.strptime(str(p["date_from"]), "%Y-%m-%d")
            d2 = datetime.strptime(str(p["date_to"]), "%Y-%m-%d")
            days = (d2 - d1).days + 1
            return days if days > 0 else 30
        except Exception:
            return 30
    return 30

# ==========================================
# Section 1 — Closing & Opening Stock
# ==========================================

def sm_closing_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Current closing stock value and qty (Customizable grouping)."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid)
    group_by = str(p.get("group_by", "distributor")).strip().lower()
    _limit = int(p.get("limit", 50))
    
    if group_by == "zone":
        gb_cols = "\"Zone\""
        sel_cols = "\"Zone\""
    elif group_by == "state":
        gb_cols = "\"State\""
        sel_cols = "\"State\""
    elif group_by == "item":
        gb_cols = "\"Item Code\", \"Item Description\", \"Item Division\""
        sel_cols = "\"Item Code\", \"Item Description\", \"Item Division\""
    else: # default distributor
        gb_cols = "\"ds_code\", \"ds_name\", \"Zone\", \"State\""
        sel_cols = "\"ds_code\", \"ds_name\", \"Zone\", \"State\""

    return run_query(f"""
        SELECT {sel_cols},
               SUM("Closing Stock") AS total_closing_qty,
               SUM("Closing Value") AS total_closing_value
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY {gb_cols}
        ORDER BY total_closing_value DESC
        LIMIT {_limit}
    """, qp)

def sm_opening_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Opening stock value and qty for the period."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name",
               SUM("Opening Stock") AS total_opening_qty
        FROM {tbl}
        WHERE "Opening Stock" <> 0 {dyn_f}
        GROUP BY "ds_code", "ds_name"
        ORDER BY total_opening_qty DESC
        LIMIT {_limit}
    """, qp)

def sm_stock_statement(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Full stock statement (Opening, Purchases, Sales, Closing) by distributor/item."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    group_by = str(p.get("group_by", "distributor")).strip().lower()
    
    if group_by == "item":
        gb_cols = "\"Item Code\", \"Item Description\", \"Item Division\""
        sel_cols = "\"Item Code\", \"Item Description\", \"Item Division\""
    elif group_by == "zone":
        gb_cols = "\"Zone\""
        sel_cols = "\"Zone\""
    else:
        gb_cols = "\"ds_code\", \"ds_name\""
        sel_cols = "\"ds_code\", \"ds_name\""

    return run_query(f"""
        SELECT {sel_cols},
               SUM("Opening Stock") AS opening_stock,
               SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note") AS total_purchases,
               SUM("Receipt Note") AS receipt_note,
               SUM("Misc In") AS misc_in,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS total_sales,
               SUM("Delivery Note") AS delivery_note,
               SUM("Misc Out") AS misc_out,
               SUM("Closing Stock") AS closing_stock,
               SUM("Closing Value") AS closing_value
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY {gb_cols}
        ORDER BY closing_value DESC
        LIMIT {_limit}
    """, qp)

# ==========================================
# Section 2 — Velocity & Health Metrics
# ==========================================

def sm_stock_cover(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Days of stock cover (Closing Stock / Avg Daily Sales). Filter by low/high cover."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    period_days = _get_period_days(p)
    
    cover_type = str(p.get("cover_type", "all")).lower()
    extra_where = ""
    order_dir = "ASC"
    if cover_type == "low":
        extra_where = f" AND (\"Closing Stock\" / NULLIF((\"Sales without Delivery Note\" + \"Sales with Delivery Note\") / {period_days}, 0)) < 7"
    elif cover_type == "overstock":
        extra_where = f" AND (\"Closing Stock\" / NULLIF((\"Sales without Delivery Note\" + \"Sales with Delivery Note\") / {period_days}, 0)) > 45"
        order_dir = "DESC"

    return run_query(f"""
        SELECT "ds_code", "ds_name", "Item Code", "Item Description", "Item Division",
               "Closing Stock", "Closing Value",
               ("Sales without Delivery Note" + "Sales with Delivery Note") AS total_sales_qty,
               ROUND(CAST("Closing Stock" / NULLIF(("Sales without Delivery Note" + "Sales with Delivery Note") / {period_days}, 0) AS NUMERIC), 1) AS days_cover
        FROM {tbl}
        WHERE "Closing Stock" > 0
          AND ("Sales without Delivery Note" + "Sales with Delivery Note") > 0
          {extra_where} {dyn_f}
        ORDER BY days_cover {order_dir}
        LIMIT {_limit}
    """, qp)

def sm_offtake_efficiency(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Percentage of purchases converted to secondary sales."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name",
               SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note") AS total_purchases,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS total_sales,
               ROUND(CAST((SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note"))
                     / NULLIF(SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note"), 0) * 100 AS NUMERIC), 2) AS offtake_efficiency_pct
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY "ds_code", "ds_name"
        ORDER BY offtake_efficiency_pct DESC
        LIMIT {_limit}
    """, qp)

def sm_stock_turn_ratio(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Stock Turn Ratio (Total Sales / Avg Stock)."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name", "Zone",
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS total_sales,
               (SUM("Opening Stock") + SUM("Closing Stock")) / 2.0 AS avg_stock,
               ROUND(CAST((SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note"))
                     / NULLIF((SUM("Opening Stock") + SUM("Closing Stock")) / 2.0, 0) AS NUMERIC), 2) AS stock_turn_ratio
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY "ds_code", "ds_name", "Zone"
        ORDER BY stock_turn_ratio DESC
        LIMIT {_limit}
    """, qp)

# ==========================================
# Section 3 — Variance & Discrepancies
# ==========================================

def sm_stock_variance(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Variance between Opening and Closing stock."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name", "Item Code", "Item Description",
               "Opening Stock", "Closing Stock",
               "Closing Stock" - "Opening Stock" AS stock_variance,
               CASE
                 WHEN "Opening Stock" > 0
                 THEN ROUND(CAST(("Closing Stock" - "Opening Stock") / "Opening Stock" * 100 AS NUMERIC), 2)
                 ELSE NULL
               END AS variance_pct
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        ORDER BY stock_variance ASC
        LIMIT {_limit}
    """, qp)

def sm_zero_negative_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Identify items with zero or negative closing stock (discrepancy)."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name", "Item Code", "Item Description", "Item Division",
               "Opening Stock", "Closing Stock"
        FROM {tbl}
        WHERE "Closing Stock" <= 0
          AND "Opening Stock" > 0 {dyn_f}
        ORDER BY "Closing Stock" ASC
        LIMIT {_limit}
    """, qp)

def sm_dead_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Items with closing stock but ZERO sales/purchases movement."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name", "Zone", "Item Code", "Item Description", "Item Division",
               "Opening Stock", "Closing Stock", "Closing Value"
        FROM {tbl}
        WHERE "Closing Stock" > 0
          AND "Sales without Delivery Note" = 0
          AND "Sales with Delivery Note" = 0
          AND "Delivery Note" = 0
          AND "Purchase without Receipt Note" = 0
          AND "Purchase with Receipt Note" = 0
          AND "Misc In" = 0
          AND "Misc Out" = 0 {dyn_f}
        ORDER BY "Closing Value" DESC
        LIMIT {_limit}
    """, qp)

def sm_misc_adjustments(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Track manual stock additions (Misc In) or stock loss/adjustments (Misc Out)."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    adj_type = str(p.get("adj_type", "out")).lower()
    col = "\"Misc Out\"" if adj_type == "out" else "\"Misc In\""
    
    return run_query(f"""
        SELECT "ds_code", "ds_name", "Item Code", "Item Description", "Item Division",
               {col} AS adjustment_qty
        FROM {tbl}
        WHERE {col} <> 0 {dyn_f}
        ORDER BY adjustment_qty DESC
        LIMIT {_limit}
    """, qp)

# ==========================================
# Section 4 — Inward & Outward Totals
# ==========================================

def sm_inward_movement(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total stock received (purchases/inward) with receipt note breakdown."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name",
               SUM("Purchase without Receipt Note") AS purchase_without_rn,
               SUM("Purchase with Receipt Note") AS purchase_with_rn,
               SUM("Receipt Note") AS receipt_note_qty,
               SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note") AS total_inward_qty
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY "ds_code", "ds_name"
        ORDER BY total_inward_qty DESC
        LIMIT {_limit}
    """, qp)

def sm_outward_movement(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total stock sold (outward) with delivery note breakdown."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT "ds_code", "ds_name",
               SUM("Sales without Delivery Note") AS sales_without_dn,
               SUM("Sales with Delivery Note") AS sales_with_dn,
               SUM("Delivery Note") AS delivery_note_qty,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS total_outward_qty
        FROM {tbl}
        WHERE 1=1 {dyn_f}
        GROUP BY "ds_code", "ds_name"
        ORDER BY total_outward_qty DESC
        LIMIT {_limit}
    """, qp)

def sm_tally_variance(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Reconciliation between DMS Closing Stock and Tally Physical Stock."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid); _limit = int(p.get("limit", 50))
    
    return run_query(f"""
        SELECT t."ds_code", t."ds_name", t."Item Code", t."Item Description",
               t."Closing Stock" AS dms_closing_stock,
               COALESCE(ps.physical_qty, 0) AS tally_physical_stock,
               t."Closing Stock" - COALESCE(ps.physical_qty, 0) AS variance
        FROM {tbl} t
        LEFT JOIN physical_stock_sync ps
          ON ps.distributorcode = t."ds_code" AND ps.itemcode = t."Item Code"
        WHERE 1=1 {dyn_f}
        ORDER BY ABS(t."Closing Stock" - COALESCE(ps.physical_qty, 0)) DESC
        LIMIT {_limit}
    """, qp)

def sm_executive_summary(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Full territory stock movement executive summary KPI card."""
    p = params or {}; qp = build_params(userid, p); dyn_f = _sm_dynamic_filters(p, qp)
    tbl = _get_table(userid)
    return run_query(f"""
        SELECT SUM("Opening Stock") AS total_opening_qty,
               SUM("Closing Stock") AS total_closing_qty,
               SUM("Closing Value") AS total_closing_value,
               SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note") AS total_inflow_qty,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS total_outflow_qty,
               COUNT(DISTINCT "ds_code") AS active_distributors,
               COUNT(DISTINCT "Item Code") AS active_skus
        FROM {tbl}
        WHERE 1=1 {dyn_f}
    """, qp)


STOCK_MOVEMENT_FLAGS = {
    "sm:closing-stock":         (sm_closing_stock, "Current closing stock value and qty (supports group_by distributor/zone/state/item)"),
    "sm:opening-stock":         (sm_opening_stock, "Opening stock value and qty for the period"),
    "sm:stock-statement":       (sm_stock_statement, "Full stock statement (Opening, Purchases, Sales, Closing) by distributor/item"),
    "sm:stock-cover":           (sm_stock_cover, "Days of stock cover (Closing Stock / Avg Daily Sales). Use cover_type=low/overstock for alerts"),
    "sm:offtake-efficiency":    (sm_offtake_efficiency, "Percentage of purchases converted to secondary sales"),
    "sm:stock-turn-ratio":      (sm_stock_turn_ratio, "Stock Turn Ratio (Total Sales / Avg Stock)"),
    "sm:stock-variance":        (sm_stock_variance, "Variance between Opening and Closing stock"),
    "sm:zero-negative-stock":   (sm_zero_negative_stock, "Identify items with zero or negative closing stock (discrepancy)"),
    "sm:dead-stock":            (sm_dead_stock, "Items with closing stock but ZERO sales/purchases movement"),
    "sm:misc-adjustments":      (sm_misc_adjustments, "Track manual stock additions (Misc In) or stock loss/adjustments (Misc Out)"),
    "sm:inward-movement":       (sm_inward_movement, "Total stock received (purchases/inward) with receipt note breakdown"),
    "sm:outward-movement":      (sm_outward_movement, "Total stock sold (outward) with delivery note breakdown"),
    "sm:tally-variance":        (sm_tally_variance, "Reconciliation between DMS Closing Stock and Tally Physical Stock"),
    "sm:executive-summary":     (sm_executive_summary, "Territory stock movement executive summary"),
}
