"""DMS Secondary Sales — Q1 to Q15 — god-mode aware."""
from ..db import run_query, run_parallel, run_monthly_parallel
from ._rbac import rbac_clause, needs_userid, build_params


def _date_filter(col, params):
    if params.get("date_from") and params.get("date_to"):
        return f"AND {col} >= :date_from AND {col} < CAST(:date_to AS DATE) + INTERVAL '1 day'"
    if params.get("date_from"):
        return f"AND {col} >= :date_from"
    if params.get("date_to"):
        return f"AND {col} <= :date_to"
    return "AND {0} >= DATE_TRUNC('month', CURRENT_DATE) AND {0} < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'".format(col)


def q1_monthly_total(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT SUM(td.billed_value) AS total_secondary_sales,
               SUM(td.billed_qty) AS total_quantity,
               COUNT(DISTINCT td.vch_no) AS invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q2_by_item_last_week(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name,
               itmg.groupname AS item_group, dvm.divisionname AS item_division,
               SUM(td.billed_qty) AS total_billed_qty,
               SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid
        LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = itm.division
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription, itmg.groupname, dvm.divisionname
        ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q3_vs_target(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               z2.zonename AS ds_zone, s2.statename AS ds_state,
               SUM(td.billed_value) AS actual_secondary_sales
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid
        LEFT JOIN statemaster s2 ON s2.stateid = c2.stateid
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, z2.zonename, s2.statename
    """, qp)


def q4_top5_items_quarter(userid, params=None):
    p = params or {}; _limit = p.get("limit", 5); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name,
               itmg.groupname AS item_group, dvm.divisionname AS item_division,
               SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid
        LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = itm.division
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription, itmg.groupname, dvm.divisionname
        ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q5_top_dealers(userid, params=None):
    p = params or {}; _limit = p.get("limit", 20); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name,
               SUM(td.billed_value) AS total_billed_value,
               COUNT(DISTINCT td.vch_no) AS invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY dln.ledgercode, dln.ledgername ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q6_trend_3m(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        SELECT DATE_TRUNC('month',td.vch_date) AS sales_month,
               ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY DATE_TRUNC('month',td.vch_date), ds.ledgercode, ds.ledgername ORDER BY sales_month
    """, qp)


def q17_compare_periods(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    if p.get("date_from") and p.get("date_to"):
        from datetime import datetime, timedelta
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        prev_to = d_from
        prev_from = d_from - timedelta(days=span)
        qp["prev_from"] = prev_from.isoformat()
        qp["prev_to"] = prev_to.isoformat()
        df = _date_filter("td.vch_date", p)
        df_prev = "AND td.vch_date >= :prev_from AND td.vch_date < :prev_to"
    else:
        df = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE) + INTERVAL '1 month'"
        df_prev = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) - INTERVAL '1 month' AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE)"
    return run_query(f"""
        WITH current AS (
            SELECT SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type)='sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        ), previous AS (
            SELECT SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type)='sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df_prev}
        )
        SELECT cm.total AS current_total, cm.invoices AS current_invoices,
               lm.total AS previous_total, lm.invoices AS previous_invoices,
               ROUND((cm.total - lm.total) / NULLIF(lm.total, 0) * 100, 2) AS change_pct
        FROM current cm, previous lm
    """, qp)


_SS_GROUP_COLS = {
    "itemid", "itemcode", "item_name", "itemdescription", "item_group", "item_division",
    "distributorid", "ds_code", "ds_name", "ds_city", "ds_state", "ds_zone",
    "dealerid", "dl_code", "dealer_name", "salespersonid", "salesperson_name",
    "s_optional1", "s_optional2"
}
_SS_METRICS = {"billed_value", "billed_qty"}
_SS_FILTER_COLS = _SS_GROUP_COLS | {"alias", "vch_no"}


