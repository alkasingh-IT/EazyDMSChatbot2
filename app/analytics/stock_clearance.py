"""
DMS Stock Clearance Analytics Module — Highly Customizable RBAC-enforced Flags.
Output Table: ai_output.stock_clearance_recommendations
RBAC Bridge: location_access_detail via distributor_ledger_id or ledgermaster.ledgercode
"""
from typing import Optional, Dict, Any
from ..db import run_query, run_parallel
from ._rbac import rbac_clause, build_params


def _sc_rbac_join(p: Optional[dict] = None) -> str:
    """Standard RBAC SQL Join for Stock Clearance using location_access_detail."""
    rbac = rbac_clause(p)
    return f"""
        LEFT JOIN ledgermaster lm ON lm.ledgercode = sc.distributor_code
        INNER JOIN ({rbac}) accd ON accd.locationid = COALESCE(sc.distributor_ledger_id, lm.ledgerid)
    """


def _sc_dynamic_filters(p: dict, qp: dict) -> str:
    """Helper to extract common customizable filters (category, brand, zone, state, city, status, health)."""
    clauses = []

    # 1. Category / Brand
    if p.get("category"):
        clauses.append("LOWER(sc.category) = LOWER(:sc_category)")
        qp["sc_category"] = str(p["category"]).strip()
    if p.get("brand"):
        clauses.append("LOWER(sc.brand) = LOWER(:sc_brand)")
        qp["sc_brand"] = str(p["brand"]).strip()

    # 2. Geography (Zone, State, City)
    if p.get("zone"):
        clauses.append("LOWER(sc.zone) = LOWER(:sc_zone)")
        qp["sc_zone"] = str(p["zone"]).strip()
    if p.get("state"):
        clauses.append("LOWER(sc.state) = LOWER(:sc_state)")
        qp["sc_state"] = str(p["state"]).strip()
    if p.get("city"):
        clauses.append("LOWER(sc.city) = LOWER(:sc_city)")
        qp["sc_city"] = str(p["city"]).strip()

    # 3. Stock Status & Health
    if p.get("stock_status"):
        clauses.append("UPPER(sc.stock_status) = UPPER(:sc_stock_status)")
        qp["sc_stock_status"] = str(p["stock_status"]).strip()
    if p.get("stock_health"):
        clauses.append("UPPER(sc.stock_health) = UPPER(:sc_stock_health)")
        qp["sc_stock_health"] = str(p["stock_health"]).strip()

    # 4. Distributor filter
    if p.get("distributor_code"):
        clauses.append("LOWER(sc.distributor_code) = LOWER(:sc_dist_code)")
        qp["sc_dist_code"] = str(p["distributor_code"]).strip()

    if clauses:
        return " AND " + " AND ".join(clauses)
    return ""


# Allowed columns for dynamic group_col and filter_col
_SC_GROUP_COLS = {
    "distributor_code", "distributor_name", "category", "brand", "stock_status",
    "stock_health", "primary_action", "scheme_type", "expiry_risk",
    "seasonality_recommendation", "peak_month_name", "city", "state", "zone", "offtake_trend"
}

_SC_METRICS = {
    "closing_value", "closing_stock", "dos", "ageing_days",
    "xfr_net_recovery_est", "xfr_logistics_cost_est", "est_scheme_net_recovery",
    "scheme_disc_pct", "anomaly_score", "seasonality_strength"
}

# Combined whitelist for filter_col — mirrors _SS_FILTER_COLS pattern in secondary_sales
_SC_FILTER_COLS = _SC_GROUP_COLS | _SC_METRICS | {
    "item_code", "item_name", "distributor_name", "distributor_code",
    "priority_rank", "days_to_expiry", "xfr_distance_km",
    "transfer_recommended", "needs_clearance", "early_warning_flag",
    "days_until_peak", "est_clearance_pct", "seasonality_strength"
}


# ==========================================
# Section 1 — Basic Stock Health & Summary
# ==========================================

def sc1_dead_stock_count(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many SKUs are currently classified as dead stock in my territory? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(DISTINCT sc.item_code) AS dead_sku_count,
               COUNT(*) AS total_dead_records,
               COUNT(DISTINCT sc.distributor_code) AS distributor_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_dead_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD'{df}
    """, qp)


def sc2_dead_stock_value(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """What is the total dead stock value across my distributors? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COALESCE(SUM(sc.closing_value), 0) AS total_dead_stock_value,
               COALESCE(SUM(sc.closing_stock), 0) AS total_dead_stock_units,
               COUNT(DISTINCT sc.item_code) AS dead_sku_count,
               COUNT(DISTINCT sc.distributor_code) AS distributor_count
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD'{df}
    """, qp)


def sc3_slow_vs_dead(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many SKUs are slow-moving vs dead across my area? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT UPPER(sc.stock_status) AS stock_status,
               COUNT(DISTINCT sc.item_code) AS sku_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_value,
               COALESCE(SUM(sc.closing_stock), 0) AS total_qty
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) IN ('SLOW', 'DEAD', 'FAST', 'NEW'){df}
        GROUP BY UPPER(sc.stock_status)
        ORDER BY total_value DESC
    """, qp)


