"""DMS Primary Sales Analytics — PR1 to PR12 — god-mode aware."""
from ..db import run_query, run_parallel, run_monthly_parallel
from ._rbac import rbac_clause, build_params



def _date_filter(col, params):
    if params.get("date_from") and params.get("date_to"):
        return f"AND {col} >= :date_from AND {col} < CAST(:date_to AS DATE) + INTERVAL '1 day'"
    if params.get("date_from"):
        return f"AND {col} >= :date_from"
    if params.get("date_to"):
        return f"AND {col} <= :date_to"
    return "AND {0} >= DATE_TRUNC('month', CURRENT_DATE) AND {0} < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'".format(col)


def pr1_this_month(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.invoiceno) AS invoice_count
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr2_last_30d(userid, params=None):
    p = params or {}; _limit = p.get("limit", 100); rbac = rbac_clause(p)
    qp = build_params(userid, p)
    where = "si.iscancelled=FALSE"
    if p.get("date_from") or p.get("date_to"):
        where += " " + _date_filter("si.invoicedate", p)
    else:
        where += " AND si.invoicedate >= CURRENT_DATE - INTERVAL '30 days'"
    return run_query(f"""
        SELECT si.invoiceid, si.invoiceno, si.invoicedate, ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               si.net_amount, si.gross_amount, si.discount_amount, si.isauthorized
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE {where}
        ORDER BY si.invoicedate DESC LIMIT {_limit}
    """, qp)


def pr3_vs_secondary(userid, params=None):
    p = params or {}; df_prim = _date_filter("si.invoicedate", p); df_sec = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT COALESCE(si_agg.primary_sales_value,0) AS primary_sales_value,
               COALESCE(td_agg.secondary_sales_value,0) AS secondary_sales_value,
               COALESCE(si_agg.primary_sales_value,0) - COALESCE(td_agg.secondary_sales_value,0) AS difference
        FROM (
          SELECT SUM(si.net_amount) AS primary_sales_value
          FROM sale_salesinvoice si
          INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
          WHERE si.iscancelled=FALSE {df_prim}
        ) si_agg,
        (
          SELECT SUM(td.billed_value) AS secondary_sales_value
          FROM transactiondetail td
          INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
          WHERE LOWER(td.trn_type)='sales'
            AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_sec}
        ) td_agg
    """, qp)


def pr4_by_sku(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name, SUM(td.billed_qty) AS total_qty,
               SUM(td.billed_value) AS total_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type) IN ('receipt','primary','purchase')
          AND td.iscancelled IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription ORDER BY total_value DESC LIMIT {_limit}
    """, qp)


def pr5_top_products_quarter(userid, params=None):
    p = params or {}; _limit = p.get("limit", 10); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name, SUM(td.billed_qty) AS total_qty,
               SUM(td.billed_value) AS total_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type) IN ('receipt','primary','purchase')
          AND td.iscancelled IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription ORDER BY total_value DESC LIMIT {_limit}
    """, qp)


def pr6_ratio(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); df_sec = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, si_agg.primary_value, td_agg.secondary_value,
               ROUND(td_agg.secondary_value / NULLIF(si_agg.primary_value,0)*100,2) AS offtake_ratio_pct
        FROM (
          SELECT si.distributorid, SUM(si.net_amount) AS primary_value
          FROM sale_salesinvoice si
          INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
          WHERE si.iscancelled=FALSE {df}
          GROUP BY si.distributorid
        ) si_agg
        JOIN ledgermaster ds ON ds.ledgerid = si_agg.distributorid AND ds.ledgertype = 1
        LEFT JOIN (
          SELECT td.distributorid, SUM(td.billed_value) AS secondary_value
          FROM transactiondetail td
          INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
          WHERE LOWER(td.trn_type)='sales'
            AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_sec}
          GROUP BY td.distributorid
        ) td_agg ON td_agg.distributorid=si_agg.distributorid
    """, qp)


def pr7_by_distributor(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("si.invoicedate", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.invoiceno) AS invoice_count
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total_primary_sales DESC LIMIT {_limit}
    """, qp)


def pr8_top_distributor(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total_primary_value
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total_primary_value DESC LIMIT 1
    """, qp)


