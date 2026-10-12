"""Combined / God-mode / Group analytics — aggregates across SS, Purchases, Primary, Stock Movement."""
from ..db import run_query, run_parallel, run_monthly_parallel
from ._rbac import rbac_clause, build_params
from .secondary_sales import q1_monthly_total, q7_growth, q15_national
from .purchases import p1_this_month, p3_pending, p9_trend_6m
from .primary_sales import pr1_this_month, pr3_vs_secondary, pr12_trend_6m
from .stock_clearance import sc100_executive_summary, STOCK_CLEARANCE_FLAGS, _sc_rbac_join
from .stock_movement import sm_executive_summary as _sm_exec


def _date_filter(col, params):
    if params.get("date_from") and params.get("date_to"):
        return f"AND {col} >= :date_from AND {col} < CAST(:date_to AS DATE) + INTERVAL '1 day'"
    if params.get("date_from"):
        return f"AND {col} >= :date_from"
    if params.get("date_to"):
        return f"AND {col} <= :date_to"
    return "AND {0} >= DATE_TRUNC('month', CURRENT_DATE) AND {0} < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'".format(col)


def combined_overview(userid, params=None):
    """Run SS + Purchases + Primary + Stock Clearance + Stock Movement overview KPIs in one call."""
    p = params or {}
    ss = q1_monthly_total(userid, p)
    ss_rows = (ss.get("rows") or [{}])[0]
    gr = q7_growth(userid, p)
    gr_rows = (gr.get("rows") or [{}])[0]
    pur = p1_this_month(userid, p)
    pr = pr1_this_month(userid, p)
    pr_rows = (pr.get("rows") or [{}])[0]
    vs = pr3_vs_secondary(userid, p)
    vs_rows = (vs.get("rows") or [{}])[0]
    pend = p3_pending(userid, p)
    sc = sc100_executive_summary(userid, p)
    sc_rows = (sc.get("rows") or [{}])[0]
    sm = _sm_exec(userid, p)
    sm_rows = (sm.get("rows") or [{}])[0]

    rows = [{
        "ss_total": ss_rows.get("total_secondary_sales", 0),
        "ss_invoices": ss_rows.get("invoice_count", 0),
        "ss_growth_pct": gr_rows.get("growth_pct", 0),
        "pur_entries": pur.get("row_count", 0),
        "pur_pending": pend.get("row_count", 0),
        "pr_total": pr_rows.get("total_primary_sales", 0),
        "pr_invoices": pr_rows.get("invoice_count", 0),
        "pr_vs_secondary": vs_rows.get("primary_sales_value", 0),
        "secondary_vs_primary": vs_rows.get("secondary_sales_value", 0),
        "difference": vs_rows.get("difference", 0),
        "sc_dead_stock_value": sc_rows.get("dead_stock_value", 0),
        "sc_slow_stock_value": sc_rows.get("slow_stock_value", 0),
        "sc_transfer_recovery_potential": sc_rows.get("transfer_recovery_potential", 0),
        "sc_scheme_recovery_potential": sc_rows.get("scheme_recovery_potential", 0),
        "sm_inflow_value": sm_rows.get("total_inflow_value", 0),
        "sm_outflow_value": sm_rows.get("total_outflow_value", 0),
    }]
    return {"rows": rows, "columns": list(rows[0].keys()), "row_count": 1, "error": None}


def group_secondary_by_user(userid, params=None):
    """Run any analytics flag across multiple user IDs and merge."""
    p = params or {}
    target_flag = p.get("flag", "ss:monthly-total")
    user_ids = p.get("user_ids", [userid])
    from .secondary_sales import SECONDARY_SALES_FLAGS
    from .purchases import PURCHASES_FLAGS
    from .primary_sales import PRIMARY_SALES_FLAGS
    from .stock_clearance import STOCK_CLEARANCE_FLAGS
    from .stock_movement import STOCK_MOVEMENT_FLAGS
    all_f = {**SECONDARY_SALES_FLAGS, **PURCHASES_FLAGS, **PRIMARY_SALES_FLAGS, **STOCK_CLEARANCE_FLAGS, **STOCK_MOVEMENT_FLAGS}
    fn, desc = all_f.get(target_flag, (None, None))
    if not fn:
        return {"error": f"Unknown flag: {target_flag}", "rows": [], "columns": [], "row_count": 0}
    results = []
    for uid in user_ids:
        r = fn(uid.strip(), p)
        for row in (r.get("rows") or []):
            row["_userid"] = uid.strip()
            results.append(row)
    cols = ["_userid"] + (r.get("columns") or []) if results else []
    return {"rows": results, "columns": cols, "row_count": len(results), "error": None}


