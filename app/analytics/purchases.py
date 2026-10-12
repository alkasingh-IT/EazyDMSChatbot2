"""DMS Purchases Analytics — P1 to P10 — god-mode aware."""
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


def p1_this_month(userid, params=None):
    p = params or {}; _limit = p.get("limit", 100); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT td.vch_no, td.vch_date, ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               itm.itemcode, itm.itemdescription AS item_name,
               td.billed_qty, td.rate, td.billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        ORDER BY td.vch_date DESC LIMIT {_limit}
    """, qp)


def p2_last_quarter(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(td.billed_value) AS total_purchase_value,
               COUNT(DISTINCT td.vch_no) AS purchase_invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def p3_pending(userid, params=None):
    p = params or {}; _limit = p.get("limit", 100); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT td.vch_no, td.vch_date, ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               itm.itemcode, itm.itemdescription AS item_name,
               td.billed_qty, td.billed_value, td.approvalstatus
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND (td.approvalstatus=0 OR td.approvalstatus IS NULL) {df}
        ORDER BY td.vch_date DESC LIMIT {_limit}
    """, qp)


def p4_by_category(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    cat_col = p.get("category_column")
    if cat_col:
        sel_cat = cat_col
        join_cat = ""
    else:
        sel_cat = "COALESCE(itmg.groupname, dvm.divisionname, td.s_optional1, 'Uncategorized')"
        join_cat = "JOIN itemmaster itm ON itm.itemid = td.itemid LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = itm.division"
    return run_monthly_parallel(f"""
        SELECT {sel_cat} AS item_category, SUM(td.billed_qty) AS total_qty,
               SUM(td.billed_value) AS total_purchase_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        {join_cat}
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY {sel_cat} ORDER BY total_purchase_value DESC
    """, qp)


def p5_item_history(userid, params=None):
    p = params or {}; item_id = p.get("item_id", ""); _limit = p.get("limit", 100)
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    qp["item_id"] = str(item_id)
    return run_query(f"""
        SELECT td.vch_no, td.vch_date, ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               itm.itemcode, itm.itemdescription AS item_name,
               td.billed_qty, td.rate, td.billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE (CAST(td.itemid AS TEXT) = :item_id OR itm.itemcode = :item_id) AND LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        ORDER BY td.vch_date DESC LIMIT {_limit}
    """, qp)


def p6_variance(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p)
    df_si = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               td_agg.tally_purchase_value,
               COALESCE(si_agg.primary_sales_value,0) AS primary_sales_value,
               td_agg.tally_purchase_value - COALESCE(si_agg.primary_sales_value,0) AS variance
        FROM (
          SELECT td.distributorid, SUM(td.billed_value) AS tally_purchase_value
          FROM transactiondetail td
          INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
          WHERE LOWER(td.trn_type)='purchase'
            AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
          GROUP BY td.distributorid
        ) td_agg
        JOIN ledgermaster ds ON ds.ledgerid = td_agg.distributorid AND ds.ledgertype = 1
        LEFT JOIN (
          SELECT si.distributorid, SUM(si.net_amount) AS primary_sales_value
          FROM sale_salesinvoice si
          INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
          WHERE si.iscancelled=FALSE {df_si}
          GROUP BY si.distributorid
        ) si_agg ON si_agg.distributorid=td_agg.distributorid
    """, qp)


def p7_by_distributor(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               c2.cityname AS ds_city, z2.zonename AS ds_zone,
               SUM(td.billed_value) AS total_purchase_value,
               COUNT(DISTINCT td.vch_no) AS purchase_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, c2.cityname, z2.zonename
        ORDER BY total_purchase_value DESC LIMIT {_limit}
    """, qp)