def sc4_health_distribution(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Full stock health distribution across territory / zone (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.stock_health,
               COUNT(*) AS item_count,
               COUNT(DISTINCT sc.item_code) AS sku_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
        GROUP BY sc.stock_health
        ORDER BY total_value DESC
    """, qp)


def sc5_at_risk_pct(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """What percentage of total stock value is at risk (slow + dead)? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        WITH base AS (
            SELECT sc.stock_status, sc.closing_value
            FROM ai_output.stock_clearance_recommendations sc
            {rbac_j}
            WHERE 1=1{df}
        )
        SELECT COALESCE(SUM(CASE WHEN UPPER(stock_status) IN ('SLOW','DEAD') THEN closing_value ELSE 0 END), 0) AS at_risk_value,
               COALESCE(SUM(closing_value), 0) AS total_stock_value,
               ROUND(
                   COALESCE(SUM(CASE WHEN UPPER(stock_status) IN ('SLOW','DEAD') THEN closing_value ELSE 0 END), 0)
                   * 100.0 / NULLIF(SUM(closing_value), 0), 2
               ) AS at_risk_pct
        FROM base
    """, qp)


def sc6_top_distributor_dead_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which distributor has the highest dead stock value in my region? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 10); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.city, sc.state, sc.zone,
               COALESCE(SUM(sc.closing_value), 0) AS dead_stock_value,
               COUNT(DISTINCT sc.item_code) AS dead_sku_count
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD'{df}
        GROUP BY sc.distributor_code, sc.distributor_name, sc.city, sc.state, sc.zone
        ORDER BY dead_stock_value DESC
        LIMIT {_limit}
    """, qp)


def sc7_distributors_with_dead_stock_count(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many distributors have at least one DEAD SKU? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(DISTINCT sc.distributor_code) AS distributors_with_dead_stock,
               COALESCE(SUM(sc.closing_value), 0) AS total_dead_stock_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD'{df}
    """, qp)


def sc8_avg_dos(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """What is the average Days of Stock across all my distributors? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT ROUND(AVG(sc.dos), 1) AS avg_dos,
               MIN(sc.dos) AS min_dos,
               MAX(sc.dos) AS max_dos,
               COUNT(*) AS total_items
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.dos < 9999{df}
    """, qp)


def sc9_new_stock(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which SKUs are classified as NEW stock? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_code, sc.item_name, sc.category, sc.closing_stock, sc.closing_value, sc.dos
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'NEW'{df}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


def sc10_overstocked_distributors(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many distributors are flagged as OVERSTOCKED? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.city,
               COUNT(*) AS overstocked_item_count,
               COALESCE(SUM(sc.closing_value), 0) AS overstocked_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.stock_health = 'OVERSTOCKED'{df}
        GROUP BY sc.distributor_code, sc.distributor_name, sc.city
        ORDER BY overstocked_value DESC
        LIMIT {_limit}
    """, qp)


# ==========================================
# Section 2 — Priority Actions & Urgency
# ==========================================

def sc13_top_priority_actions(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Top urgent dead stock items to act on today ranked by priority_rank (RBAC enforced, customizable limit)."""
    p = params or {}; _limit = p.get("limit", 5); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.priority_rank, sc.distributor_name, sc.item_name, sc.category,
               sc.closing_value, sc.stock_status, sc.stock_health, sc.primary_action,
               sc.transfer_recommended, sc.scheme_type, sc.scheme_disc_pct
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.priority_rank IS NOT NULL{df}
        ORDER BY sc.priority_rank ASC
        LIMIT {_limit}
    """, qp)


def sc14_longest_ageing_items(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which items have been sitting the longest without any sale? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = max(1, min(int(p.get("limit", 10)), 500)); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.ageing_days,
               sc.closing_stock, sc.closing_value, sc.stock_status, sc.primary_action
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
        ORDER BY sc.ageing_days DESC NULLS LAST
        LIMIT {_limit}
    """, qp)


def sc15_clearance_required_high_value(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Show me CLEARANCE_REQUIRED items above min_value threshold (RBAC enforced, customizable min_value)."""
    p = params or {}; val_min = float(p.get("min_value", 50000)); qp = build_params(userid, p); qp["val_min"] = val_min
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.priority_rank, sc.distributor_name, sc.item_name, sc.category,
               sc.closing_value, sc.dos, sc.primary_action, sc.scheme_disc_pct
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.stock_health = 'CLEARANCE_REQUIRED' AND sc.closing_value >= :val_min{df}
        ORDER BY sc.closing_value DESC
    """, qp)


def sc16_urgent_distributors(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which distributors need immediate attention based on priority rank? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = max(1, min(int(p.get("limit", 10)), 100)); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.city,
               MIN(sc.priority_rank) AS top_priority_rank,
               COUNT(*) AS total_items,
               COALESCE(SUM(sc.closing_value), 0) AS total_at_risk_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.priority_rank IS NOT NULL{df}
        GROUP BY sc.distributor_code, sc.distributor_name, sc.city
        ORDER BY top_priority_rank ASC
        LIMIT {_limit}
    """, qp)


def sc17_critical_priority_value(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total value of items flagged as Critical priority (rank <= max_rank) (RBAC enforced, customizable)."""
    p = params or {}; max_rank = int(p.get("max_rank", 10)); qp = build_params(userid, p); qp["max_rank"] = max_rank
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS critical_item_count,
               COALESCE(SUM(sc.closing_value), 0) AS critical_priority_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.priority_rank <= :max_rank{df}
    """, qp)


def sc19_ageing_urgent_count(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many items are in the ageing_urgent bucket? (RBAC enforced, customizable min_ageing_days)."""
    p = params or {}; min_days = int(p.get("min_ageing_days", 180)); qp = build_params(userid, p); qp["min_days"] = min_days
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS ageing_urgent_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.ageing_urgent = TRUE OR sc.ageing_days >= :min_days){df}
    """, qp)


def sc20_transfer_vs_scheme_split(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Percentage of dead stock items with transfer recommendation vs scheme only (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.primary_action,
               COUNT(*) AS item_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_value,
               ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) AS pct_share
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD'{df}
        GROUP BY sc.primary_action
        ORDER BY total_value DESC
    """, qp)


# ==========================================
# Section 3 — Transfer Recommendations
# ==========================================

def sc23_transfer_recommendations(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which of my dead stock items have a transfer recommendation? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.priority_rank, sc.distributor_name, sc.item_name, sc.closing_stock,
               sc.closing_value, sc.xfr_target_dist_name, sc.xfr_distance_km,
               sc.xfr_net_recovery_est, sc.xfr_logistics_cost_est
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.transfer_recommended = TRUE{df}
        ORDER BY sc.xfr_net_recovery_est DESC NULLS LAST
        LIMIT {_limit}
    """, qp)


def sc25_transfer_total_recovery(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Estimated total recovery from all recommended transfers in my area (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS transfer_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_transfer_stock_value,
               COALESCE(SUM(sc.xfr_net_recovery_est), 0) AS total_net_recovery_est,
               COALESCE(SUM(sc.xfr_logistics_cost_est), 0) AS total_logistics_cost_est
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.transfer_recommended = TRUE{df}
    """, qp)


def sc26_same_city_transfers(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which transfer routes are within the same city? (RBAC enforced, customizable same_city_km, limit)"""
    p = params or {}; _limit = p.get("limit", 50); same_city_km = int(p.get("same_city_km", 25))
    qp = build_params(userid, p); qp["same_city_km"] = same_city_km
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value,
               sc.xfr_target_dist_name, sc.xfr_distance_km, sc.xfr_net_recovery_est
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.transfer_recommended = TRUE AND (sc.xfr_proximity_label = 'Same City' OR sc.xfr_distance_km <= :same_city_km){df}
        ORDER BY sc.xfr_distance_km ASC
        LIMIT {_limit}
    """, qp)


def sc27_transfers_within_50km(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Show me all transfers within max_km radius (RBAC enforced, customizable max_km, limit)."""
    p = params or {}; _limit = p.get("limit", 50); max_km = float(p.get("max_km", 50))
    qp = build_params(userid, p); qp["max_km"] = max_km
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value,
               sc.xfr_target_dist_name, sc.xfr_distance_km, sc.xfr_net_recovery_est
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.transfer_recommended = TRUE AND sc.xfr_distance_km <= :max_km{df}
        ORDER BY sc.xfr_distance_km ASC
        LIMIT {_limit}
    """, qp)


def sc28_dead_stock_no_transfer(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which dead stock items have no viable transfer route? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.closing_value,
               sc.dos, sc.scheme_type, sc.scheme_disc_pct, sc.est_scheme_net_recovery
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD' AND (sc.transfer_recommended IS NOT TRUE){df}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


def sc31_transfer_logistics_cost(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How much total logistics cost is estimated across transfer routes? (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS total_transfers,
               COALESCE(SUM(sc.xfr_logistics_cost_est), 0) AS total_logistics_cost,
               COALESCE(SUM(sc.xfr_net_recovery_est), 0) AS total_net_recovery
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.transfer_recommended = TRUE{df}
    """, qp)


# ==========================================
# Section 4 — Scheme Recommendations
# ==========================================

def sc36_scheme_recommendations(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Discount schemes recommended for dead stock (RBAC enforced, customizable limit)."""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.closing_value,
               sc.scheme_type, sc.scheme_disc_pct, sc.est_clearance_pct, sc.est_scheme_net_recovery
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.scheme_type IS NOT NULL OR UPPER(sc.stock_status) = 'DEAD'){df}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


def sc37_aggressive_schemes(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which items have an aggressive flat discount scheme? (RBAC enforced, customizable min_discount, limit)."""
    p = params or {}; _limit = p.get("limit", 50); min_disc = float(p.get("min_discount", 30))
    qp = build_params(userid, p); qp["min_disc"] = min_disc
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value,
               sc.scheme_type, sc.scheme_disc_pct, sc.est_clearance_pct
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.scheme_type ILIKE '%Aggressive%' OR sc.scheme_disc_pct >= :min_disc){df}
        ORDER BY sc.scheme_disc_pct DESC
        LIMIT {_limit}
    """, qp)


def sc38_avg_discount_pct(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Average recommended discount % across all DEAD items (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT ROUND(AVG(sc.scheme_disc_pct), 2) AS avg_discount_pct,
               MIN(sc.scheme_disc_pct) AS min_discount_pct,
               MAX(sc.scheme_disc_pct) AS max_discount_pct,
               COUNT(*) AS total_items
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'DEAD' AND sc.scheme_disc_pct IS NOT NULL{df}
    """, qp)


def sc39_free_qty_schemes(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which items are recommended for Free Qty scheme? (RBAC enforced, customizable scheme_keyword, limit)"""
    p = params or {}; _limit = p.get("limit", 50)
    scheme_kw = str(p.get("scheme_keyword", "Free Qty")).strip()
    qp = build_params(userid, p); qp["scheme_kw"] = f"%{scheme_kw}%"
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value, sc.scheme_type, sc.est_clearance_pct
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.scheme_type ILIKE :scheme_kw OR sc.scheme_type ILIKE '%Buy%'){df}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


def sc40_est_clearance_pct(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Estimated clearance % if recommended schemes are executed (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT ROUND(AVG(sc.est_clearance_pct), 2) AS avg_est_clearance_pct,
               COALESCE(SUM(sc.closing_value), 0) AS total_stock_value,
               COALESCE(SUM(sc.est_scheme_net_recovery), 0) AS est_total_net_recovery
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.needs_clearance = TRUE OR sc.scheme_type IS NOT NULL){df}
    """, qp)


def sc44_total_scheme_recovery(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total estimated scheme recovery across territory / zone (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS item_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_at_risk_value,
               COALESCE(SUM(sc.est_scheme_net_recovery), 0) AS total_scheme_recovery_est
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.needs_clearance = TRUE OR UPPER(sc.stock_status) IN ('DEAD', 'SLOW')){df}
    """, qp)


# ==========================================
# Section 5 — Seasonality Intelligence
# ==========================================

def sc46_seasonal_holds(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which items are on HOLD_FOR_SEASON? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.closing_value,
               sc.peak_month_name, sc.days_until_peak, sc.seasonality_strength
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.seasonality_recommendation = 'HOLD_FOR_SEASON'{df}
        ORDER BY sc.days_until_peak ASC NULLS LAST
        LIMIT {_limit}
    """, qp)


def sc47_peak_season_timeline(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """When is peak season for held items & days until peak? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.peak_month_name,
               MIN(sc.days_until_peak) AS min_days_until_peak,
               COUNT(*) AS item_count,
               COALESCE(SUM(sc.closing_value), 0) AS hold_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.seasonality_recommendation = 'HOLD_FOR_SEASON'{df}
        GROUP BY sc.peak_month_name
        ORDER BY min_days_until_peak ASC NULLS LAST
    """, qp)


def sc50_seasonal_hold_value(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """What is the total value of stock currently on seasonal hold? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS hold_item_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_seasonal_hold_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.seasonality_recommendation = 'HOLD_FOR_SEASON'{df}
    """, qp)


def sc54_high_seasonality_items(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Items with seasonality_strength above min_strength (RBAC enforced, customizable min_strength, limit)"""
    p = params or {}; _limit = p.get("limit", 50); min_str = float(p.get("min_strength", 0.80))
    qp = build_params(userid, p); qp["min_str"] = min_str
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.closing_value,
               sc.seasonality_strength, sc.seasonality_type, sc.seasonality_recommendation
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.seasonality_strength > :min_str{df}
        ORDER BY sc.seasonality_strength DESC
        LIMIT {_limit}
    """, qp)


# ==========================================
# Section 6 — Expiry Risk
# ==========================================

def sc56_expiring_30_days(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Items expiring in next max_days (RBAC enforced, customizable max_days, limit)"""
    p = params or {}; _limit = p.get("limit", 100); max_days = int(p.get("max_days", 30))
    qp = build_params(userid, p); qp["max_days"] = max_days
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_stock, sc.closing_value,
               sc.days_to_expiry, sc.expiry_risk, sc.primary_action, sc.scheme_disc_pct
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.days_to_expiry <= :max_days AND sc.days_to_expiry >= 0{df}
        ORDER BY sc.days_to_expiry ASC
        LIMIT {_limit}
    """, qp)


def sc57_already_expired(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Items that have already expired (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 100); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_stock, sc.closing_value,
               sc.days_to_expiry, sc.expiry_risk
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.expiry_risk = 'Already Expired' OR sc.days_to_expiry < 0){df}
        ORDER BY sc.days_to_expiry ASC
        LIMIT {_limit}
    """, qp)


def sc58_critical_expiry_risk(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Critical expiry risk items (RBAC enforced, customizable expiry_risk_levels, limit)"""
    p = params or {}
    _limit = p.get("limit", 100)
    # Allow caller to override which risk levels are considered critical
    risk_levels = tuple(str(v).strip() for v in p.get("expiry_risk_levels", ["Critical", "Already Expired"]))
    if not risk_levels:
        risk_levels = ("Critical", "Already Expired")
    qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    risk_sql = ", ".join(f"'{r}'" for r in risk_levels)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.closing_value,
               sc.days_to_expiry, sc.expiry_risk, sc.primary_action
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.expiry_risk IN ({risk_sql}){df}
        ORDER BY sc.days_to_expiry ASC
        LIMIT {_limit}
    """, qp)


def sc59_expiry_value_at_risk(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total value of items facing Critical / Already Expired risk (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS expiry_risk_count,
               COALESCE(SUM(sc.closing_value), 0) AS expiry_risk_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.expiry_risk IN ('Critical', 'Already Expired'){df}
    """, qp)