def cross_comparison(userid, params=None):
    """Compare secondary, purchase, primary side by side per distributor."""
    p = params or {}
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    rbac = rbac_clause(p)
    qp = build_params(userid, p)

    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COALESCE(ss.ss_value, 0) AS secondary_sales,
               COALESCE(pur.pur_value, 0) AS purchase_value,
               COALESCE(pr.pr_value, 0) AS primary_sales,
               COALESCE(pr.pr_value, 0) - COALESCE(ss.ss_value, 0) AS primary_minus_secondary,
               CASE WHEN COALESCE(ss.ss_value, 0) > 0
                    THEN ROUND(COALESCE(pr.pr_value, 0) / ss.ss_value * 100, 2)
                    ELSE 0 END AS stock_cover_ratio
        FROM (
            SELECT td.distributorid, SUM(td.billed_value) AS ss_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY td.distributorid
        ) ss
        FULL JOIN (
            SELECT td.distributorid, SUM(td.billed_value) AS pur_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_pur}
            GROUP BY td.distributorid
        ) pur ON pur.distributorid=ss.distributorid
        FULL JOIN (
            SELECT si.distributorid, SUM(si.net_amount) AS pr_value
            FROM sale_salesinvoice si
            INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY si.distributorid
        ) pr ON pr.distributorid=COALESCE(ss.distributorid, pur.distributorid)
        JOIN ledgermaster ds ON ds.ledgerid = COALESCE(ss.distributorid, pur.distributorid, pr.distributorid) AND ds.ledgertype = 1
        ORDER BY COALESCE(ss.ss_value, 0) DESC
    """, qp)


def combined_monthly_comparison(userid, params=None):
    """All 3 modules side by side per month."""
    p = params or {}
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)

    return run_query(f"""
        SELECT COALESCE(ss.month, pur.month, pr.month) AS month,
               COALESCE(ss.ss_total, 0) AS secondary_sales,
               COALESCE(pur.pur_total, 0) AS purchases,
               COALESCE(pr.pr_total, 0) AS primary_sales
        FROM (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS ss_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        ) ss FULL JOIN (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS pur_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_pur}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        ) pur ON pur.month=ss.month
        FULL JOIN (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS pr_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        ) pr ON pr.month=COALESCE(ss.month, pur.month)
        ORDER BY month
    """, qp)


def combined_ytd_all(userid, params=None):
    """YTD totals for all 3 modules."""
    p = params or {}.copy()
    from datetime import date
    today = date.today(); fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)
    p_ytd = {**p, "date_from": fy_start.isoformat()}

    rbac = rbac_clause(p_ytd); qp = build_params(userid, p_ytd)
    df_ss = _date_filter("td.vch_date", p_ytd)
    df_pur = _date_filter("td.vch_date", p_ytd)
    df_pr = _date_filter("si.invoicedate", p_ytd)

    return run_query(f"""
        SELECT (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}) AS ytd_secondary,
               (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_pur}) AS ytd_purchases,
               (SELECT SUM(si.net_amount) FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
                WHERE si.iscancelled=FALSE {df_pr}) AS ytd_primary
    """, qp)


def combined_growth_all(userid, params=None):
    """Growth % for all 3 modules side by side (current vs previous period)."""
    p = params or {}.copy()
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)

    prev_sql = " AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AND td.vch_date < DATE_TRUNC('month', CURRENT_DATE)"
    prev_pr_sql = " AND si.invoicedate >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AND si.invoicedate < DATE_TRUNC('month', CURRENT_DATE)"
    if p.get("date_from") and p.get("date_to"):
        from datetime import datetime, timedelta
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d")
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d")
        span = (d_to - d_from).days + 1
        pv_to = d_from; pv_from = d_from - timedelta(days=span)
        prev_sql = f" AND td.vch_date >= '{pv_from.isoformat()}' AND td.vch_date < '{pv_to.isoformat()}'"
        prev_pr_sql = f" AND si.invoicedate >= '{pv_from.isoformat()}' AND si.invoicedate < '{pv_to.isoformat()}'"

    return run_query(f"""
        WITH cur AS (
            SELECT
                (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                 WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}) AS ss,
                (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                 WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_pur}) AS pur,
                (SELECT SUM(si.net_amount) FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
                 WHERE si.iscancelled=FALSE {df_pr}) AS pr
        ), prev AS (
            SELECT
                (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                 WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {prev_sql}) AS ss,
                (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                 WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {prev_sql}) AS pur,
                (SELECT SUM(si.net_amount) FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
                 WHERE si.iscancelled=FALSE {prev_pr_sql}) AS pr
        )
        SELECT cur.ss AS cur_secondary, cur.pur AS cur_purchases, cur.pr AS cur_primary,
               prev.ss AS prev_secondary, prev.pur AS prev_purchases, prev.pr AS prev_primary,
               ROUND((cur.ss - prev.ss) / NULLIF(prev.ss, 0) * 100, 2) AS ss_growth_pct,
               ROUND((cur.pur - prev.pur) / NULLIF(prev.pur, 0) * 100, 2) AS pur_growth_pct,
               ROUND((cur.pr - prev.pr) / NULLIF(prev.pr, 0) * 100, 2) AS pr_growth_pct
        FROM cur, prev
    """, qp)


def combined_offtake_ratio(userid, params=None):
    """Offtake ratio (Secondary/Primary * 100) by month."""
    p = params or {}
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    return run_query(f"""
        SELECT COALESCE(ss.month, pr.month) AS month,
               COALESCE(ss.ss_total, 0) AS secondary_sales,
               COALESCE(pr.pr_total, 0) AS primary_sales,
               CASE WHEN COALESCE(pr.pr_total, 0) > 0
                    THEN ROUND(COALESCE(ss.ss_total, 0) / pr.pr_total * 100, 2)
                    ELSE 0 END AS offtake_pct
        FROM (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS ss_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        ) ss FULL JOIN (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS pr_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        ) pr ON pr.month=ss.month
        ORDER BY month
    """, qp)


def combined_item_comparison(userid, params=None):
    """Top items compared across Secondary and Primary."""
    p = params or {}; _limit = int(p.get("limit", 20))
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    return run_query(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name,
               COALESCE(ss.ss_qty, 0) AS secondary_qty,
               COALESCE(ss.ss_value, 0) AS secondary_value,
               COALESCE(pr.pr_qty, 0) AS primary_qty,
               COALESCE(pr.pr_value, 0) AS primary_value
        FROM (
            SELECT td.itemid, SUM(td.billed_qty) AS ss_qty, SUM(td.billed_value) AS ss_value
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY td.itemid ORDER BY ss_value DESC LIMIT {_limit}
        ) ss FULL JOIN (
            SELECT sid.itemid, SUM(sid.net_amount) AS pr_value, COUNT(*) AS pr_qty
            FROM sale_salesinvoice si
            INNER JOIN sale_salesinvoicedetail sid ON sid.invoiceid = si.invoiceid
            INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY sid.itemid ORDER BY pr_value DESC LIMIT {_limit}
        ) pr ON pr.itemid=ss.itemid
        JOIN itemmaster itm ON itm.itemid = COALESCE(ss.itemid, pr.itemid)
        ORDER BY COALESCE(ss.ss_value, pr.pr_value) DESC LIMIT {_limit}
    """, qp)