def p8_top_distributor(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total_purchase_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total_purchase_value DESC LIMIT 1
    """, qp)


def p9_trend_6m(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT DATE_TRUNC('month',td.vch_date) AS purchase_month, SUM(td.billed_value) AS total_purchase_value
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month',td.vch_date) ORDER BY purchase_month
        """, qp_base)
    from datetime import datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    queries = []; month_starts = []; cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        qp = {**qp_base, "ms": cursor.isoformat(), "me": m_end.isoformat()}
        queries.append((f"""
            SELECT SUM(td.billed_value) AS total_purchase_value
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ms AND td.vch_date < :me
        """, qp))
        month_starts.append(cursor)
        cursor = m_end
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"purchase_month": month_starts[i].isoformat()[:7], "total_purchase_value": res["rows"][0].get("total_purchase_value", 0)})
    return {"rows": rows, "columns": ["purchase_month", "total_purchase_value"], "row_count": len(rows), "error": None}


def p10_reconciliation(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p)
    df_si = _date_filter("si.invoicedate", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               td_agg.tally_purchase_value,
               COALESCE(si_agg.primary_sales_value,0) AS primary_sales_value,
               td_agg.tally_purchase_value - COALESCE(si_agg.primary_sales_value,0) AS variance
        FROM (
          SELECT td.distributorid, SUM(td.billed_value) AS tally_purchase_value
          FROM transactiondetail td
          INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
          WHERE LOWER(td.trn_type)='purchase'
            AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
          GROUP BY td.distributorid
        ) td_agg
        JOIN ledgermaster ds ON ds.ledgerid = td_agg.distributorid AND ds.ledgertype = 1
        LEFT JOIN (
          SELECT si.distributorid, SUM(si.net_amount) AS primary_sales_value
          FROM sale_salesinvoice si
          INNER JOIN ({rbac}) accd ON accd.locationid=si.distributorid
          WHERE si.iscancelled=FALSE {df_si}
          GROUP BY si.distributorid
        ) si_agg ON si_agg.distributorid=td_agg.distributorid
        ORDER BY variance DESC
    """, qp)


def p12_compare_periods(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    if p.get("date_from") and p.get("date_to"):
        from datetime import datetime, timedelta
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        prev_to = d_from; prev_from = d_from - timedelta(days=span)
        qp["prev_from"] = prev_from.isoformat(); qp["prev_to"] = prev_to.isoformat()
        df = _date_filter("td.vch_date", p)
        df_prev = "AND td.vch_date >= :prev_from AND td.vch_date < :prev_to"
    else:
        df = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE) + INTERVAL '1 month'"
        df_prev = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) - INTERVAL '1 month' AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE)"
    return run_query(f"""
        WITH current AS (
            SELECT SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        ), previous AS (
            SELECT SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_prev}
        )
        SELECT cm.total AS current_total, cm.invoices AS current_invoices,
               lm.total AS previous_total, lm.invoices AS previous_invoices,
               ROUND((cm.total - lm.total) / NULLIF(lm.total, 0) * 100, 2) AS change_pct
        FROM current cm, previous lm
    """, qp)


_PUR_GROUP_COLS = {
    "itemid", "itemcode", "item_name", "itemdescription", "item_group", "item_division",
    "distributorid", "ds_code", "ds_name", "ds_city", "ds_state", "ds_zone",
    "s_optional1", "s_optional2"
}
_PUR_METRICS = {"billed_value", "billed_qty"}
_PUR_FILTER_COLS = _PUR_GROUP_COLS | {"vch_no"}


def p13_custom_top(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    group_col = str(p.get("group_col", "item_name")).strip()
    if group_col not in _PUR_GROUP_COLS: group_col = "item_name"
    metric = str(p.get("metric", "billed_value")).strip()
    if metric not in _PUR_METRICS: metric = "billed_value"
    order = "DESC" if str(p.get("order", "desc")).upper() != "ASC" else "ASC"
    limit_sql = ""
    _limit = p.get("limit")
    if _limit is not None:
        _limit = max(1, int(_limit))
        limit_sql = f" LIMIT {_limit}"

    if group_col in ("item_name", "itemdescription"):
        grp_expr = "itm.itemdescription"; extra_sel = ", itm.itemcode"; extra_gb = ", itm.itemcode"
        join_sql = "JOIN itemmaster itm ON itm.itemid = td.itemid"
    elif group_col == "itemcode":
        grp_expr = "itm.itemcode"; extra_sel = ", itm.itemdescription AS item_name"; extra_gb = ", itm.itemdescription"
        join_sql = "JOIN itemmaster itm ON itm.itemid = td.itemid"
    elif group_col == "item_group":
        grp_expr = "itmg.groupname"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN itemmaster itm ON itm.itemid = td.itemid LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid"
    elif group_col == "item_division":
        grp_expr = "dvm.divisionname"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN itemmaster itm ON itm.itemid = td.itemid LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = itm.division"
    elif group_col in ("ds_name", "distributor_name"):
        grp_expr = "ds.ledgername"; extra_sel = ", ds.ledgercode AS ds_code"; extra_gb = ", ds.ledgercode"
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1"
    elif group_col in ("ds_code", "distributorid"):
        grp_expr = "ds.ledgercode"; extra_sel = ", ds.ledgername AS ds_name"; extra_gb = ", ds.ledgername"
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1"
    elif group_col in ("ds_city", "city"):
        grp_expr = "c2.cityname"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1 LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid"
    elif group_col in ("ds_state", "state"):
        grp_expr = "s2.statename"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1 LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid LEFT JOIN statemaster s2 ON s2.stateid = c2.stateid"
    elif group_col in ("ds_zone", "zone"):
        grp_expr = "z2.zonename"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1 LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid"
    else:
        grp_expr = f"td.{group_col}"; extra_sel = ""; extra_gb = ""; join_sql = ""

    return run_query(f"""
        SELECT {grp_expr} AS grp{extra_sel}, SUM(td.{metric}) AS total
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        {join_sql}
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY {grp_expr}{extra_gb}
        ORDER BY total {order}{limit_sql}
    """, qp)


def p14_filtered(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    filter_col = str(p.get("filter_col", "")).strip()
    if filter_col and filter_col not in _PUR_FILTER_COLS: filter_col = ""
    filter_val = str(p.get("filter_val", "")).strip()
    filter_op = str(p.get("filter_op", "eq")).strip()
    extra_where = ""
    if filter_col and filter_val:
        if filter_op == "eq":
            extra_where = f'AND LOWER(CAST(td.{filter_col} AS TEXT)) = LOWER(:filter_val)'
            qp["filter_val"] = filter_val
        elif filter_op in ("gt","lt","gte","lte","ge","le"):
            opmap = {"gt":">","lt":"<","gte":">=","ge":">=","lte":"<=","le":"<="}
            extra_where = f'AND CAST(td.{filter_col} AS NUMERIC) {opmap.get(filter_op, "=")} :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op == "like":
            extra_where = f"AND td.{filter_col} ILIKE :filter_val_pat"
            qp["filter_val_pat"] = f"%{filter_val}%"
    return run_query(f"""
        SELECT SUM(td.billed_value) AS total_value, SUM(td.billed_qty) AS total_qty,
               COUNT(DISTINCT td.vch_no) AS invoice_count, COUNT(DISTINCT td.distributorid) AS distributor_count
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df} {extra_where}
    """, qp)


def p11_monthly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT DATE_TRUNC('month',td.vch_date) AS month, SUM(td.billed_value) AS total_purchase_value
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month',td.vch_date) ORDER BY month
        """, qp_base)
    from datetime import datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    queries = []; month_starts = []; cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        qp = {**qp_base, "ms": cursor.isoformat(), "me": m_end.isoformat()}
        queries.append((f"""
            SELECT SUM(td.billed_value) AS total_purchase_value
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ms AND td.vch_date < :me
        """, qp))
        month_starts.append(cursor)
        cursor = m_end
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"month": month_starts[i].isoformat()[:7], "total_purchase_value": res["rows"][0].get("total_purchase_value", 0)})
    return {"rows": rows, "columns": ["month", "total_purchase_value"], "row_count": len(rows), "error": None}