def q18_custom_top(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    group_col = str(p.get("group_col", "item_name")).strip()
    if group_col not in _SS_GROUP_COLS:
        group_col = "item_name"
    metric = str(p.get("metric", "billed_value")).strip()
    if metric not in _SS_METRICS:
        metric = "billed_value"
    order = "DESC" if str(p.get("order", "desc")).upper() != "ASC" else "ASC"
    limit_sql = ""
    _limit = p.get("limit")
    if _limit is not None:
        _limit = max(1, int(_limit))
        limit_sql = f" LIMIT {_limit}"

    # Build dynamic group expression and master join
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
    elif group_col in ("dealer_name", "alias"):
        grp_expr = "COALESCE(dln.ledgername, td.alias)"; extra_sel = ", dln.ledgercode AS dl_code"; extra_gb = ", dln.ledgercode, td.alias"
        join_sql = "LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid"
    elif group_col in ("dl_code", "dealerid"):
        grp_expr = "COALESCE(dln.ledgercode, td.dl_code)"; extra_sel = ", COALESCE(dln.ledgername, td.alias) AS dealer_name"; extra_gb = ", dln.ledgername, td.dl_code, td.alias"
        join_sql = "LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid"
    elif group_col in ("salesperson_name", "salespersonid"):
        grp_expr = "emp.employeename"; extra_sel = ""; extra_gb = ""
        join_sql = "JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1 LEFT JOIN hr_employeemaster emp ON emp.employeeid = ds.salespersonid"
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
        SELECT {grp_expr} AS grp{extra_sel},
               SUM(td.{metric}) AS total
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        {join_sql}
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY {grp_expr}{extra_gb}
        ORDER BY total {order}{limit_sql}
    """, qp)


def q19_filtered(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    filter_col = str(p.get("filter_col", "")).strip()
    if filter_col and filter_col not in _SS_FILTER_COLS:
        filter_col = ""
    filter_val = str(p.get("filter_val", "")).strip()
    filter_op = str(p.get("filter_op", "eq")).strip()
    extra_where = ""
    if filter_col and filter_val:
        if filter_op == "eq":
            extra_where = f'AND LOWER(CAST(td.{filter_col} AS TEXT)) = LOWER(:filter_val)'
        elif filter_op == "gt":
            extra_where = f'AND CAST(td.{filter_col} AS NUMERIC) > :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op == "lt":
            extra_where = f'AND CAST(td.{filter_col} AS NUMERIC) < :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op in ("gte", "ge"):
            extra_where = f'AND CAST(td.{filter_col} AS NUMERIC) >= :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op in ("lte", "le"):
            extra_where = f'AND CAST(td.{filter_col} AS NUMERIC) <= :filter_val_num'
            qp["filter_val_num"] = filter_val
        elif filter_op == "like":
            extra_where = f"AND td.{filter_col} ILIKE :filter_val_pat"
            qp["filter_val_pat"] = f"%{filter_val}%"
        else:
            extra_where = f'AND LOWER(CAST(td.{filter_col} AS TEXT)) = LOWER(:filter_val)'
        if "filter_val" not in qp and filter_op in ("eq",):
            qp["filter_val"] = filter_val
    return run_query(f"""
        SELECT SUM(td.billed_value) AS total_value,
               SUM(td.billed_qty) AS total_qty,
               COUNT(DISTINCT td.vch_no) AS invoice_count,
               COUNT(DISTINCT td.distributorid) AS distributor_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df} {extra_where}
    """, qp)


def q16_monthly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT DATE_TRUNC('month',td.vch_date) AS month, SUM(td.billed_value) AS total_sales
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month',td.vch_date) ORDER BY month
        """, qp_base)
    from datetime import datetime, timedelta
    d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
    d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
    queries = []; month_starts = []; cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        ms = cursor.isoformat(); me = m_end.isoformat()
        qp = {**qp_base, f"ms": ms, f"me": me}
        queries.append((f"""
            SELECT SUM(td.billed_value) AS total_sales
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ms AND td.vch_date < :me
        """, qp))
        month_starts.append(cursor)
        cursor = m_end
    results = run_parallel(queries)
    rows = []
    for i, res in enumerate(results):
        if res.get("rows"):
            rows.append({"month": month_starts[i].isoformat()[:7], "total_sales": res["rows"][0].get("total_sales", 0)})
    return {"rows": rows, "columns": ["month", "total_sales"], "row_count": len(rows), "error": None}


def q7_growth(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    if p.get("date_from") and p.get("date_to"):
        from datetime import datetime, timedelta
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        prev_to = d_from
        prev_from = d_from - timedelta(days=span)
        qp["prev_from"] = prev_from.isoformat()
        qp["prev_to"] = prev_to.isoformat()
        df1 = _date_filter("td.vch_date", p)
        df2 = "AND td.vch_date >= :prev_from AND td.vch_date < :prev_to"
    else:
        df1 = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE) + INTERVAL '1 month'"
        df2 = "AND td.vch_date >= DATE_TRUNC('month',CURRENT_DATE) - INTERVAL '1 month' AND td.vch_date < DATE_TRUNC('month',CURRENT_DATE)"
    return run_query(f"""
        WITH cm AS (
            SELECT SUM(td.billed_value) AS total
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type)='sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df1}
        ), lm AS (
            SELECT SUM(td.billed_value) AS total
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type)='sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df2}
        )
        SELECT cm.total AS current_month_sales, lm.total AS last_month_sales,
               ROUND((cm.total - lm.total) / NULLIF(lm.total, 0) * 100, 2) AS growth_pct
        FROM cm, lm
    """, qp)