def pr9_region_total(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.distributorid) AS distributor_count,
               COUNT(DISTINCT si.invoiceno) AS invoice_count
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr10_zone_by_distributor(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("si.invoicedate", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, z2.zonename AS ds_zone,
               SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.invoiceno) AS invoice_count
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername, z2.zonename ORDER BY total_primary_sales DESC LIMIT {_limit}
    """, qp)


def pr11_national(userid, params=None):
    p = params or {}; fy_start = p.get("fy_start", "2025-04-01"); rbac = rbac_clause(p)
    qp = build_params(userid, p); qp["fy_start"] = fy_start
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, z2.zonename AS ds_zone,
               SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.invoiceno) AS invoice_count
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE si.iscancelled=FALSE
          AND si.invoicedate >= CAST(:fy_start AS DATE)
          AND si.invoicedate <  CAST(:fy_start AS DATE) + INTERVAL '1 year'
        GROUP BY ds.ledgercode, ds.ledgername, z2.zonename ORDER BY total_primary_sales DESC
    """, qp)


def pr12_trend_6m(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("si.invoicedate", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT DATE_TRUNC('month',si.invoicedate) AS invoice_month, SUM(si.net_amount) AS total_primary_sales,
                   COUNT(DISTINCT si.invoiceno) AS invoice_count
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month',si.invoicedate) ORDER BY invoice_month
        """, qp_base)
    from datetime import datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    queries = []; month_starts = []; cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        qp = {**qp_base, "ms": cursor.isoformat(), "me": m_end.isoformat()}
        queries.append((f"""
            SELECT SUM(si.net_amount) AS total_primary_sales, COUNT(DISTINCT si.invoiceno) AS invoice_count
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE AND si.invoicedate >= :ms AND si.invoicedate < :me
        """, qp))
        month_starts.append(cursor)
        cursor = m_end
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"invoice_month": month_starts[i].isoformat()[:7],
                         "total_primary_sales": res["rows"][0].get("total_primary_sales", 0),
                         "invoice_count": res["rows"][0].get("invoice_count", 0)})
    return {"rows": rows, "columns": ["invoice_month", "total_primary_sales", "invoice_count"], "row_count": len(rows), "error": None}


def pr14_compare_periods(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    if p.get("date_from") and p.get("date_to"):
        from datetime import datetime, timedelta
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        prev_to = d_from; prev_from = d_from - timedelta(days=span)
        qp["prev_from"] = prev_from.isoformat(); qp["prev_to"] = prev_to.isoformat()
        df = _date_filter("si.invoicedate", p)
        df_prev = "AND si.invoicedate >= :prev_from AND si.invoicedate < :prev_to"
    else:
        df = "AND si.invoicedate >= DATE_TRUNC('month',CURRENT_DATE) AND si.invoicedate < DATE_TRUNC('month',CURRENT_DATE) + INTERVAL '1 month'"
        df_prev = "AND si.invoicedate >= DATE_TRUNC('month',CURRENT_DATE) - INTERVAL '1 month' AND si.invoicedate < DATE_TRUNC('month',CURRENT_DATE)"
    return run_query(f"""
        WITH current AS (
            SELECT SUM(si.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
        ), previous AS (
            SELECT SUM(si.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df_prev}
        )
        SELECT cm.total AS current_total, cm.invoices AS current_invoices,
               lm.total AS previous_total, lm.invoices AS previous_invoices,
               ROUND((cm.total - lm.total) / NULLIF(lm.total, 0) * 100, 2) AS change_pct
        FROM current cm, previous lm
    """, qp)


_PR_GROUP_COLS = {
    "distributorid", "partyid", "ds_code", "ds_name", "distributor_name",
    "ds_city", "ds_state", "ds_zone"
}
_PR_METRICS = {"net_amount", "gross_amount"}
_PR_FILTER_COLS = _PR_GROUP_COLS | {"isauthorized"}


def pr15_custom_top(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    group_col = str(p.get("group_col", "ds_name")).strip()
    if group_col not in _PR_GROUP_COLS: group_col = "ds_name"
    metric = str(p.get("metric", "net_amount")).strip()
    if metric not in _PR_METRICS: metric = "net_amount"
    order = "DESC" if str(p.get("order", "desc")).upper() != "ASC" else "ASC"
    limit_sql = ""
    _limit = p.get("limit")
    if _limit is not None:
        _limit = max(1, int(_limit))
        limit_sql = f" LIMIT {_limit}"

    if group_col in ("ds_name", "distributor_name"):
        grp_expr = "ds.ledgername"; extra_sel = ", ds.ledgercode AS ds_code"; extra_gb = ", ds.ledgercode"
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1"
    elif group_col in ("ds_code", "distributorid"):
        grp_expr = "ds.ledgercode"; extra_sel = ", ds.ledgername AS ds_name"; extra_gb = ", ds.ledgername"
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1"
    elif group_col in ("ds_city", "city"):
        grp_expr = "c2.cityname"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1 LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid"
    elif group_col in ("ds_state", "state"):
        grp_expr = "s2.statename"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1 LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid LEFT JOIN statemaster s2 ON s2.stateid = c2.stateid"
    elif group_col in ("ds_zone", "zone"):
        grp_expr = "z2.zonename"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1 LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid"
    else:
        grp_expr = f"si.{group_col}"; extra_sel = ""; extra_gb = ""; join_sql = ""

    return run_query(f"""
        SELECT {grp_expr} AS grp{extra_sel}, SUM(si.{metric}) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        {join_sql}
        WHERE si.iscancelled=FALSE {df}
        GROUP BY {grp_expr}{extra_gb} ORDER BY total {order}{limit_sql}
    """, qp)


def pr16_filtered(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    filter_col = str(p.get("filter_col", "")).strip()
    if filter_col and filter_col not in _PR_FILTER_COLS: filter_col = ""
    filter_val = str(p.get("filter_val", "")).strip()
    filter_op = str(p.get("filter_op", "eq")).strip()
    extra_where = ""
    if filter_col and filter_val:
        if filter_col == "isauthorized":
            extra_where = f'AND si.isauthorized = :filter_val_isauth'
            qp["filter_val_isauth"] = filter_val.lower() in ("true","1","yes")
        elif filter_op == "eq":
            extra_where = f'AND LOWER(CAST(si.{filter_col} AS TEXT)) = LOWER(:filter_val)'
            qp["filter_val"] = filter_val
        elif filter_op in ("gt","lt","gte","lte","ge","le"):
            opmap = {"gt":">","lt":"<","gte":">=","ge":">=","lte":"<=","le":"<="}
            extra_where = f'AND CAST(si.{filter_col} AS NUMERIC) {opmap.get(filter_op, "=")} :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op == "like":
            extra_where = f"AND CAST(si.{filter_col} AS TEXT) ILIKE :filter_val_pat"
            qp["filter_val_pat"] = f"%{filter_val}%"
    return run_query(f"""
        SELECT SUM(si.net_amount) AS total_value, COUNT(DISTINCT si.invoiceno) AS invoice_count,
               COUNT(DISTINCT si.distributorid) AS distributor_count
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df} {extra_where}
    """, qp)


def pr13_monthly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("si.invoicedate", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT DATE_TRUNC('month',si.invoicedate) AS month, SUM(si.net_amount) AS total_primary_sales
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month',si.invoicedate) ORDER BY month
        """, qp_base)
    from datetime import datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    queries = []; month_starts = []; cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        qp = {**qp_base, "ms": cursor.isoformat(), "me": m_end.isoformat()}
        queries.append((f"""
            SELECT SUM(si.net_amount) AS total_primary_sales
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE AND si.invoicedate >= :ms AND si.invoicedate < :me
        """, qp))
        month_starts.append(cursor)
        cursor = m_end
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"month": month_starts[i].isoformat()[:7], "total_primary_sales": res["rows"][0].get("total_primary_sales", 0)})
    return {"rows": rows, "columns": ["month", "total_primary_sales"], "row_count": len(rows), "error": None}