def p16_distributor_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, DATE_TRUNC('month',td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, DATE_TRUNC('month',td.vch_date)
        ORDER BY ds.ledgername, month
    """, qp)


def p15_fast_total(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(td.billed_value) AS total_purchase_value,
               SUM(td.billed_qty) AS total_quantity
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def p17_year_to_date(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    from datetime import date
    today = date.today(); fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)
    df = _date_filter("td.vch_date", {**p, "date_from": fy_start.isoformat()})
    return run_query(f"""
        SELECT SUM(td.billed_value) AS ytd_purchase_value, SUM(td.billed_qty) AS ytd_qty
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def p18_quarterly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT EXTRACT(YEAR FROM td.vch_date)::text || '-Q' || CEIL(EXTRACT(MONTH FROM td.vch_date)/3.0)::text AS quarter,
                   SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY EXTRACT(YEAR FROM td.vch_date), CEIL(EXTRACT(MONTH FROM td.vch_date)/3.0) ORDER BY quarter
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
            SELECT SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :qs AND td.vch_date < :qe
        """, qp))
        q_starts.append((lab, q_start, q_end))
        cursor = q_end + timedelta(days=1)
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"quarter": q_starts[i][0], "total": res["rows"][0].get("total", 0)})
    return {"rows": rows, "columns": ["quarter", "total"], "row_count": len(rows), "error": None}


def p19_avg_invoice(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(td.billed_value) AS total, SUM(td.billed_qty) AS total_qty, COUNT(DISTINCT td.vch_no) AS invoices,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2) AS avg_invoice_value
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def p20_cumulative_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS month_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, month_total,
               ROUND(SUM(month_total) OVER (ORDER BY month), 2) AS cumulative_total
        FROM monthly ORDER BY month
    """, qp)