def combined_distributor_snapshot(userid, params=None):
    """Single distributor detail across all 3 modules."""
    p = params or {}
    did = str(p.get("distributor_id", "")).strip()
    dname = str(p.get("distributor_name", "")).strip()
    if not did and dname:
        # The router only knows the NAME the user gave — resolve it to the id.
        _lk = run_query(
            "SELECT ledgerid FROM ledgermaster WHERE ledgername ILIKE :dn LIMIT 1",
            {"dn": f"%{dname}%"},
        )
        if _lk.get("rows"):
            did = str(_lk["rows"][0].get("ledgerid"))
    if not did:
        return {"rows": [], "columns": ["metric", "value"], "row_count": 0, "error": "Provide distributor_id or distributor_name"}
    p_did = {**p}
    rbac = rbac_clause(p_did); qp_base = build_params(userid, p_did)
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    qp = {**qp_base, "did": did}
    return run_query(f"""
        SELECT 'Secondary Sales' AS module,
               COALESCE(SUM(td.billed_value), 0) AS total_value,
               COUNT(DISTINCT td.vch_no) AS invoices,
               COALESCE(ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2), 0) AS avg_invoice
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND (CAST(td.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_ss}
        UNION ALL
        SELECT 'Purchases' AS module,
               COALESCE(SUM(td.billed_value), 0), COUNT(DISTINCT td.vch_no),
               COALESCE(ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2), 0)
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND (CAST(td.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_pur}
        UNION ALL
        SELECT 'Primary Sales' AS module,
               COALESCE(SUM(si.net_amount), 0), COUNT(DISTINCT si.invoiceno),
               COALESCE(ROUND(SUM(si.net_amount) / NULLIF(COUNT(DISTINCT si.invoiceno), 0), 2), 0)
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        LEFT JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE AND (CAST(si.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_pr}
    """, qp)


