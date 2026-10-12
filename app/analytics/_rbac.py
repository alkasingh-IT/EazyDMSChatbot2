"""Shared RBAC helper with UUID / User ID support."""
from typing import Optional


def rbac_clause(params: Optional[dict] = None) -> str:
    return (
        "SELECT DISTINCT lad.locationid "
        "FROM location_access_detail lad "
        "WHERE lad.userid = :userid_int "
        "OR EXISTS ("
        "    SELECT 1 FROM sec_usermaster u "
        "    WHERE u.id = lad.userid AND CAST(u.userguid AS TEXT) = :userid"
        ")"
    )


def needs_userid(params: Optional[dict] = None) -> bool:
    return True


import re

def build_params(userid: str, params: Optional[dict] = None) -> dict:
    p = params or {}
    qp = {}

    # 0. Preserve internal DB-routing key so run_query/run_monthly_parallel
    #    can route to the correct registered tenant DB even after params are
    #    sanitised.  _db_uid is never forwarded to PostgreSQL (stripped by
    #    _sql_params / _convert_params in db.py / async_db.py).
    if p.get("_db_uid"):
        qp["_db_uid"] = p["_db_uid"]

    # 1. Sanitize dates (strict YYYY-MM-DD format check)
    for date_key in ("date_from", "date_to"):
        v = str(p.get(date_key) or "").strip()
        if v and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            qp[date_key] = v

    # 2. Sanitize identifiers/columns (alphanumeric and underscore only, max 64 chars)
    for col_key in ("category_column", "fy_start"):
        v = str(p.get(col_key) or "").strip()
        if v and re.match(r"^[a-zA-Z0-9_]{1,64}$", v):
            qp[col_key] = v

    # 3. Sanitize integers (limit, item_id, so_userid)
    for int_key in ("limit", "item_id", "so_userid"):
        v = p.get(int_key)
        if v is not None:
            try:
                val = int(v)
                if int_key == "limit":
                    val = max(1, min(val, 5000))
                qp[int_key] = val
            except (ValueError, TypeError):
                pass

    # 4. User ID binding
    uid_str = str(userid or "").strip()
    qp["userid"] = uid_str
    try:
        qp["userid_int"] = int(uid_str)
    except (ValueError, TypeError):
        qp["userid_int"] = -1

    return qp


# Standard master table joins (Ledger, Dealer, Item, Group, Division, Employee, City, State, Zone)
MASTER_JOINS = """
JOIN ledgermaster ds
  ON ds.ledgerid = td.distributorid
 AND ds.ledgertype = 1
LEFT JOIN ledgermaster dln
  ON dln.ledgerid = td.dealerid
JOIN itemmaster itm
  ON itm.itemid = td.itemid
LEFT JOIN itemgroup itmg
  ON itmg.itemgroupid = itm.groupid
LEFT JOIN tbl_divisionmaster dvm
  ON dvm.divisionid = itm.division
LEFT JOIN hr_employeemaster emp
  ON emp.employeeid = ds.salespersonid
LEFT JOIN citymaster c2
  ON c2.cityid = ds.cityid
LEFT JOIN statemaster s2
  ON s2.stateid = c2.stateid
LEFT JOIN zonemaster z2
  ON z2.zoneid = ds.zoneid
"""

MASTER_JOINS_DS = """
JOIN ledgermaster ds
  ON ds.ledgerid = td.distributorid
 AND ds.ledgertype = 1
LEFT JOIN hr_employeemaster emp
  ON emp.employeeid = ds.salespersonid
LEFT JOIN citymaster c2
  ON c2.cityid = ds.cityid
LEFT JOIN statemaster s2
  ON s2.stateid = c2.stateid
LEFT JOIN zonemaster z2
  ON z2.zoneid = ds.zoneid
"""

MASTER_JOINS_ITM = """
JOIN itemmaster itm
  ON itm.itemid = td.itemid
LEFT JOIN itemgroup itmg
  ON itmg.itemgroupid = itm.groupid
LEFT JOIN tbl_divisionmaster dvm
  ON dvm.divisionid = itm.division
"""

MASTER_JOINS_DLN = """
LEFT JOIN ledgermaster dln
  ON dln.ledgerid = td.dealerid
"""