def p21_returns(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    df2 = _date_filter("td2.vch_date", p)
    return run_query(f"""
        SELECT COUNT(DISTINCT td.vch_no) AS return_invoices,
               SUM(ABS(td.billed_value)) AS return_value,
               ROUND(SUM(ABS(td.billed_value)) * 100.0 / NULLIF((SELECT SUM(td2.billed_value) FROM transactiondetail td2
                   INNER JOIN ({rbac}) accd2 ON accd2.locationid=td2.distributorid
                   WHERE LOWER(td2.trn_type)='purchase' AND td2.iscancelled IS DISTINCT FROM TRUE AND td2.isdeleted IS DISTINCT FROM TRUE {df2}), 0), 2) AS return_pct
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND td.billed_value < 0 {df}
    """, qp)


def p22_growth_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total) OVER (ORDER BY m.month) AS prev_month,
               ROUND((m.total - LAG(m.total) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total) OVER (ORDER BY m.month), 0) * 100, 2) AS growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


def p23_vendor_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS vendor_code, ds.ledgername AS vendor_name, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, DATE_TRUNC('month', td.vch_date)
        ORDER BY ds.ledgername, month
    """, qp)


def p24_invoice_range(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT CASE
            WHEN td.billed_value < 5000 THEN 'Below 5K'
            WHEN td.billed_value < 25000 THEN '5K-25K'
            WHEN td.billed_value < 100000 THEN '25K-1L'
            WHEN td.billed_value < 500000 THEN '1L-5L'
            ELSE '5L+'
        END AS invoice_range,
        COUNT(DISTINCT td.vch_no) AS invoices,
        SUM(td.billed_value) AS total_value
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY CASE
            WHEN td.billed_value < 5000 THEN 'Below 5K'
            WHEN td.billed_value < 25000 THEN '5K-25K'
            WHEN td.billed_value < 100000 THEN '25K-1L'
            WHEN td.billed_value < 500000 THEN '1L-5L'
            ELSE '5L+'
        END ORDER BY MIN(td.billed_value)
    """, qp)


