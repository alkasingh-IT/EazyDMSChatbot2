"""
DMS Claims Analytics Module.
Covers distributor debit/credit notes, scheme shortfall, damaged goods, rate differences, and claim aging.
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


def _clm_filters(params: dict) -> str:
    clauses = []
    if params.get("distributor_id"):
        clauses.append("AND cm.distributorid = :distributor_id")
    if params.get("claim_type"):
        clauses.append("AND cm.claim_type = :claim_type")
    if params.get("status"):
        clauses.append("AND LOWER(cm.status) = LOWER(:status)")
    return " ".join(clauses)


def clm_pending(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Show pending claims for my distributor/team."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    cf = _clm_filters(p)
    return run_query(f"""
        SELECT cm.claim_id, cm.claim_no, cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name, cm.claim_type,
               cm.claim_amount, cm.claim_date, cm.status
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE LOWER(cm.status) IN ('pending', 'submitted', 'under_review') {cf}
        ORDER BY cm.claim_date DESC {limit_clause}
    """, qp)


def clm_status(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Status of specific claim by ID or Claim Number."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    claim_no = p.get("claim_id") or p.get("claim_no") or ""
    qp["claim_no"] = str(claim_no).strip()
    return run_query(f"""
        SELECT cm.claim_id, cm.claim_no, cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name, cm.claim_type,
               cm.claim_amount, cm.approved_amount, cm.status, cm.claim_date, cm.approved_date, cm.remarks
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE cm.claim_no = :claim_no OR CAST(cm.claim_id AS VARCHAR) = :claim_no
    """, qp)


def clm_approved_this_month(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Approved claims for this month."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("cm.approved_date", p)
    cf = _clm_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT cm.claim_id, cm.claim_no, cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name, cm.claim_type,
               cm.claim_amount, cm.approved_amount, cm.approved_date
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE LOWER(cm.status) = 'approved' {df} {cf}
        ORDER BY cm.approved_date DESC {limit_clause}
    """, qp)


def clm_outstanding_value(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Total value of outstanding/pending claims."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    cf = _clm_filters(p)
    return run_query(f"""
        SELECT cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name,
               COUNT(cm.claim_id) AS pending_claims_count,
               SUM(cm.claim_amount) AS total_pending_amount
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE LOWER(cm.status) IN ('pending', 'submitted', 'under_review') {cf}
        GROUP BY cm.ds_code, ds.ledgername
        ORDER BY total_pending_amount DESC
    """, qp)


def clm_rejected(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Rejected claims and reasons."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("cm.claim_date", p)
    cf = _clm_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT cm.claim_id, cm.claim_no, cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name, cm.claim_type,
               cm.claim_amount, cm.rejection_reason, cm.claim_date
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE LOWER(cm.status) IN ('rejected', 'declined') {df} {cf}
        ORDER BY cm.claim_date DESC {limit_clause}
    """, qp)


def clm_avg_approval_time(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Average time (days) taken for claims to get approved."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    cf = _clm_filters(p)
    return run_query(f"""
        SELECT cm.claim_type,
               COUNT(cm.claim_id) AS approved_count,
               ROUND(CAST(AVG(cm.approved_date - cm.claim_date) AS NUMERIC), 1) AS avg_approval_days
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        WHERE LOWER(cm.status) = 'approved' AND cm.approved_date IS NOT NULL {cf}
        GROUP BY cm.claim_type
        ORDER BY avg_approval_days DESC
    """, qp)


def clm_aging_report(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Claim aging report (0-30 days, 31-60 days, 60+ days) [RSM+]."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    cf = _clm_filters(p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        SELECT cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name,
               SUM(CASE WHEN (CURRENT_DATE - cm.claim_date) <= 30 THEN cm.claim_amount ELSE 0 END) AS aging_0_30,
               SUM(CASE WHEN (CURRENT_DATE - cm.claim_date) BETWEEN 31 AND 60 THEN cm.claim_amount ELSE 0 END) AS aging_31_60,
               SUM(CASE WHEN (CURRENT_DATE - cm.claim_date) > 60 THEN cm.claim_amount ELSE 0 END) AS aging_60_plus,
               SUM(cm.claim_amount) AS total_pending_amount
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE LOWER(cm.status) IN ('pending', 'submitted', 'under_review') {cf}
        GROUP BY cm.ds_code, ds.ledgername
        ORDER BY total_pending_amount DESC {limit_clause}
    """, qp)


def clm_rejection_rate(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Claim rejection rate percentage by distributor/territory [ZSM+]."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    cf = _clm_filters(p)
    return run_query(f"""
        SELECT cm.ds_code, COALESCE(ds.ledgername, cm.ds_code) AS ds_name,
               COUNT(cm.claim_id) AS total_claims,
               COUNT(CASE WHEN LOWER(cm.status) IN ('rejected', 'declined') THEN 1 END) AS rejected_claims,
               ROUND(CAST(COUNT(CASE WHEN LOWER(cm.status) IN ('rejected', 'declined') THEN 1 END) * 100.0 / NULLIF(COUNT(cm.claim_id), 0) AS NUMERIC), 2) AS rejection_rate_pct
        FROM claim_master cm
        INNER JOIN ({rbac}) accd ON accd.locationid = cm.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = cm.distributorid AND ds.ledgertype = 1
        WHERE 1=1 {cf}
        GROUP BY cm.ds_code, ds.ledgername
        ORDER BY rejection_rate_pct DESC
    """, qp)


CLAIMS_FLAGS = {
    "clm:pending":             (clm_pending,             "Show pending claims for my distributor/team"),
    "clm:status":              (clm_status,              "Status of specific claim by ID or Claim Number"),
    "clm:approved-this-month": (clm_approved_this_month, "Approved claims for this month"),
    "clm:outstanding-value":    (clm_outstanding_value,    "Total value of outstanding/pending claims"),
    "clm:rejected":             (clm_rejected,             "Rejected claims and reasons"),
    "clm:avg-approval-time":    (clm_avg_approval_time,    "Average time (days) taken for claims to get approved"),
    "clm:aging-report":         (clm_aging_report,         "Claim aging report (0-30, 31-60, 60+ days) [RSM+]"),
    "clm:rejection-rate":       (clm_rejection_rate,       "Claim rejection rate percentage by distributor/territory [ZSM+]"),
}

