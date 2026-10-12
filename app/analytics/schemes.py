"""
DMS Schemes Analytics Module.
Covers trade promotions, discounts, scheme achievement, free stock, and redemption performance.
Fully RBAC-enforced across SO/ASM/RSM/ZSM/NSM levels.
"""
from typing import Optional, Dict, Any
from ..db import run_query
from ._rbac import rbac_clause, build_params


def _date_filter(col: str, params: dict) -> str:
    if params.get("date_from") and params.get("date_to"):
        return f"AND {col} >= :date_from AND {col} < CAST(:date_to AS DATE) + INTERVAL '1 day'"
    if params.get("date_from"):
        return f"AND {col} >= :date_from"
    if params.get("date_to"):
        return f"AND {col} <= :date_to"
    return f"AND {col} >= DATE_TRUNC('month', CURRENT_DATE) AND {col} < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'"


def _sch_filters(params: dict) -> str:
    clauses = []
    if params.get("distributor_id"):
        clauses.append("AND sa.distributorid = :distributor_id")
    if params.get("scheme_type"):
        clauses.append("AND sm.scheme_type = :scheme_type")
    if params.get("scheme_id"):
        clauses.append("AND sm.scheme_id = :scheme_id")
    return " ".join(clauses)


def sch_active_schemes(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """What active schemes are available for my distributor right now?"""
    p = params or {}; qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    sf = _sch_filters(p)
    return run_query(f"""
        SELECT sm.scheme_id, sm.scheme_code, sm.scheme_name, sm.start_date, sm.end_date,
               sm.scheme_type, sm.description
        FROM scheme_master sm
        WHERE sm.is_active IS DISTINCT FROM FALSE
          AND (sm.end_date IS NULL OR sm.end_date >= CURRENT_DATE) {sf}
        ORDER BY sm.start_date DESC {limit_clause}
    """, qp)


def sch_scheme_details(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Details of a specific scheme by code or name."""
    p = params or {}; qp = build_params(userid, p)
    scheme_code = p.get("scheme_code") or p.get("scheme_name") or ""
    qp["scheme_code"] = f"%{scheme_code}%"
    sf = _sch_filters(p)
    return run_query(f"""
        SELECT sm.scheme_id, sm.scheme_code, sm.scheme_name, sm.start_date, sm.end_date,
               sm.scheme_type, sm.slab_details, sm.description
        FROM scheme_master sm
        WHERE (sm.scheme_code ILIKE :scheme_code OR sm.scheme_name ILIKE :scheme_code) {sf}
        LIMIT 10
    """, qp)


def sch_scheme_achievement(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Scheme achievement this month per distributor."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("sa.vch_date", p)
    sf = _sch_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT sa.ds_code, COALESCE(ds.ledgername, sa.ds_code) AS ds_name, sm.scheme_name,
               SUM(sa.target_value) AS target_value,
               SUM(sa.achievement_value) AS achievement_value,
               ROUND(CAST(SUM(sa.achievement_value) * 100.0 / NULLIF(SUM(sa.target_value), 0) AS NUMERIC), 2) AS achievement_pct
        FROM scheme_achievement sa
        INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = sa.distributorid AND ds.ledgertype = 1
        LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
        WHERE 1=1 {df} {sf}
        GROUP BY sa.ds_code, ds.ledgername, sm.scheme_name
        ORDER BY achievement_pct DESC {limit_clause}
    """, qp)


def sch_expiring_soon(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Schemes expiring within the next 7 days."""
    p = params or {}; qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    sf = _sch_filters(p)
    return run_query(f"""
        SELECT sm.scheme_id, sm.scheme_code, sm.scheme_name, sm.start_date, sm.end_date,
               sm.end_date - CURRENT_DATE AS days_remaining
        FROM scheme_master sm
        WHERE sm.is_active IS DISTINCT FROM FALSE
          AND sm.end_date >= CURRENT_DATE
          AND sm.end_date <= CURRENT_DATE + INTERVAL '7 days' {sf}
        ORDER BY sm.end_date ASC {limit_clause}
    """, qp)


def sch_free_stock_earned(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Free stock earned through schemes this month."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("sa.vch_date", p)
    sf = _sch_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT sa.ds_code, COALESCE(ds.ledgername, sa.ds_code) AS ds_name,
               SUM(sa.free_stock_qty) AS total_free_qty,
               SUM(sa.free_stock_value) AS total_free_value
        FROM scheme_achievement sa
        INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = sa.distributorid AND ds.ledgertype = 1
        LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
        WHERE sa.free_stock_qty > 0 {df} {sf}
        GROUP BY sa.ds_code, ds.ledgername
        ORDER BY total_free_value DESC {limit_clause}
    """, qp)


def sch_redemption_history(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Scheme redemption history for the last 3 months."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    sf = _sch_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT sa.ds_code, COALESCE(ds.ledgername, sa.ds_code) AS ds_name, sm.scheme_name,
               DATE_TRUNC('month', sa.vch_date) AS redemption_month,
               SUM(sa.achievement_value) AS redeemed_value,
               SUM(sa.free_stock_value) AS free_stock_value
        FROM scheme_achievement sa
        INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = sa.distributorid AND ds.ledgertype = 1
        LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
        WHERE sa.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months' {sf}
        GROUP BY sa.ds_code, ds.ledgername, sm.scheme_name, DATE_TRUNC('month', sa.vch_date)
        ORDER BY redemption_month DESC, redeemed_value DESC {limit_clause}
    """, qp)


def sch_area_utilization(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Best utilized scheme in my area [ASM+]."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("sa.vch_date", p)
    sf = _sch_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT sm.scheme_id, sm.scheme_name,
               COUNT(DISTINCT sa.distributorid) AS participating_distributors,
               SUM(sa.achievement_value) AS total_achievement_value
        FROM scheme_achievement sa
        INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
        LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
        WHERE 1=1 {df} {sf}
        GROUP BY sm.scheme_id, sm.scheme_name
        ORDER BY total_achievement_value DESC {limit_clause}
    """, qp)


def sch_distributor_perf(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Scheme performance by distributor [ASM+]."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("sa.vch_date", p)
    sf = _sch_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT sa.ds_code, COALESCE(ds.ledgername, sa.ds_code) AS ds_name,
               COUNT(DISTINCT sa.scheme_id) AS active_schemes_count,
               SUM(sa.achievement_value) AS total_scheme_benefit
        FROM scheme_achievement sa
        INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = sa.distributorid AND ds.ledgertype = 1
        LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
        WHERE 1=1 {df} {sf}
        GROUP BY sa.ds_code, ds.ledgername
        ORDER BY total_scheme_benefit DESC {limit_clause}
    """, qp)


def sch_cost_vs_uplift(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total scheme cost vs secondary sales uplift nationally [NSM]."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df_sa = _date_filter("sa.vch_date", p)
    df_td = _date_filter("td.vch_date", p)
    sf = _sch_filters(p)
    return run_query(f"""
        WITH scheme_cost AS (
            SELECT SUM(sa.free_stock_value + sa.discount_value) AS total_scheme_cost
            FROM scheme_achievement sa
            INNER JOIN ({rbac}) accd ON accd.locationid = sa.distributorid
            LEFT JOIN scheme_master sm ON sm.scheme_id = sa.scheme_id
            WHERE 1=1 {df_sa} {sf}
        ),
        sales_val AS (
            SELECT SUM(td.billed_value) AS total_secondary_sales
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_td}
        )
        SELECT sc.total_scheme_cost, sv.total_secondary_sales,
               ROUND(CAST(sc.total_scheme_cost * 100.0 / NULLIF(sv.total_secondary_sales, 0) AS NUMERIC), 2) AS scheme_cost_pct_of_sales
        FROM scheme_cost sc, sales_val sv
    """, qp)


SCHEMES_FLAGS = {
    "sch:active-schemes":     (sch_active_schemes,     "Active schemes available for my distributor right now"),
    "sch:scheme-details":     (sch_scheme_details,     "Details of a specific scheme by code or name"),
    "sch:scheme-achievement": (sch_scheme_achievement, "Scheme achievement this month per distributor"),
    "sch:expiring-soon":       (sch_expiring_soon,       "Schemes expiring within the next 7 days"),
    "sch:free-stock-earned":   (sch_free_stock_earned,   "Free stock earned through schemes this month"),
    "sch:redemption-history":  (sch_redemption_history,  "Scheme redemption history for the last 3 months"),
    "sch:area-utilization":   (sch_area_utilization,   "Best utilized scheme in my area [ASM+]"),
    "sch:distributor-perf":   (sch_distributor_perf,   "Scheme performance by distributor [ASM+]"),
    "sch:cost-vs-uplift":      (sch_cost_vs_uplift,      "Total scheme cost vs secondary sales uplift nationally [NSM]"),
}