def q8_by_category(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    cat_col = p.get("category_column")
    if cat_col:
        sel_cat = cat_col
        join_cat = ""
    else:
        sel_cat = "COALESCE(itmg.groupname, td.s_optional1, 'Uncategorized')"
        join_cat = "JOIN itemmaster itm ON itm.itemid = td.itemid LEFT JOIN itemgroup itmg ON itmg.itemgroupid = itm.groupid"
    return run_query(f"""
        SELECT {sel_cat} AS product_category, SUM(td.billed_qty) AS total_qty,
               SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        {join_cat}
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY {sel_cat} ORDER BY total_billed_value DESC
    """, qp)


def q9_by_so(userid, params=None):
    p = params or {}; so_uid = p.get("so_userid", userid); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p)
    qp = {k: v for k, v in p.items() if k in ("date_from", "date_to")}
    qp["so_userid"] = so_uid
    return run_query(f"""
        SELECT ds.ledgername AS ds_name, ds.ledgercode AS ds_code, td.vch_no, td.vch_date,
               itm.itemcode, itm.itemdescription AS item_name, td.billed_qty, td.billed_value
        FROM transactiondetail td
        INNER JOIN (SELECT DISTINCT locationid FROM location_access_detail WHERE userid=:so_userid) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        ORDER BY td.vch_date DESC
    """, qp)


def q10_team_by_so(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT emp.employeename AS salesperson_name, ds.ledgername AS ds_name, ds.ledgercode AS ds_code,
               SUM(td.billed_value) AS total_billed_value,
               COUNT(DISTINCT td.vch_no) AS invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN hr_employeemaster emp ON emp.employeeid = ds.salespersonid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY emp.employeename, ds.ledgername, ds.ledgercode ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q11_top_so(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT emp.employeename AS salesperson_name, SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN hr_employeemaster emp ON emp.employeeid = ds.salespersonid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY emp.employeename ORDER BY total_billed_value DESC LIMIT 1
    """, qp)


def q12_by_distributor(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total_billed_value,
               COUNT(DISTINCT td.vch_no) AS invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q13_compare_areas(userid, params=None):
    p = params or {}; _limit = p.get("limit", 50); df = _date_filter("td.vch_date", p)
    rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               z2.zonename AS ds_zone, s2.statename AS ds_state, c2.cityname AS ds_city,
               SUM(td.billed_value) AS total_billed_value,
               COUNT(DISTINCT td.vch_no) AS invoice_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN citymaster c2 ON c2.cityid = ds.cityid
        LEFT JOIN statemaster s2 ON s2.stateid = c2.stateid
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, z2.zonename, s2.statename, c2.cityname ORDER BY total_billed_value DESC LIMIT {_limit}
    """, qp)


def q14_zone_quarter(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT z2.zonename AS ds_zone, SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN zonemaster z2 ON z2.zoneid = ds.zoneid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY z2.zonename ORDER BY total_billed_value DESC
    """, qp)


def q15_national(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT SUM(td.billed_value) AS national_secondary_sales,
               COUNT(DISTINCT td.vch_no) AS invoice_count,
               COUNT(DISTINCT td.distributorid) AS distributor_count
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q21_distributor_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, DATE_TRUNC('month',td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, DATE_TRUNC('month',td.vch_date)
        ORDER BY ds.ledgername, month
    """, qp)


def q22_year_to_date(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    from datetime import date
    today = date.today(); fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)
    df = _date_filter("td.vch_date", {**p, "date_from": fy_start.isoformat()})
    return run_query(f"""
        SELECT SUM(td.billed_value) AS ytd_secondary_sales, COUNT(DISTINCT td.vch_no) AS ytd_invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q23_quarterly_summary(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    if not (p.get("date_from") and p.get("date_to")):
        return run_query(f"""
            SELECT EXTRACT(YEAR FROM td.vch_date)::text || '-Q' || CEIL(EXTRACT(MONTH FROM td.vch_date)/3.0)::text AS quarter,
                   SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
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
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
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


def q24_avg_invoice(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2) AS avg_invoice_value
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q25_cumulative_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS month_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, month_total,
               ROUND(SUM(month_total) OVER (ORDER BY month), 2) AS cumulative_total
        FROM monthly ORDER BY month
    """, qp)


def q26_returns(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    df2 = _date_filter("td2.vch_date", p)
    return run_query(f"""
        SELECT COUNT(DISTINCT td.vch_no) AS return_invoices,
               SUM(ABS(td.billed_value)) AS return_value,
               ROUND(SUM(ABS(td.billed_value)) * 100.0 / NULLIF((SELECT SUM(td2.billed_value) FROM transactiondetail td2
                   INNER JOIN ({rbac}) accd2 ON accd2.locationid=td2.distributorid
                   WHERE LOWER(td2.trn_type)='sales' AND td2.iscancelled IS DISTINCT FROM TRUE AND td2.isdeleted IS DISTINCT FROM TRUE {df2}), 0), 2) AS return_pct
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND td.billed_value < 0 {df}
    """, qp)


def q27_growth_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total) OVER (ORDER BY m.month) AS prev_month,
               ROUND((m.total - LAG(m.total) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total) OVER (ORDER BY m.month), 0) * 100, 2) AS growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


def q28_dealer_monthly(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY dln.ledgercode, dln.ledgername, DATE_TRUNC('month', td.vch_date)
        ORDER BY dln.ledgername, month
    """, qp)


def q29_invoice_range(userid, params=None):
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
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY CASE
            WHEN td.billed_value < 5000 THEN 'Below 5K'
            WHEN td.billed_value < 25000 THEN '5K-25K'
            WHEN td.billed_value < 100000 THEN '25K-1L'
            WHEN td.billed_value < 500000 THEN '1L-5L'
            ELSE '5L+'
        END ORDER BY MIN(td.billed_value)
    """, qp)


def q30_weekday_analysis(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT to_char(td.vch_date, 'Day') AS weekday,
               EXTRACT(DOW FROM td.vch_date) AS dow,
               COUNT(DISTINCT td.vch_no) AS invoices,
               SUM(td.billed_value) AS total_value
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY to_char(td.vch_date, 'Day'), EXTRACT(DOW FROM td.vch_date)
        ORDER BY dow
    """, qp)