def combined_item_cross_ref(userid, params=None):
    """Items with big gap between primary and secondary."""
    p = params or {}; _limit = int(p.get("limit", 50))
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    return run_query(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name,
               COALESCE(ss.ss_value, 0) AS secondary_value, COALESCE(ss.ss_qty, 0) AS secondary_qty,
               COALESCE(pr.pr_value, 0) AS primary_value,
               CASE WHEN COALESCE(pr.pr_value, 0) > 0
                    THEN ROUND(COALESCE(ss.ss_value, 0) / pr.pr_value * 100, 2) ELSE 0 END AS offtake_pct,
               COALESCE(pr.pr_value, 0) - COALESCE(ss.ss_value, 0) AS gap_value
        FROM (
            SELECT td.itemid, SUM(td.billed_value) AS ss_value, SUM(td.billed_qty) AS ss_qty
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY td.itemid
        ) ss FULL JOIN (
            SELECT sid.itemid, SUM(sid.net_amount) AS pr_value
            FROM sale_salesinvoice si
            INNER JOIN sale_salesinvoicedetail sid ON sid.invoiceid = si.invoiceid
            INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY sid.itemid
        ) pr ON pr.itemid=ss.itemid
        JOIN itemmaster itm ON itm.itemid = COALESCE(ss.itemid, pr.itemid)
        ORDER BY gap_value DESC LIMIT {_limit}
    """, qp)


def combined_distributor_deep(userid, params=None):
    """Deep dive: single distributor across all modules with growth."""
    p = params or {}
    did = str(p.get("distributor_id", "")).strip()
    dname = str(p.get("distributor_name", "")).strip()
    if not did and dname:
        # The router only knows the NAME the user gave — resolve it to the id.
        _lk = run_query(
            "SELECT ledgerid FROM ledgermaster WHERE ledgername ILIKE :dn LIMIT 1",
            {"dn": f"%{dname}%"},
        )
        if _lk.get("rows"):
            did = str(_lk["rows"][0].get("ledgerid"))
    if not did:
        return {"rows": [], "columns": ["metric", "value"], "row_count": 0, "error": "Provide distributor_id or distributor_name"}
    rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    qp = {**qp_base, "did": did}
    return run_query(f"""
        WITH ss AS (
            SELECT 'Secondary Sales' AS module,
                   COALESCE(SUM(td.billed_value), 0) AS total,
                   COUNT(DISTINCT td.vch_no) AS invoices,
                   COUNT(DISTINCT td.dealerid) AS dealer_count,
                   COUNT(DISTINCT td.itemid) AS item_count
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            LEFT JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND (CAST(td.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_ss}
        ), pur AS (
            SELECT 'Purchases' AS module,
                   COALESCE(SUM(td.billed_value), 0) AS total,
                   COUNT(DISTINCT td.vch_no) AS invoices,
                   0 AS dealer_count,
                   COUNT(DISTINCT td.itemid) AS item_count
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            LEFT JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND (CAST(td.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_pur}
        ), pr AS (
            SELECT 'Primary Sales' AS module,
                   COALESCE(SUM(si.net_amount), 0) AS total,
                   COUNT(DISTINCT si.invoiceno) AS invoices,
                   0 AS dealer_count,
                   COUNT(DISTINCT sid.itemid) AS item_count
            FROM sale_salesinvoice si
            INNER JOIN sale_salesinvoicedetail sid ON sid.invoiceid = si.invoiceid
            INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            LEFT JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
            WHERE si.iscancelled=FALSE AND (CAST(si.distributorid AS TEXT)=:did OR ds.ledgercode=:did) {df_pr}
        )
        SELECT module, total, invoices, dealer_count, item_count FROM ss
        UNION ALL SELECT module, total, invoices, dealer_count, item_count FROM pur
        UNION ALL SELECT module, total, invoices, dealer_count, item_count FROM pr
    """, qp)


def combined_module_breakdown(userid, params=None):
    """% share of total business that each module represents."""
    p = params or {}
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pur = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    return run_query(f"""
        SELECT 'Secondary Sales' AS module,
               (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}) AS total
        UNION ALL SELECT 'Purchases',
               (SELECT SUM(td.billed_value) FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
                WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_pur})
        UNION ALL SELECT 'Primary Sales',
               (SELECT SUM(si.net_amount) FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
                WHERE si.iscancelled=FALSE {df_pr})
    """, qp)


def combined_gap_trend(userid, params=None):
    """Primary vs secondary gap trend by month."""
    p = params or {}
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    df_pr = _date_filter("si.invoicedate", p)
    return run_query(f"""
        SELECT COALESCE(ss.month, pr.month) AS month,
               COALESCE(ss.ss_total, 0) AS secondary_sales,
               COALESCE(pr.pr_total, 0) AS primary_sales,
               COALESCE(pr.pr_total, 0) - COALESCE(ss.ss_total, 0) AS gap,
               CASE WHEN COALESCE(pr.pr_total, 0) > 0
                    THEN ROUND(COALESCE(ss.ss_total, 0) / pr.pr_total * 100, 2) ELSE 0 END AS offtake_pct
        FROM (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS ss_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        ) ss FULL JOIN (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS pr_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_pr}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        ) pr ON pr.month=ss.month
        ORDER BY month
    """, qp)


def combined_seasonality(userid, params=None):
    """Monthly pattern averaged across years."""
    p = params or {}
    rbac = rbac_clause(p); qp = build_params(userid, p)
    df_ss = _date_filter("td.vch_date", p)
    return run_query(f"""
        SELECT EXTRACT(MONTH FROM td.vch_date) AS month_num,
               to_char(td.vch_date, 'Month') AS month_name,
               ROUND(AVG(td.billed_value), 2) AS avg_value,
               COUNT(DISTINCT EXTRACT(YEAR FROM td.vch_date)) AS years_count
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
        GROUP BY EXTRACT(MONTH FROM td.vch_date), to_char(td.vch_date, 'Month')
        ORDER BY month_num
    """, qp)


def combined_stock_health_vs_sales(userid, params=None):
    """Side-by-side analysis of distributor secondary sales vs dead/slow stock value (RBAC enforced)."""
    p = params or {}
    df_ss = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p)
    rbac_j_sc = _sc_rbac_join(p)
    qp = build_params(userid, p)
    _limit = p.get("limit", 50)

    return run_query(f"""
        WITH sales AS (
            SELECT td.distributorid, SUM(td.billed_value) AS secondary_sales_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_ss}
            GROUP BY td.distributorid
        ), stock AS (
            SELECT COALESCE(sc.distributor_ledger_id, lm.ledgerid) AS distributorid,
                   sc.distributor_name,
                   COALESCE(SUM(CASE WHEN UPPER(sc.stock_status) = 'DEAD' THEN sc.closing_value ELSE 0 END), 0) AS dead_stock_value,
                   COALESCE(SUM(CASE WHEN UPPER(sc.stock_status) = 'SLOW' THEN sc.closing_value ELSE 0 END), 0) AS slow_stock_value,
                   COALESCE(SUM(sc.xfr_net_recovery_est), 0) AS transfer_recovery_potential,
                   COALESCE(SUM(sc.est_scheme_net_recovery), 0) AS scheme_recovery_potential
            FROM ai_output.stock_clearance_recommendations sc
            {rbac_j_sc}
            GROUP BY COALESCE(sc.distributor_ledger_id, lm.ledgerid), sc.distributor_name
        )
        SELECT COALESCE(st.distributor_name, CAST(s.distributorid AS TEXT)) AS distributor_name,
               COALESCE(s.secondary_sales_value, 0) AS secondary_sales_value,
               COALESCE(st.dead_stock_value, 0) AS dead_stock_value,
               COALESCE(st.slow_stock_value, 0) AS slow_stock_value,
               COALESCE(st.transfer_recovery_potential, 0) AS transfer_recovery_potential,
               COALESCE(st.scheme_recovery_potential, 0) AS scheme_recovery_potential,
               ROUND(
                   COALESCE(st.dead_stock_value, 0) * 100.0 / NULLIF(s.secondary_sales_value, 0), 2
               ) AS dead_stock_to_sales_pct
        FROM stock st
        FULL JOIN sales s ON s.distributorid = st.distributorid
        ORDER BY dead_stock_value DESC
        LIMIT {_limit}
    """, qp)


def combined_stock_movement_vs_sales(userid, params=None):
    """Compare Stock Inflow/Outflow vs Secondary Sales per distributor (RBAC enforced)."""
    p = params or {}
    qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    uid_safe = str(userid).replace('-', '_')
    tbl = f"tbl_stock_movement_item_wise_report_ai_{uid_safe}"

    return run_query(f"""
        SELECT "ds_code", "ds_name",
               SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note") AS inflow_value,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS outflow_value,
               SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note") AS secondary_sales_value,
               (SUM("Purchase without Receipt Note") + SUM("Purchase with Receipt Note")) -
               (SUM("Sales without Delivery Note") + SUM("Sales with Delivery Note")) AS net_stock_accumulation
        FROM {tbl}
        GROUP BY "ds_code", "ds_name"
        ORDER BY net_stock_accumulation DESC
        {limit_clause}
    """, qp)


def combined_clearance_impact(userid, params=None):
    """Complete cross-module financial overview: Primary + Secondary + Purchases + Stock Clearance Recovery (RBAC enforced)."""
    p = params or {}
    overview = combined_overview(userid, p)
    return overview


COMBINED_FLAGS = {
    "combined:overview":              (combined_overview,              "Combined SS + Purchases + Primary + Stock Clearance + Stock Movement overview KPIs"),
    "combined:cross-compare":         (cross_comparison,               "Cross-comparison per distributor across all modules"),
    "combined:group-by-user":         (group_secondary_by_user,        "Run any flag across multiple user IDs [Group Analytics]"),
    "combined:monthly-comparison":    (combined_monthly_comparison,    "All modules side by side per month"),
    "combined:ytd-all":               (combined_ytd_all,               "Year-to-date total for Secondary + Purchases + Primary"),
    "combined:growth-all":            (combined_growth_all,            "Growth percentage for all modules collectively"),
    "combined:offtake-ratio":         (combined_offtake_ratio,         "Offtake % (Secondary/Primary ratio) by month"),
    "combined:item-comparison":       (combined_item_comparison,       "Top items comparison across Secondary and Primary side by side"),
    "combined:distributor-snapshot":   (combined_distributor_snapshot,   "Single distributor detail across all modules"),
    "combined:item-cross-ref":        (combined_item_cross_ref,        "Items with biggest gap between primary and secondary sales"),
    "combined:distributor-deep":      (combined_distributor_deep,      "Deep distributor dive across modules"),
    "combined:module-breakdown":      (combined_module_breakdown,      "% share breakdown of each module"),
    "combined:gap-trend":              (combined_gap_trend,              "Primary vs secondary sales gap trend by month"),
    "combined:seasonality":            (combined_seasonality,            "Seasonal pattern — average monthly sales across years"),
    "combined:stock-vs-sales":        (combined_stock_health_vs_sales, "Distributor dead stock vs secondary sales velocity & recovery pct"),
    "combined:stock-movement-vs-sales":(combined_stock_movement_vs_sales, "Distributor stock inflow/outflow vs secondary sales velocity"),
    "combined:clearance-impact":      (combined_clearance_impact,      "Complete cross-module overview including stock clearance recovery potentials"),
}