def sc61_distributor_expiry_risk(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Distributors with highest expiry-risk stock (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.city,
               COUNT(*) AS critical_expiry_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_expiry_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.expiry_risk IN ('Critical', 'High', 'Already Expired'){df}
        GROUP BY sc.distributor_code, sc.distributor_name, sc.city
        ORDER BY total_expiry_value DESC
        LIMIT {_limit}
    """, qp)


# ==========================================
# Section 7 — Anomaly Detection & Early Warnings
# ==========================================

def sc64_anomaly_distributors(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Distributors flagged as anomalies (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.city,
               COUNT(*) AS flagged_items,
               ROUND(AVG(sc.anomaly_score), 3) AS avg_anomaly_score,
               COALESCE(SUM(sc.closing_value), 0) AS total_flagged_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.early_warning_flag = TRUE{df}
        GROUP BY sc.distributor_code, sc.distributor_name, sc.city
        ORDER BY avg_anomaly_score ASC
        LIMIT {_limit}
    """, qp)


def sc65_fast_items_with_warning(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """FAST-moving items with early warning flag (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value,
               sc.dos, sc.anomaly_score, sc.offtake_trend
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE UPPER(sc.stock_status) = 'FAST' AND sc.early_warning_flag = TRUE{df}
        ORDER BY sc.anomaly_score ASC
        LIMIT {_limit}
    """, qp)


def sc66_severe_anomalies(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Items with anomaly score below max_score (RBAC enforced, customizable max_score, limit)"""
    p = params or {}; _limit = p.get("limit", 50); max_score = float(p.get("max_score", -0.5))
    qp = build_params(userid, p); qp["max_score"] = max_score
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.stock_status, sc.dos,
               sc.anomaly_score, sc.closing_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.anomaly_score < :max_score{df}
        ORDER BY sc.anomaly_score ASC
        LIMIT {_limit}
    """, qp)


# ==========================================
# Section 8 — Advanced Analytical Reasoning
# ==========================================

def sc70_recoverable_slow_items(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """SLOW items with improving trend — RECOVERABLE (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.priority_rank, sc.distributor_name, sc.item_name, sc.category,
               sc.closing_value, sc.dos, sc.offtake_trend, sc.primary_action
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE (sc.stock_health = 'RECOVERABLE_SLOW' OR (UPPER(sc.stock_status) = 'SLOW' AND sc.offtake_trend = 'Improving')){df}
        ORDER BY sc.priority_rank ASC NULLS LAST
        LIMIT {_limit}
    """, qp)


def sc72_transfer_vs_scheme_comparison(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Transfer vs scheme net recovery comparison (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.closing_value,
               sc.xfr_net_recovery_est, sc.est_scheme_net_recovery,
               (sc.xfr_net_recovery_est - sc.est_scheme_net_recovery) AS transfer_advantage
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.xfr_net_recovery_est > 0 AND sc.est_scheme_net_recovery > 0{df}
        ORDER BY transfer_advantage DESC
        LIMIT {_limit}
    """, qp)


def sc75_total_clearance_recovery_potential(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """If I execute all recommended transfers & schemes — % dead stock value recovered? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COALESCE(SUM(CASE WHEN UPPER(sc.stock_status) = 'DEAD' THEN sc.closing_value ELSE 0 END), 0) AS total_dead_stock_value,
               COALESCE(SUM(sc.xfr_net_recovery_est), 0) AS total_transfer_recovery,
               COALESCE(SUM(sc.est_scheme_net_recovery), 0) AS total_scheme_recovery,
               (COALESCE(SUM(sc.xfr_net_recovery_est), 0) + COALESCE(SUM(sc.est_scheme_net_recovery), 0)) AS combined_recovery_est,
               ROUND((COALESCE(SUM(sc.xfr_net_recovery_est), 0) + COALESCE(SUM(sc.est_scheme_net_recovery), 0)) * 100.0 / NULLIF(SUM(CASE WHEN UPPER(sc.stock_status) = 'DEAD' THEN sc.closing_value ELSE 0 END), 0), 2) AS recovery_pct_of_dead_stock
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
    """, qp)


# ==========================================
# Section 9 — Offtake Trend & Velocity
# ==========================================

def sc86_worsening_trend_items(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Which items have a worsening offtake trend? (RBAC enforced, customizable limit)"""
    p = params or {}; _limit = p.get("limit", 50); qp = build_params(userid, p)
    rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.distributor_name, sc.item_name, sc.category, sc.stock_status,
               sc.closing_value, sc.dos, sc.offtake_trend, sc.primary_action
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.offtake_trend = 'Worsening'{df}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


def sc87_improving_trend_count(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """How many items in my territory are showing improving sales velocity? (RBAC enforced, customizable)"""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT COUNT(*) AS improving_items_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_improving_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE sc.offtake_trend = 'Improving'{df}
    """, qp)


def sc90_trend_direction_summary(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Compare worsening vs improving trend count across territory / zone (RBAC enforced, customizable)."""
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    return run_query(f"""
        SELECT sc.offtake_trend,
               COUNT(*) AS item_count,
               COALESCE(SUM(sc.closing_value), 0) AS total_value
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
        GROUP BY sc.offtake_trend
        ORDER BY total_value DESC
    """, qp)


# ==========================================
# Section 10 — National / Executive Summary
# ==========================================

def sc100_executive_summary(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """
    Executive summary of stock clearance situation — runs 3 parallel sub-queries and merges.
    Mirrors the run_parallel pattern from secondary_sales.py for optimized performance.
    RBAC enforced on all sub-queries. Customizable via dynamic filters.
    """
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)

    # Sub-query 1: stock status counts + total value
    q_status = (f"""
        SELECT COUNT(DISTINCT sc.distributor_code) AS total_distributors,
               COALESCE(SUM(sc.closing_value), 0) AS total_stock_value,
               COALESCE(SUM(CASE WHEN UPPER(sc.stock_status) = 'DEAD' THEN sc.closing_value ELSE 0 END), 0) AS dead_stock_value,
               COALESCE(SUM(CASE WHEN UPPER(sc.stock_status) = 'SLOW' THEN sc.closing_value ELSE 0 END), 0) AS slow_stock_value,
               COUNT(DISTINCT sc.item_code) AS total_sku_count
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
    """, qp)

    # Sub-query 2: clearance recovery potentials
    q_recovery = (f"""
        SELECT COALESCE(SUM(CASE WHEN sc.transfer_recommended = TRUE THEN sc.xfr_net_recovery_est ELSE 0 END), 0) AS transfer_recovery_potential,
               COALESCE(SUM(CASE WHEN sc.needs_clearance = TRUE THEN sc.est_scheme_net_recovery ELSE 0 END), 0) AS scheme_recovery_potential,
               COUNT(CASE WHEN sc.transfer_recommended = TRUE THEN 1 END) AS transfer_item_count,
               COUNT(CASE WHEN sc.needs_clearance = TRUE THEN 1 END) AS scheme_item_count
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
    """, qp)

    # Sub-query 3: seasonality + expiry risk signals
    q_risk = (f"""
        SELECT COALESCE(SUM(CASE WHEN sc.seasonality_recommendation = 'HOLD_FOR_SEASON' THEN sc.closing_value ELSE 0 END), 0) AS seasonal_hold_value,
               COUNT(CASE WHEN sc.expiry_risk IN ('Critical', 'Already Expired') THEN 1 END) AS critical_expiry_items,
               COUNT(CASE WHEN sc.early_warning_flag = TRUE THEN 1 END) AS anomaly_flagged_items
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
    """, qp)

    results = run_parallel([q_status, q_recovery, q_risk])
    r_status  = (results[0].get("rows") or [{}])[0]
    r_recovery = (results[1].get("rows") or [{}])[0]
    r_risk    = (results[2].get("rows") or [{}])[0]

    merged = {**r_status, **r_recovery, **r_risk}
    return {"rows": [merged], "columns": list(merged.keys()), "row_count": 1, "error": None}


# ==========================================
# Dynamic & Highly Customizable Generic Flags
# ==========================================

def sc_custom_top(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """
    Highly customizable top/bottom query — mirrors q18_custom_top from secondary_sales.
    Params:
      - group_col: column to group by (e.g. 'category', 'distributor_name', 'stock_status', 'brand', 'zone')
      - metric: column to aggregate (e.g. 'closing_value', 'closing_stock', 'xfr_net_recovery_est')
      - order: 'desc' or 'asc'
      - limit: max rows (optional — omit for all rows)
    """
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    group_col = str(p.get("group_col", "category")).strip().lower()
    if group_col not in _SC_GROUP_COLS:
        group_col = "category"
    metric = str(p.get("metric", "closing_value")).strip().lower()
    if metric not in _SC_METRICS:
        metric = "closing_value"
    order = "DESC" if str(p.get("order", "desc")).upper() != "ASC" else "ASC"
    # Optional limit — mirrors q18_custom_top: only add LIMIT clause when param supplied
    limit_sql = ""
    _limit = p.get("limit")
    if _limit is not None:
        limit_sql = f" LIMIT {int(_limit)}"
    # Extra display columns when grouping by code-type cols — mirrors extra_cols in q18_custom_top
    extra_cols = {
        "distributor_code": "distributor_name",
        "category": "brand",
        "primary_action": "scheme_type",
    }
    extra_sel = f", sc.{extra_cols[group_col]}" if extra_cols.get(group_col) else ""
    extra_gb  = f", sc.{extra_cols[group_col]}" if extra_cols.get(group_col) else ""

    return run_query(f"""
        SELECT sc.{group_col} AS grp{extra_sel},
               SUM(sc.{metric}) AS total,
               COUNT(*) AS item_count
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df}
        GROUP BY sc.{group_col}{extra_gb}
        ORDER BY total {order}{limit_sql}
    """, qp)


def sc_filtered(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """
    Dynamic column filter query — mirrors q19_filtered from secondary_sales exactly.
    Params:
      - filter_col: column to filter (validated against _SC_FILTER_COLS whitelist)
      - filter_val: target value
      - filter_op: 'eq' | 'gt' | 'lt' | 'gte'/'ge' | 'lte'/'le' | 'like'
    """
    p = params or {}; qp = build_params(userid, p); rbac_j = _sc_rbac_join(p); df = _sc_dynamic_filters(p, qp)
    filter_col = str(p.get("filter_col", "")).strip().lower()
    if filter_col and filter_col not in _SC_FILTER_COLS:   # whitelist check — matches q19_filtered
        filter_col = ""
    filter_val = str(p.get("filter_val", "")).strip()
    filter_op  = str(p.get("filter_op", "eq")).strip().lower()

    extra_where = ""
    if filter_col and filter_val:
        if filter_op == "eq":
            extra_where = f"AND LOWER(CAST(sc.{filter_col} AS TEXT)) = LOWER(:filter_val)"
        elif filter_op == "gt":
            extra_where = f"AND CAST(sc.{filter_col} AS NUMERIC) > :filter_val_num"
            qp["filter_val_num"] = filter_val
        elif filter_op == "lt":
            extra_where = f"AND CAST(sc.{filter_col} AS NUMERIC) < :filter_val_num"
            qp["filter_val_num"] = filter_val
        elif filter_op in ("gte", "ge"):
            extra_where = f"AND CAST(sc.{filter_col} AS NUMERIC) >= :filter_val_num"
            qp["filter_val_num"] = filter_val
        elif filter_op in ("lte", "le"):
            extra_where = f"AND CAST(sc.{filter_col} AS NUMERIC) <= :filter_val_num"
            qp["filter_val_num"] = filter_val
        elif filter_op == "like":
            extra_where = f"AND sc.{filter_col} ILIKE :filter_val_pat"
            qp["filter_val_pat"] = f"%{filter_val}%"
        else:  # fallback to eq — matches secondary_sales q19 else branch
            extra_where = f"AND LOWER(CAST(sc.{filter_col} AS TEXT)) = LOWER(:filter_val)"
        if "filter_val" not in qp and filter_op in ("eq",):  # bind key only when needed
            qp["filter_val"] = filter_val
    if filter_op == "eq" and filter_col and filter_val and "filter_val" not in qp:
        qp["filter_val"] = filter_val

    _limit = p.get("limit", 100)
    return run_query(f"""
        SELECT sc.distributor_code, sc.distributor_name, sc.item_code, sc.item_name,
               sc.category, sc.brand, sc.stock_status, sc.stock_health, sc.closing_value,
               sc.primary_action, sc.priority_rank, sc.ageing_days, sc.dos
        FROM ai_output.stock_clearance_recommendations sc
        {rbac_j}
        WHERE 1=1{df} {extra_where}
        ORDER BY sc.closing_value DESC
        LIMIT {_limit}
    """, qp)


# Export flags registry
STOCK_CLEARANCE_FLAGS = {
    # Basic Health
    "sc:dead-count":           (sc1_dead_stock_count, "Dead stock SKU count and distributor count"),
    "sc:dead-value":           (sc2_dead_stock_value, "Total dead stock value and units"),
    "sc:slow-vs-dead":         (sc3_slow_vs_dead, "Slow-moving vs dead stock breakdown"),
    "sc:health-distribution":  (sc4_health_distribution, "Full stock health distribution (CLEARANCE_REQUIRED, OVERSTOCKED, etc.)"),
    "sc:at-risk-pct":          (sc5_at_risk_pct, "Percentage of total stock value at risk"),
    "sc:top-distributor-dead": (sc6_top_distributor_dead_stock, "Distributors with highest dead stock value"),
    "sc:distributors-with-dead": (sc7_distributors_with_dead_stock_count, "Count of distributors having dead stock"),
    "sc:avg-dos":              (sc8_avg_dos, "Average Days of Stock (DOS)"),
    "sc:new-stock":            (sc9_new_stock, "SKUs classified as NEW stock"),
    "sc:overstocked-distributors": (sc10_overstocked_distributors, "Distributors flagged as OVERSTOCKED"),

    # Priority Actions
    "sc:top-priority-actions": (sc13_top_priority_actions, "Top urgent dead stock items to act on today (priority_rank)"),
    "sc:longest-ageing":       (sc14_longest_ageing_items, "Items sitting longest without sale"),
    "sc:clearance-required-high-val": (sc15_clearance_required_high_value, "CLEARANCE_REQUIRED items above high value threshold"),
    "sc:urgent-distributors":  (sc16_urgent_distributors, "Distributors needing immediate attention based on priority rank"),
    "sc:critical-priority-val": (sc17_critical_priority_value, "Total value of Critical priority items (rank <= max_rank)"),
    "sc:ageing-urgent-count":  (sc19_ageing_urgent_count, "Count and value of urgent ageing items"),
    "sc:transfer-vs-scheme-split": (sc20_transfer_vs_scheme_split, "Split of dead stock: transfer vs scheme primary action"),

    # Transfers
    "sc:transfer-recommendations": (sc23_transfer_recommendations, "Recommended stock transfer routes and recovery"),
    "sc:transfer-total-recovery": (sc25_transfer_total_recovery, "Total estimated recovery from recommended transfers"),
    "sc:same-city-transfers":  (sc26_same_city_transfers, "Stock transfer routes within the same city"),
    "sc:transfers-within-50km": (sc27_transfers_within_50km, "Stock transfers within specified radius"),
    "sc:dead-no-transfer":     (sc28_dead_stock_no_transfer, "Dead stock items with no viable transfer route"),
    "sc:logistics-cost":       (sc31_transfer_logistics_cost, "Total estimated logistics cost for transfers"),

    # Schemes
    "sc:scheme-recommendations": (sc36_scheme_recommendations, "Recommended discount schemes for stock clearance"),
    "sc:aggressive-schemes":   (sc37_aggressive_schemes, "Items recommended for aggressive flat discount schemes"),
    "sc:avg-discount-pct":     (sc38_avg_discount_pct, "Average recommended discount percentage"),
    "sc:free-qty-schemes":     (sc39_free_qty_schemes, "Items recommended for Free Qty / Buy-Get schemes"),
    "sc:est-clearance-pct":    (sc40_est_clearance_pct, "Estimated clearance percentage across schemes"),
    "sc:total-scheme-recovery": (sc44_total_scheme_recovery, "Total estimated recovery if all schemes are executed"),

    # Seasonality
    "sc:seasonal-holds":       (sc46_seasonal_holds, "Stock items on HOLD_FOR_SEASON advisory"),
    "sc:peak-season-timeline": (sc47_peak_season_timeline, "Peak season timeline for seasonal hold stock"),
    "sc:seasonal-hold-value":  (sc50_seasonal_hold_value, "Total value of stock on seasonal hold"),
    "sc:high-seasonality":     (sc54_high_seasonality_items, "Extremely seasonal stock items"),

    # Expiry
    "sc:expiring-30-days":     (sc56_expiring_30_days, "Items expiring in the next specified days"),
    "sc:already-expired":      (sc57_already_expired, "Already expired stock items"),
    "sc:critical-expiry-risk": (sc58_critical_expiry_risk, "Critical expiry risk items"),
    "sc:expiry-value-at-risk": (sc59_expiry_value_at_risk, "Total stock value facing critical expiry risk"),
    "sc:distributor-expiry-risk": (sc61_distributor_expiry_risk, "Distributors with highest expiry risk stock"),

    # Anomalies
    "sc:anomaly-distributors": (sc64_anomaly_distributors, "Distributors flagged as statistical anomalies"),
    "sc:fast-with-warning":    (sc65_fast_items_with_warning, "FAST items with early warning flags"),
    "sc:severe-anomalies":     (sc66_severe_anomalies, "Items with severe anomaly scores"),

    # Reasoning
    "sc:recoverable-slow":     (sc70_recoverable_slow_items, "SLOW items showing improving sales velocity"),
    "sc:transfer-vs-scheme-comp": (sc72_transfer_vs_scheme_comparison, "Side-by-side comparison: transfer recovery vs scheme recovery"),
    "sc:total-clearance-potential": (sc75_total_clearance_recovery_potential, "Total clearance recovery potential across transfers and schemes"),

    # Offtake Trends
    "sc:worsening-trend":       (sc86_worsening_trend_items, "Stock items with worsening sales velocity trend"),
    "sc:improving-trend-count": (sc87_improving_trend_count, "Count of stock items with improving sales velocity"),
    "sc:trend-summary":        (sc90_trend_direction_summary, "Overall offtake trend direction summary"),

    # Executive Summary
    "sc:executive-summary":    (sc100_executive_summary, "Executive summary of stock health, clearance, and recovery potential"),

    # Highly Customizable Utilities
    "sc:custom-top":           (sc_custom_top, "Customizable group-by query (group_col, metric, order, limit, filters)"),
    "sc:filtered":             (sc_filtered, "Dynamic column filtering (filter_col, filter_val, filter_op, filters)"),
}