def q31_pareto(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
                   ROW_NUMBER() OVER (ORDER BY SUM(td.billed_value) DESC) AS rn,
                   COUNT(*) OVER () AS total_distributors,
                   SUM(SUM(td.billed_value)) OVER () AS grand_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY ds.ledgercode, ds.ledgername
        ), cumulative AS (
            SELECT ds_code, ds_name, total, rn, total_distributors, grand_total,
                   SUM(total) OVER (ORDER BY rn) / grand_total * 100 AS cumulative_pct
            FROM ranked
        )
        SELECT COUNT(*) AS top_n, SUM(total) AS top_value,
               ROUND(SUM(total) * 100.0 / MAX(grand_total), 2) AS top_pct,
               MAX(total_distributors) AS total_distributors
        FROM cumulative WHERE cumulative_pct <= 80.0
    """, qp)


def q32_distributor_compare(userid, params=None):
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
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
          AND (CAST(td.distributorid AS TEXT) IN ({placeholders}) OR ds.ledgercode IN ({placeholders})) {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def q33_monthly_run_rate(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS month_count,
               SUM(td.billed_value) AS total_value,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)), 0), 2) AS avg_monthly,
               ROUND(SUM(td.billed_value) / 30.0, 2) AS daily_run_rate
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q34_item_monthly(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT itm.itemcode, itm.itemdescription AS item_name, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN itemmaster itm ON itm.itemid = td.itemid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY itm.itemcode, itm.itemdescription, DATE_TRUNC('month', td.vch_date)
        ORDER BY itm.itemdescription, month
    """, qp)


def q35_dealer_all(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 100))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name,
               SUM(td.billed_value) AS total, SUM(td.billed_qty) AS qty,
               COUNT(DISTINCT td.vch_no) AS invoices,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2) AS avg_invoice,
               COUNT(DISTINCT td.distributorid) AS distributor_count
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY dln.ledgercode, dln.ledgername ORDER BY total DESC LIMIT {_limit}
    """, qp)


def q36_dealer_growth(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
    from datetime import datetime, timedelta
    if p.get("date_from") and p.get("date_to"):
        d_from = datetime.strptime(str(p["date_from"]), "%Y-%m-%d").date()
        d_to = datetime.strptime(str(p["date_to"]), "%Y-%m-%d").date()
        span = (d_to - d_from).days + 1
        pv_to = d_from; pv_from = d_from - timedelta(days=span)
        qp = {**qp_base, "cs": d_from.isoformat(), "ce": (d_to + timedelta(days=1)).isoformat(),
              "ps": pv_from.isoformat(), "pe": pv_to.isoformat()}
        return run_query(f"""
            SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name,
                   SUM(CASE WHEN td.vch_date >= :cs AND td.vch_date < :ce THEN td.billed_value ELSE 0 END) AS current_total,
                   SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END) AS previous_total,
                   ROUND((SUM(CASE WHEN td.vch_date >= :cs AND td.vch_date < :ce THEN td.billed_value ELSE 0 END)
                       - SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END))
                       / NULLIF(SUM(CASE WHEN td.vch_date >= :ps AND td.vch_date < :pe THEN td.billed_value ELSE 0 END), 0) * 100, 2) AS growth_pct
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ps AND td.vch_date < :ce
            GROUP BY dln.ledgercode, dln.ledgername ORDER BY current_total DESC
        """, qp)
    return run_query(f"""
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name, SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY dln.ledgercode, dln.ledgername ORDER BY total DESC
    """, qp)


def q37_so_monthly(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT emp.employeename AS salesperson_name, DATE_TRUNC('month', td.vch_date) AS month,
               SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN hr_employeemaster emp ON emp.employeeid = ds.salespersonid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY emp.employeename, DATE_TRUNC('month', td.vch_date)
        ORDER BY emp.employeename, month
    """, qp)