def p25_weekday_analysis(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT to_char(td.vch_date, 'Day') AS weekday,
               EXTRACT(DOW FROM td.vch_date) AS dow,
               COUNT(DISTINCT td.vch_no) AS invoices,
               SUM(td.billed_value) AS total_value
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY to_char(td.vch_date, 'Day'), EXTRACT(DOW FROM td.vch_date)
        ORDER BY dow
    """, qp)


def p26_pareto(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT td.distributorid, SUM(td.billed_value) AS total,
                   ROW_NUMBER() OVER (ORDER BY SUM(td.billed_value) DESC) AS rn,
                   COUNT(*) OVER () AS total_distributors,
                   SUM(SUM(td.billed_value)) OVER () AS grand_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY td.distributorid
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


def p27_distributor_compare(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    ids = str(p.get("distributor_ids", "")).strip()
    if not ids:
        return {"rows": [], "columns": ["ds_code", "ds_name", "total", "invoices"], "row_count": 0, "error": "Provide distributor_ids (comma-separated)"}
    placeholders = ",".join(f":did{i}" for i, _ in enumerate(ids.split(",")))
    for i, did in enumerate(x.strip() for x in ids.split(",") if x.strip()):
        qp[f"did{i}"] = did
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
               COUNT(DISTINCT td.vch_no) AS invoices,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2) AS avg_invoice,
               COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS active_months
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND (CAST(td.distributorid AS TEXT) IN ({placeholders}) OR ds.ledgercode IN ({placeholders})) {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def p28_monthly_run_rate(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS month_count,
               SUM(td.billed_value) AS total_value,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)), 0), 2) AS avg_monthly,
               ROUND(SUM(td.billed_value) / 30.0, 2) AS daily_run_rate
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def p29_item_monthly(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription, DATE_TRUNC('month', td.vch_date)
        ORDER BY itm.itemdescription, month
    """, qp)


def p30_distributor_growth(userid, params=None):
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
                   SUM(CASE WHEN td.vch_date >= :cs AND td.vch_date < :ce THEN td.billed_value ELSE 0 END) AS current_total,
                   SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END) AS previous_total,
                   ROUND((SUM(CASE WHEN td.vch_date >= :cs AND td.vch_date < :ce THEN td.billed_value ELSE 0 END)
                       - SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END))
                       / NULLIF(SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END), 0) * 100, 2) AS growth_pct
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ps AND td.vch_date < :ce
            GROUP BY ds.ledgercode, ds.ledgername ORDER BY current_total DESC
        """, qp)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {_date_filter("td.vch_date", p)}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, build_params(userid, p))


def p31_category_monthly(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT COALESCE(itmg.groupname, dvm.divisionname, td.s_optional1, 'Other') AS category, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid
        LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = itm.division
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY COALESCE(itmg.groupname, dvm.divisionname, td.s_optional1, 'Other'), DATE_TRUNC('month', td.vch_date)
        ORDER BY category, month
    """, qp)


def p32_moving_avg_3m(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, total,
               ROUND(AVG(total) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg_3m
        FROM monthly ORDER BY month
    """, qp)


def p33_abc_analysis(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
                   SUM(SUM(td.billed_value)) OVER () AS grand_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
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


def p34_market_share(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
               ROUND(SUM(td.billed_value) * 100.0 / SUM(SUM(td.billed_value)) OVER (), 2) AS share_pct,
               ROW_NUMBER() OVER (ORDER BY SUM(td.billed_value) DESC) AS rank
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def p35_distributor_consistency(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH total_months AS (
            SELECT COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS month_count
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        )
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS active_months,
               total_months.month_count AS total_months,
               ROUND(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) * 100.0 / total_months.month_count, 2) AS consistency_pct,
               SUM(td.billed_value) AS total,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)), 0), 2) AS avg_per_active_month
        FROM transactiondetail td
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        CROSS JOIN total_months
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, total_months.month_count ORDER BY consistency_pct DESC
    """, qp)


def p36_year_on_year(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='purchase' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total, 12) OVER (ORDER BY m.month) AS same_month_last_year,
               ROUND((m.total - LAG(m.total, 12) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total, 12) OVER (ORDER BY m.month), 0) * 100, 2) AS yoy_growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