def pr17_fast_total(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT SUM(si.net_amount) AS total_primary_sales
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr18_distributor_monthly(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    _limit = int(p.get("limit", 50))
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, DATE_TRUNC('month',si.invoicedate) AS month,
               SUM(si.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
        FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername, DATE_TRUNC('month',si.invoicedate)
        ORDER BY ds.ledgername, month
    """, qp)


def pr19_year_to_date(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    from datetime import date
    today = date.today(); fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)
    qp["fy_start"] = fy_start.isoformat()
    df = _date_filter("si.invoicedate", {**p, "date_from": fy_start.isoformat()})
    return run_query(f"""
        SELECT SUM(si.net_amount) AS ytd_primary_sales, COUNT(DISTINCT si.invoiceno) AS ytd_invoices
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr20_quarterly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("si.invoicedate", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT EXTRACT(YEAR FROM si.invoicedate)::text || '-Q' || CEIL(EXTRACT(MONTH FROM si.invoicedate)/3.0)::text AS quarter,
                   SUM(si.net_amount) AS total_primary_sales
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY EXTRACT(YEAR FROM si.invoicedate), CEIL(EXTRACT(MONTH FROM si.invoicedate)/3.0)
            ORDER BY quarter
        """, qp_base)
    from datetime import date, datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    q_starts = []; queries = []; cursor = d_from
    while cursor <= d_to:
        q_start = date(cursor.year, ((cursor.month - 1) // 3) * 3 + 1, 1)
        q_end = (q_start.replace(month=q_start.month + 3) - timedelta(days=1)) if q_start.month + 3 <= 12 else date(q_start.year + 1, 1, 1) - timedelta(days=1)
        if q_end > d_to: q_end = d_to
        lab = f"{q_start.year}-Q{(q_start.month-1)//3+1}"
        if lab in [l for l,_,_ in q_starts]: break
        qp = {**qp_base, "qs": q_start.isoformat(), "qe": (q_end + timedelta(days=1)).isoformat()}
        queries.append((f"""
            SELECT SUM(si.net_amount) AS total_primary_sales
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE AND si.invoicedate >= :qs AND si.invoicedate < :qe
        """, qp))
        q_starts.append((lab, q_start, q_end))
        cursor = q_end + timedelta(days=1)
    from ..db import run_parallel
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"quarter": q_starts[i][0], "total_primary_sales": res["rows"][0].get("total_primary_sales", 0)})
    return {"rows": rows, "columns": ["quarter", "total_primary_sales"], "row_count": len(rows), "error": None}


def pr21_avg_invoice(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT SUM(si.net_amount) AS total_primary_sales, COUNT(DISTINCT si.invoiceno) AS invoice_count,
               ROUND(SUM(si.net_amount) / NULLIF(COUNT(DISTINCT si.invoiceno), 0), 2) AS avg_invoice_value
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr22_cumulative_monthly(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS month_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, month_total,
               ROUND(SUM(month_total) OVER (ORDER BY month), 2) AS cumulative_total
        FROM monthly ORDER BY month
    """, qp)


def pr23_returns(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("si.invoicedate", p)
    df2 = _date_filter("si2.invoicedate", p)
    return run_query(f"""
        SELECT COUNT(DISTINCT si.invoiceno) AS return_invoices,
               SUM(ABS(si.net_amount)) AS return_value,
               ROUND(SUM(ABS(si.net_amount)) * 100.0 / NULLIF((SELECT SUM(si2.net_amount) FROM sale_salesinvoice si2
                   INNER JOIN ({rbac}) accd2 ON accd2.locationid=si2.distributorid WHERE si2.iscancelled=FALSE {df2}), 0), 2) AS return_pct
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE AND si.net_amount < 0 {df}
    """, qp)


def pr24_growth_monthly(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total) OVER (ORDER BY m.month) AS prev_month,
               ROUND((m.total - LAG(m.total) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total) OVER (ORDER BY m.month), 0) * 100, 2) AS growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


def pr25_party_monthly(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS party_name, DATE_TRUNC('month', si.invoicedate) AS month,
               SUM(si.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername, DATE_TRUNC('month', si.invoicedate)
        ORDER BY ds.ledgername, month
    """, qp)


def pr26_invoice_range(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT CASE
            WHEN si.net_amount < 100000 THEN 'Below 1L'
            WHEN si.net_amount < 500000 THEN '1L-5L'
            WHEN si.net_amount < 1000000 THEN '5L-10L'
            WHEN si.net_amount < 5000000 THEN '10L-50L'
            ELSE '50L+'
        END AS invoice_range,
        COUNT(DISTINCT si.invoiceno) AS invoices,
        SUM(si.net_amount) AS total_value
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY CASE
            WHEN si.net_amount < 100000 THEN 'Below 1L'
            WHEN si.net_amount < 500000 THEN '1L-5L'
            WHEN si.net_amount < 1000000 THEN '5L-10L'
            WHEN si.net_amount < 5000000 THEN '10L-50L'
            ELSE '50L+'
        END ORDER BY MIN(si.net_amount)
    """, qp)


def pr27_weekday_analysis(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT to_char(si.invoicedate, 'Day') AS weekday,
               EXTRACT(DOW FROM si.invoicedate) AS dow,
               COUNT(DISTINCT si.invoiceno) AS invoices,
               SUM(si.net_amount) AS total_value
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY to_char(si.invoicedate, 'Day'), EXTRACT(DOW FROM si.invoicedate)
        ORDER BY dow
    """, qp)


def pr28_pareto(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT si.distributorid, SUM(si.net_amount) AS total,
                   ROW_NUMBER() OVER (ORDER BY SUM(si.net_amount) DESC) AS rn,
                   COUNT(*) OVER () AS total_distributors,
                   SUM(SUM(si.net_amount)) OVER () AS grand_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY si.distributorid
        ), cumulative AS (
            SELECT distributorid, total, rn, total_distributors, grand_total,
                   SUM(total) OVER (ORDER BY rn) / grand_total * 100 AS cumulative_pct
            FROM ranked
        )
        SELECT COUNT(*) AS top_n, SUM(total) AS top_value,
               ROUND(SUM(total) * 100.0 / MAX(grand_total), 2) AS top_pct,
               MAX(total_distributors) AS total_distributors
        FROM cumulative WHERE cumulative_pct <= 80.0
    """, qp)


def pr29_distributor_compare(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    ids = str(p.get("distributor_ids", "")).strip()
    if not ids:
        return {"rows": [], "columns": ["ds_code", "ds_name", "total_primary_sales", "invoices"], "row_count": 0, "error": "Provide distributor_ids (comma-separated)"}
    qp["dids"] = tuple(x.strip() for x in ids.split(",") if x.strip())
    placeholders = ",".join(f":did{i}" for i in range(len(qp["dids"])))
    for i, did in enumerate(qp["dids"]): qp[f"did{i}"] = did
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total_primary_sales,
               COUNT(DISTINCT si.invoiceno) AS invoices,
               ROUND(SUM(si.net_amount) / NULLIF(COUNT(DISTINCT si.invoiceno), 0), 2) AS avg_invoice,
               COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)) AS active_months
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE AND (CAST(si.distributorid AS TEXT) IN ({placeholders}) OR ds.ledgercode IN ({placeholders})) {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total_primary_sales DESC
    """, qp)


def pr30_monthly_run_rate(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)) AS month_count,
               SUM(si.net_amount) AS total_value,
               ROUND(SUM(si.net_amount) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)), 0), 2) AS avg_monthly,
               ROUND(SUM(si.net_amount) / 30.0, 2) AS daily_run_rate
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
    """, qp)


def pr31_item_monthly(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name, DATE_TRUNC('month', si.invoicedate) AS month,
               SUM(sid.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
        FROM sale_salesinvoice si
        INNER JOIN sale_salesinvoicedetail sid ON sid.invoiceid = si.invoiceid
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN itemmaster itm ON itm.itemid = sid.itemid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY itm.itemcode, itm.itemdescription, DATE_TRUNC('month', si.invoicedate)
        ORDER BY itm.itemdescription, month
    """, qp)


def pr32_distributor_growth(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    from datetime import datetime, timedelta
    if p.get("date_from") and p.get("date_to"):
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        pv_to = d_from; pv_from = d_from - timedelta(days=span)
        qp = {**qp_base, "cs": d_from.isoformat(), "ce": (d_to + timedelta(days=1)).isoformat(),
              "ps": pv_from.isoformat(), "pe": pv_to.isoformat()}
        return run_query(f"""
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
                   SUM(CASE WHEN si.invoicedate >= :cs AND si.invoicedate < :ce THEN si.net_amount ELSE 0 END) AS current_total,
                   SUM(CASE WHEN si.invoicedate >= :ps AND si.invoicedate < :pe THEN si.net_amount ELSE 0 END) AS previous_total,
                   ROUND((SUM(CASE WHEN si.invoicedate >= :cs AND si.invoicedate < :ce THEN si.net_amount ELSE 0 END)
                       - SUM(CASE WHEN si.invoicedate >= :ps AND si.invoicedate < :pe THEN si.net_amount ELSE 0 END))
                       / NULLIF(SUM(CASE WHEN si.invoicedate >= :ps AND si.invoicedate < :pe THEN si.net_amount ELSE 0 END), 0) * 100, 2) AS growth_pct
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
            WHERE si.iscancelled=FALSE AND si.invoicedate >= :ps AND si.invoicedate < :ce
            GROUP BY ds.ledgercode, ds.ledgername ORDER BY current_total DESC
        """, qp)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {_date_filter("si.invoicedate", p)}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, build_params(userid, p))


def pr33_sku_ranking(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT itm.itemcode, COALESCE(itm.itemdescription, sid.itemname) AS item_name,
               SUM(sid.net_amount) AS total, COUNT(DISTINCT si.invoiceno) AS invoices,
               ROUND(SUM(sid.net_amount) / NULLIF(COUNT(DISTINCT si.invoiceno), 0), 2) AS avg_invoice,
               COUNT(DISTINCT si.distributorid) AS distributor_count
        FROM sale_salesinvoice si
        INNER JOIN sale_salesinvoicedetail sid ON sid.invoiceid = si.invoiceid
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN itemmaster itm ON itm.itemid = sid.itemid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY itm.itemcode, COALESCE(itm.itemdescription, sid.itemname) ORDER BY total DESC LIMIT {_limit}
    """, qp)


def pr34_moving_avg_3m(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, total,
               ROUND(AVG(total) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg_3m
        FROM monthly ORDER BY month
    """, qp)


def pr35_abc_analysis(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total,
                   SUM(SUM(si.net_amount)) OVER () AS grand_total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
            WHERE si.iscancelled=FALSE {df}
            GROUP BY ds.ledgercode, ds.ledgername
        ), cum AS (
            SELECT ds_code, ds_name, total, grand_total,
                   SUM(total) OVER (ORDER BY total DESC) / grand_total * 100 AS cum_pct
            FROM ranked
        )
        SELECT ds_code, ds_name, total,
               ROUND(total * 100.0 / grand_total, 2) AS share_pct,
               CASE WHEN cum_pct <= 70 THEN 'A' WHEN cum_pct <= 90 THEN 'B' ELSE 'C' END AS abc_class
        FROM cum ORDER BY total DESC
    """, qp)


def pr36_market_share(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(si.net_amount) AS total,
               ROUND(SUM(si.net_amount) * 100.0 / SUM(SUM(si.net_amount)) OVER (), 2) AS share_pct,
               ROW_NUMBER() OVER (ORDER BY SUM(si.net_amount) DESC) AS rank
        FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def pr37_distributor_consistency(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH total_months AS (
            SELECT COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)) AS month_count
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
        )
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)) AS active_months,
               total_months.month_count AS total_months,
               ROUND(COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)) * 100.0 / total_months.month_count, 2) AS consistency_pct,
               SUM(si.net_amount) AS total,
               ROUND(SUM(si.net_amount) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', si.invoicedate)), 0), 2) AS avg_per_active_month
        FROM sale_salesinvoice si
        JOIN ledgermaster ds ON ds.ledgerid = si.distributorid AND ds.ledgertype = 1
        CROSS JOIN total_months
        INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
        WHERE si.iscancelled=FALSE {df}
        GROUP BY ds.ledgercode, ds.ledgername, total_months.month_count ORDER BY consistency_pct DESC
    """, qp)


def pr38_year_on_year(userid, params=None):
    p = params or {}; df = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', si.invoicedate) AS month, SUM(si.net_amount) AS total
            FROM sale_salesinvoice si INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
            WHERE si.iscancelled=FALSE {df}
            GROUP BY DATE_TRUNC('month', si.invoicedate)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total, 12) OVER (ORDER BY m.month) AS same_month_last_year,
               ROUND((m.total - LAG(m.total, 12) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total, 12) OVER (ORDER BY m.month), 0) * 100, 2) AS yoy_growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


PRIMARY_SALES_FLAGS = {
    "pr:this-month":            (pr1_this_month,           "Primary sales (receipts) this month"),
    "pr:last-30d":              (pr2_last_30d,             "Primary invoices for last 30 days"),
    "pr:vs-secondary":          (pr3_vs_secondary,         "Primary sales value vs secondary sales value this month"),
    "pr:by-sku":                (pr4_by_sku,               "Primary sales by item/SKU this month"),
    "pr:top-products-quarter":  (pr5_top_products_quarter, "Top 10 products by primary inflow this quarter"),
    "pr:ratio":                 (pr6_ratio,                "Primary vs secondary sales ratio (offtake %)"),
    "pr:by-distributor":        (pr7_by_distributor,       "Primary sales for all distributors in area [ASM+]"),
    "pr:top-distributor":       (pr8_top_distributor,      "Distributor with most primary stock received [ASM+]"),
    "pr:region-total":          (pr9_region_total,         "Total primary sales for region this month [RSM+]"),
    "pr:zone-by-distributor":   (pr10_zone_by_distributor, "Primary sales by distributor for zone [ZSM+]"),
    "pr:national":              (pr11_national,            "National primary sales by zone this financial year [NSM]"),
    "pr:trend-6m":              (pr12_trend_6m,            "Primary sales trend for region over last 6 months [RSM+]"),
    "pr:monthly-summary":       (pr13_monthly_summary,     "Month-wise primary sales summary"),
    "pr:fast-total":            (pr17_fast_total,          "Fast single-period primary sales total (no GROUP BY)"),
    "pr:compare-periods":       (pr14_compare_periods,     "Compare primary sales across two date ranges side by side"),
    "pr:custom-top":            (pr15_custom_top,          "Custom top-N primary sales grouped by distributor or party"),
    "pr:filtered":              (pr16_filtered,            "Filtered primary sales aggregate (filter by any column + value)"),
    "pr:distributor-monthly":   (pr18_distributor_monthly, "Primary sales breakdown by distributor AND month (cross-tab)"),
    "pr:year-to-date":          (pr19_year_to_date,       "Primary sales year-to-date from April 1st (FYTD)"),
    "pr:quarterly-summary":     (pr20_quarterly_summary,  "Quarter-wise primary sales summary"),
    "pr:avg-invoice":           (pr21_avg_invoice,        "Average value per primary invoice"),
    "pr:cumulative-monthly":    (pr22_cumulative_monthly, "Running cumulative primary sales month by month"),
    "pr:returns":               (pr23_returns,            "Primary credit notes / returns analysis"),
    "pr:growth-monthly":        (pr24_growth_monthly,     "Month-over-month primary sales growth percentage"),
    "pr:party-monthly":         (pr25_party_monthly,      "Primary sales by party AND month (cross-tab)"),
    "pr:invoice-range":         (pr26_invoice_range,      "Primary invoice size distribution (slab-wise)"),
    "pr:weekday-analysis":      (pr27_weekday_analysis,   "Primary sales by day of week"),
    "pr:pareto":                (pr28_pareto,             "Pareto analysis — top N distributors covering 80% of primary sales"),
    "pr:distributor-compare":   (pr29_distributor_compare,"Compare multiple distributors side by side by IDs"),
    "pr:monthly-run-rate":      (pr30_monthly_run_rate,   "Average monthly and daily primary sales run rate"),
    "pr:item-monthly":          (pr31_item_monthly,       "Item-wise monthly primary sales trend"),
    "pr:distributor-growth":    (pr32_distributor_growth, "Per-distributor primary sales growth over 2 periods"),
    "pr:sku-ranking":           (pr33_sku_ranking,        "SKU ranking by primary sales value and volume"),
    "pr:moving-avg-3m":         (pr34_moving_avg_3m,      "3-month rolling average of primary sales"),
    "pr:abc-analysis":          (pr35_abc_analysis,       "ABC classification of distributors by primary sales value"),
    "pr:market-share":          (pr36_market_share,       "Each distributor's share of total primary sales with rank"),
    "pr:distributor-consistency":(pr37_distributor_consistency, "Distributor consistency score by active primary months"),
    "pr:year-on-year":          (pr38_year_on_year,       "Month-by-month primary sales vs same month last year"),
}