def q38_so_ranking(userid, params=None):
    p = params or {}; _limit = int(p.get("limit", 50))
    df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT emp.employeename AS salesperson_name, SUM(td.billed_value) AS total,
               COUNT(DISTINCT td.vch_no) AS invoices,
               COUNT(DISTINCT td.dealerid) AS dealer_count,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0), 2) AS avg_invoice
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN hr_employeemaster emp ON emp.employeeid = ds.salespersonid
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY emp.employeename ORDER BY total DESC LIMIT {_limit}
    """, qp)


def q39_distributor_growth(userid, params=None):
    p = params or {}; rbac = rbac_clause(p); qp_base = build_params(userid, p)
    df = _date_filter("td.vch_date", p)
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
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= :ps AND td.vch_date < :ce
            GROUP BY ds.ledgercode, ds.ledgername ORDER BY current_total DESC
        """, qp)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total, COUNT(DISTINCT td.vch_no) AS invoices
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def q40_moving_avg_3m(userid, params=None):
    """3-month rolling average of secondary sales."""
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(month, 'YYYY-MM') AS month, total,
               ROUND(AVG(total) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg_3m
        FROM monthly ORDER BY month
    """, qp)


def q41_abc_analysis(userid, params=None):
    """ABC classification of distributors by secondary sales."""
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH ranked AS (
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
                   SUM(SUM(td.billed_value)) OVER () AS grand_total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
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


def q42_market_share(userid, params=None):
    """Each distributor's share of total secondary sales."""
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name, SUM(td.billed_value) AS total,
               ROUND(SUM(td.billed_value) * 100.0 / SUM(SUM(td.billed_value)) OVER (), 2) AS share_pct,
               ROW_NUMBER() OVER (ORDER BY SUM(td.billed_value) DESC) AS rank
        FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername ORDER BY total DESC
    """, qp)


def q43_distributor_consistency(userid, params=None):
    """Distributor consistency score - active months, regularity."""
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH total_months AS (
            SELECT COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS month_count
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        )
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) AS active_months,
               total_months.month_count AS total_months,
               ROUND(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)) * 100.0 / total_months.month_count, 2) AS consistency_pct,
               SUM(td.billed_value) AS total,
               ROUND(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT DATE_TRUNC('month', td.vch_date)), 0), 2) AS avg_per_active_month
        FROM transactiondetail td, total_months
        INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername, total_months.month_count ORDER BY consistency_pct DESC
    """, qp)


def q44_year_on_year(userid, params=None):
    """Compare each month with same month last year."""
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS month, SUM(td.billed_value) AS total
            FROM transactiondetail td INNER JOIN ({rbac}) accd ON accd.locationid=td.distributorid
            WHERE LOWER(td.trn_type)='sales' AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(m.month, 'YYYY-MM') AS month, m.total,
               LAG(m.total, 12) OVER (ORDER BY m.month) AS same_month_last_year,
               ROUND((m.total - LAG(m.total, 12) OVER (ORDER BY m.month)) / NULLIF(LAG(m.total, 12) OVER (ORDER BY m.month), 0) * 100, 2) AS yoy_growth_pct
        FROM monthly m ORDER BY m.month
    """, qp)


def q20_fast_total(userid, params=None):
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        SELECT SUM(td.billed_value) AS total_sales,
               SUM(td.billed_qty) AS total_quantity
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
    """, qp)