PURCHASES_FLAGS = {
    "pur:this-month":       (p1_this_month,      "Purchase entries for this month"),
    "pur:last-quarter":     (p2_last_quarter,    "Total purchase value last quarter"),
    "pur:pending":          (p3_pending,         "Pending/unmatched purchase entries"),
    "pur:by-category":      (p4_by_category,     "Purchases by item category this month"),
    "pur:item-history":     (p5_item_history,    "Purchase history for a specific item (last 3 months)"),
    "pur:variance":         (p6_variance,        "Variance between Tally purchases and DMS primary sales"),
    "pur:by-distributor":   (p7_by_distributor,  "Purchases for all distributors in area [ASM+]"),
    "pur:top-distributor":  (p8_top_distributor, "Distributor with highest purchase volume [ASM+]"),
    "pur:trend-6m":         (p9_trend_6m,        "Purchase trends for region over last 6 months [RSM+]"),
    "pur:reconciliation":   (p10_reconciliation, "Purchase vs primary sales reconciliation [RSM+]"),
    "pur:monthly-summary":  (p11_monthly_summary, "Month-wise purchase summary (no per-distributor)"),
    "pur:fast-total":       (p15_fast_total,      "Fast single-period purchase value + qty (no GROUP BY)"),
    "pur:compare-periods":  (p12_compare_periods, "Compare purchases across two date ranges side by side"),
    "pur:custom-top":       (p13_custom_top,      "Custom top-N purchases grouped by any column (item/distributor)"),
    "pur:filtered":             (p14_filtered,            "Filtered purchase aggregate (filter by any column + value)"),
    "pur:distributor-monthly":  (p16_distributor_monthly, "Purchase breakdown by distributor AND month (cross-tab)"),
    "pur:year-to-date":         (p17_year_to_date,       "Purchase year-to-date from April 1st (FYTD)"),
    "pur:quarterly-summary":    (p18_quarterly_summary,  "Quarter-wise purchase summary"),
    "pur:avg-invoice":          (p19_avg_invoice,        "Average value per purchase invoice"),
    "pur:cumulative-monthly":   (p20_cumulative_monthly, "Running cumulative purchases month by month"),
    "pur:returns":              (p21_returns,            "Purchase returns / debit notes analysis"),
    "pur:growth-monthly":       (p22_growth_monthly,     "Month-over-month purchase growth percentage"),
    "pur:vendor-monthly":       (p23_vendor_monthly,     "Purchase breakdown by vendor AND month (cross-tab)"),
    "pur:invoice-range":        (p24_invoice_range,      "Purchase invoice size distribution (slab-wise)"),
    "pur:weekday-analysis":     (p25_weekday_analysis,   "Purchases by day of week"),
    "pur:pareto":               (p26_pareto,             "Pareto analysis — top N distributors covering 80% of purchases"),
    "pur:distributor-compare":  (p27_distributor_compare,"Compare multiple distributors side by side by IDs"),
    "pur:monthly-run-rate":     (p28_monthly_run_rate,   "Average monthly and daily purchase run rate"),
    "pur:item-monthly":         (p29_item_monthly,       "Item-wise monthly purchase trend"),
    "pur:distributor-growth":   (p30_distributor_growth, "Per-distributor purchase growth over 2 periods"),
    "pur:category-monthly":     (p31_category_monthly,   "Category-wise monthly purchase trend"),
    "pur:moving-avg-3m":        (p32_moving_avg_3m,     "3-month rolling average of purchase volume"),
    "pur:abc-analysis":         (p33_abc_analysis,      "ABC classification of distributors by purchase value"),
    "pur:market-share":         (p34_market_share,      "Each distributor's share of total purchases with rank"),
    "pur:distributor-consistency":(p35_distributor_consistency, "Distributor consistency score by active purchase months"),
    "pur:year-on-year":         (p36_year_on_year,      "Month-by-month purchases vs same month last year"),
}