def q45_avg_invoice_per_dealer(userid, params=None):
    # AN1. Avg invoice value per dealer per distributor
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT td.dealerid) AS active_dealers,
               COUNT(DISTINCT td.vch_no) AS invoice_count,
               SUM(td.billed_value) AS total_value,
               ROUND(CAST(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.dealerid), 0) AS NUMERIC), 2) AS avg_value_per_dealer,
               ROUND(CAST(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.vch_no), 0) AS NUMERIC), 2) AS avg_value_per_invoice
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type) = 'sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername
        ORDER BY avg_value_per_dealer DESC {limit_clause}
    """, qp)


def q46_zero_sales_items(userid, params=None):
    # AN2. SKUs with zero secondary sales this month vs last month
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        WITH last_month AS (
            SELECT DISTINCT itm.itemcode, itm.itemdescription AS item_name, td.itemid
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            JOIN itemmaster itm ON itm.itemid = td.itemid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
              AND td.vch_date < DATE_TRUNC('month', CURRENT_DATE)
        ),
        this_month AS (
            SELECT DISTINCT td.itemid
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE)
        )
        SELECT lm.itemcode, lm.item_name
        FROM last_month lm
        LEFT JOIN this_month tm ON tm.itemid = lm.itemid
        WHERE tm.itemid IS NULL
        {limit_clause}
    """, qp)


def q47_sales_per_active_dealer(userid, params=None):
    # AN3. Avg secondary sales value per active dealer per distributor
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT td.dealerid) AS active_dealers,
               SUM(td.billed_value) AS total_value,
               ROUND(CAST(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.dealerid), 0) AS NUMERIC), 2) AS sales_per_active_dealer
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type) = 'sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername
        ORDER BY sales_per_active_dealer DESC {limit_clause}
    """, qp)


def q48_single_order_dealers(userid, params=None):
    # AN4. Dealers with only 1 order this month
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_monthly_parallel(f"""
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name,
               ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT td.vch_no) AS invoice_count,
               SUM(td.billed_value) AS total_billed_value
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        LEFT JOIN ledgermaster dln ON dln.ledgerid = td.dealerid
        WHERE LOWER(td.trn_type) = 'sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY dln.ledgercode, dln.ledgername, ds.ledgercode, ds.ledgername
        HAVING COUNT(DISTINCT td.vch_no) = 1
        ORDER BY total_billed_value ASC {limit_clause}
    """, qp)


def q49_dealer_pareto(userid, params=None):
    # AN5. Pareto / 80-20 — % value from top 20% dealers
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_monthly_parallel(f"""
        WITH dealer_sales AS (
            SELECT td.dealerid, SUM(td.billed_value) AS dealer_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
            GROUP BY td.dealerid
        ),
        ranked AS (
            SELECT dealer_value, NTILE(5) OVER (ORDER BY dealer_value DESC) AS quintile
            FROM dealer_sales
        )
        SELECT quintile,
               COUNT(*) AS dealer_count,
               SUM(dealer_value) AS total_value,
               ROUND(CAST(SUM(dealer_value) * 100.0 / NULLIF(SUM(SUM(dealer_value)) OVER (), 0) AS NUMERIC), 2) AS value_pct
        FROM ranked
        GROUP BY quintile ORDER BY quintile
    """, qp)


def q50_new_dealer_activations(userid, params=None):
    # AN6. New dealers billed for the first time this month
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        WITH first_bill AS (
            SELECT td.dealerid, MIN(td.vch_date) AS first_bill_date
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
            GROUP BY td.dealerid
        )
        SELECT dln.ledgercode AS dl_code, dln.ledgername AS dealer_name, fb.first_bill_date
        FROM first_bill fb
        LEFT JOIN ledgermaster dln ON dln.ledgerid = fb.dealerid
        WHERE DATE_TRUNC('month', fb.first_bill_date) = DATE_TRUNC('month', CURRENT_DATE)
        ORDER BY fb.first_bill_date DESC {limit_clause}
    """, qp)


def q51_declining_distributors(userid, params=None):
    # AN7. Distributors that have NOT grown vs last month
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        WITH growth AS (
            SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
                   SUM(CASE WHEN DATE_TRUNC('month', td.vch_date) = DATE_TRUNC('month', CURRENT_DATE) THEN td.billed_value ELSE 0 END) AS current_value,
                   SUM(CASE WHEN DATE_TRUNC('month', td.vch_date) = DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' THEN td.billed_value ELSE 0 END) AS last_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
            GROUP BY ds.ledgercode, ds.ledgername
        )
        SELECT ds_code, ds_name, last_value, current_value,
               ROUND(CAST((current_value - last_value) / NULLIF(last_value, 0) * 100 AS NUMERIC), 2) AS mom_growth_pct
        FROM growth
        WHERE current_value < last_value
        ORDER BY mom_growth_pct ASC {limit_clause}
    """, qp)


def q52_sales_per_dealer_per_day(userid, params=None):
    # AN8. Sales per active dealer per day (productivity metric)
    p = params or {}; df = _date_filter("td.vch_date", p); rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_monthly_parallel(f"""
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               COUNT(DISTINCT td.dealerid) AS active_dealers,
               COUNT(DISTINCT CAST(td.vch_date AS DATE)) AS active_days,
               SUM(td.billed_value) AS total_value,
               ROUND(CAST(SUM(td.billed_value) / NULLIF(COUNT(DISTINCT td.dealerid) * COUNT(DISTINCT CAST(td.vch_date AS DATE)), 0) AS NUMERIC), 2) AS value_per_dealer_per_day
        FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = td.distributorid AND ds.ledgertype = 1
        WHERE LOWER(td.trn_type) = 'sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE {df}
        GROUP BY ds.ledgercode, ds.ledgername
        ORDER BY value_per_dealer_per_day DESC {limit_clause}
    """, qp)


def q53_rolling_velocity_trend(userid, params=None):
    # AN9. Rolling 3M vs 6M average sales velocity trend
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    return run_query(f"""
        WITH monthly AS (
            SELECT DATE_TRUNC('month', td.vch_date) AS sale_month, SUM(td.billed_value) AS month_value
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '5 months'
            GROUP BY DATE_TRUNC('month', td.vch_date)
        )
        SELECT to_char(sale_month, 'YYYY-MM') AS sale_month, month_value,
               ROUND(CAST(AVG(month_value) OVER (ORDER BY sale_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS NUMERIC), 2) AS rolling_3m_avg,
               ROUND(CAST(AVG(month_value) OVER (ORDER BY sale_month ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS NUMERIC), 2) AS rolling_6m_avg
        FROM monthly
        ORDER BY sale_month
    """, qp)


def q54_lost_item_distributor(userid, params=None):
    # AN10. Item-distributor combos with zero sales 2+ months but had sales before
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    return run_query(f"""
        WITH recent_sales AS (
            SELECT DISTINCT td.distributorid, td.itemid
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
        ),
        historical_sales AS (
            SELECT DISTINCT td.distributorid, td.itemid
            FROM transactiondetail td
            INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
            WHERE LOWER(td.trn_type) = 'sales'
              AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
              AND td.vch_date < DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
              AND td.vch_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '6 months'
        )
        SELECT ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               itm.itemcode, itm.itemdescription AS item_name
        FROM historical_sales h
        LEFT JOIN recent_sales r ON r.distributorid = h.distributorid AND r.itemid = h.itemid
        JOIN ledgermaster ds ON ds.ledgerid = h.distributorid AND ds.ledgertype = 1
        JOIN itemmaster itm ON itm.itemid = h.itemid
        WHERE r.distributorid IS NULL
        ORDER BY ds.ledgername, itm.itemdescription {limit_clause}
    """, qp)


SECONDARY_SALES_FLAGS = {
    "ss:monthly-total":      (q1_monthly_total,      "Total secondary sales value + quantity this month"),
    "ss:by-item-last-week":  (q2_by_item_last_week,  "Secondary sales by item for last week"),
    "ss:vs-target":          (q3_vs_target,          "Actual secondary sales by distributor this month"),
    "ss:top5-items-quarter": (q4_top5_items_quarter, "Top 5 items by secondary sales this quarter"),
    "ss:top-dealers":        (q5_top_dealers,        "Top dealers by secondary sales this month"),
    "ss:trend-3m":           (q6_trend_3m,           "Secondary sales trend last 3 months"),
    "ss:growth":             (q7_growth,             "Secondary sales growth vs last month"),
    "ss:by-category":        (q8_by_category,        "Secondary sales by product category this month"),
    "ss:by-so":              (q9_by_so,              "Secondary sales for specific SO this month [ASM+]"),
    "ss:team-by-so":         (q10_team_by_so,        "Team secondary sales by SO this week [ASM+]"),
    "ss:top-so":             (q11_top_so,            "SO with highest secondary sales this month [ASM+]"),
    "ss:by-distributor":     (q12_by_distributor,    "Distributor-wise secondary sales for region [RSM+]"),
    "ss:compare-areas":      (q13_compare_areas,     "Compare secondary sales across all areas [RSM+]"),
    "ss:zone-quarter":       (q14_zone_quarter,      "Zone-wise secondary sales this quarter [ZSM+]"),
    "ss:national":           (q15_national,          "Total national secondary sales this month [NSM]"),
    "ss:monthly-summary":    (q16_monthly_summary,   "Month-wise secondary sales summary (no per-distributor)"),
    "ss:fast-total":         (q20_fast_total,        "Fast single-period secondary sales value + qty (no GROUP BY)"),
    "ss:compare-periods":    (q17_compare_periods,   "Compare secondary sales across two date ranges side by side"),
    "ss:custom-top":         (q18_custom_top,        "Custom top-N secondary sales grouped by any column (item/dealer/distributor)"),
    "ss:filtered":               (q19_filtered,             "Filtered secondary sales aggregate (filter by any column + value)"),
    "ss:distributor-monthly":    (q21_distributor_monthly,  "Secondary sales breakdown by distributor AND month (cross-tab)"),
    "ss:year-to-date":           (q22_year_to_date,        "Secondary sales year-to-date from April 1st (FYTD)"),
    "ss:quarterly-summary":      (q23_quarterly_summary,   "Quarter-wise secondary sales summary"),
    "ss:avg-invoice":            (q24_avg_invoice,         "Average value per secondary invoice"),
    "ss:cumulative-monthly":     (q25_cumulative_monthly,  "Running cumulative secondary sales month by month"),
    "ss:returns":                (q26_returns,             "Secondary credit notes / returns analysis"),
    "ss:growth-monthly":         (q27_growth_monthly,      "Month-over-month secondary sales growth percentage"),
    "ss:dealer-monthly":         (q28_dealer_monthly,      "Secondary sales by dealer AND month (cross-tab)"),
    "ss:invoice-range":          (q29_invoice_range,       "Secondary invoice size distribution (slab-wise)"),
    "ss:weekday-analysis":       (q30_weekday_analysis,    "Secondary sales by day of week"),
    "ss:pareto":                 (q31_pareto,              "Pareto analysis — top N distributors covering 80% of secondary sales"),
    "ss:distributor-compare":    (q32_distributor_compare, "Compare multiple distributors side by side by IDs"),
    "ss:monthly-run-rate":       (q33_monthly_run_rate,    "Average monthly secondary sales run rate"),
    "ss:item-monthly":           (q34_item_monthly,        "Item-wise monthly secondary sales trend"),
    "ss:dealer-all":             (q35_dealer_all,          "All dealers ranked by sales volume and metrics"),
    "ss:dealer-growth":          (q36_dealer_growth,       "Per-dealer secondary sales growth over 2 periods"),
    "ss:so-monthly":             (q37_so_monthly,          "Sales officer wise monthly secondary sales breakdown"),
    "ss:so-ranking":             (q38_so_ranking,          "Sales officer ranking by secondary sales performance"),
    "ss:distributor-growth":     (q39_distributor_growth,  "Per-distributor secondary sales growth over 2 periods"),
    "ss:moving-avg-3m":          (q40_moving_avg_3m,       "3-month rolling average of secondary sales"),
    "ss:abc-analysis":           (q41_abc_analysis,        "ABC classification of distributors by secondary sales value"),
    "ss:market-share":           (q42_market_share,        "Each distributor's share of total secondary sales with rank"),
    "ss:distributor-consistency":(q43_distributor_consistency, "Distributor consistency score by active months"),
    "ss:year-on-year":           (q44_year_on_year,        "Month-by-month secondary sales vs same month last year"),
    "ss:avg-invoice-per-dealer": (q45_avg_invoice_per_dealer, "Avg invoice value per dealer per distributor (AN1)"),
    "ss:zero-sales-items":       (q46_zero_sales_items,       "SKUs with zero secondary sales this month vs last month (AN2)"),
    "ss:sales-per-active-dealer":(q47_sales_per_active_dealer, "Avg secondary sales value per active dealer per distributor (AN3)"),
    "ss:single-order-dealers":   (q48_single_order_dealers,   "Dealers with only 1 order this month (low engagement) (AN4)"),
    "ss:dealer-pareto":          (q49_dealer_pareto,          "Pareto 80-20 — % value from top 20% dealers (AN5)"),
    "ss:new-dealer-activations": (q50_new_dealer_activations, "New dealers billed for the first time this month (AN6)"),
    "ss:declining-distributors": (q51_declining_distributors, "Distributors that have NOT grown vs last month (AN7)"),
    "ss:sales-per-dealer-per-day":(q52_sales_per_dealer_per_day,"Sales per active dealer per day productivity metric (AN8)"),
    "ss:rolling-velocity-trend": (q53_rolling_velocity_trend, "Rolling 3M vs 6M average sales velocity trend (AN9)"),
    "ss:lost-item-distributor":  (q54_lost_item_distributor,  "Item-distributor combos with zero sales 2+ months but had sales before (AN10)"),
}
