"""
DMS Masters Analytics Module.
Covers Distributor Master, Item Master, Dealer/Retailer Master, and Territory Master lookups.
Fully RBAC-enforced across SO/ASM/RSM/ZSM/NSM levels.
"""
from typing import Optional, Dict, Any
from ..db import run_query
from ._rbac import rbac_clause, build_params


def _mst_filters(params: dict) -> str:
    clauses = []
    if params.get("zone_id"):
        clauses.append("AND zm.zoneid = :zone_id")
    if params.get("state_id"):
        clauses.append("AND sm.stateid = :state_id")
    if params.get("city_id"):
        clauses.append("AND cm.cityid = :city_id")
    return " ".join(clauses)


def mst_distributor_detail(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Details of distributor by name or code (in-scope only)."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    search = p.get("distributor_code") or p.get("distributor_name") or p.get("query") or ""
    qp["search"] = f"%{search}%"
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    mf = _mst_filters(p)
    return run_query(f"""
        SELECT lm.ledgerid AS distributorid, lm.ledgercode AS ds_code, lm.ledgername AS ds_name,
               cm.cityname AS city, zm.zonename AS zone, sm.statename AS state,
               lm.address, lm.phone, lm.email, lm.isactive
        FROM ledgermaster lm
        INNER JOIN ({rbac}) accd ON accd.locationid = lm.ledgerid
        LEFT JOIN citymaster cm ON cm.cityid = lm.cityid
        LEFT JOIN zonemaster zm ON zm.zoneid = lm.zoneid
        LEFT JOIN statemaster sm ON sm.stateid = lm.stateid
        WHERE (lm.ledgercode ILIKE :search OR lm.ledgername ILIKE :search) {mf}
        ORDER BY lm.ledgername {limit_clause}
    """, qp)


def mst_item_detail(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Details of item/SKU by code, name, or division."""
    p = params or {}; qp = build_params(userid, p)
    search = p.get("item_code") or p.get("item_name") or p.get("query") or ""
    qp["search"] = f"%{search}%"
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    cat_filter = "AND dvm.divisionname = :division_name" if p.get("division_name") else ""
    return run_query(f"""
        SELECT im.itemid, im.itemcode, COALESCE(im.itemdescription, im.itemname) AS item_name,
               dvm.divisionname AS item_division, itmg.groupname AS item_group,
               im.uom, im.mrp, im.purchase_rate, im.isactive
        FROM itemmaster im
        LEFT JOIN itemgroup itmg ON itmg.itemgroupid = im.groupid
        LEFT JOIN tbl_divisionmaster dvm ON dvm.divisionid = im.division
        WHERE (im.itemcode ILIKE :search OR im.itemdescription ILIKE :search OR im.itemname ILIKE :search OR dvm.divisionname ILIKE :search) {cat_filter}
        ORDER BY im.itemcode {limit_clause}
    """, qp)


def mst_dealer_list(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """List of all dealers/retailers under my assigned distributors."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    mf = _mst_filters(p)
    return run_query(f"""
        SELECT DISTINCT COALESCE(dln.ledgercode, dm.dl_code) AS dl_code,
               COALESCE(dln.ledgername, dm.alias) AS dealer_name,
               ds.ledgercode AS ds_code, ds.ledgername AS ds_name,
               cm.cityname AS city, zm.zonename AS zone
        FROM transactiondetail dm
        INNER JOIN ({rbac}) accd ON accd.locationid = dm.distributorid
        JOIN ledgermaster ds ON ds.ledgerid = dm.distributorid AND ds.ledgertype = 1
        LEFT JOIN ledgermaster dln ON dln.ledgerid = dm.dealerid
        LEFT JOIN citymaster cm ON cm.cityid = dln.cityid
        LEFT JOIN zonemaster zm ON zm.zoneid = dln.zoneid
        WHERE dm.dealerid IS NOT NULL AND dm.iscancelled IS DISTINCT FROM TRUE AND dm.isdeleted IS DISTINCT FROM TRUE {mf}
        ORDER BY dealer_name {limit_clause}
    """, qp)


def mst_active_distributors(userid: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """List of all active distributors in my assigned hierarchy scope."""
    p = params or {}; rbac = rbac_clause(p); qp = build_params(userid, p)
    limit_clause = f"LIMIT {int(p['limit'])}" if p.get("limit") else ""
    mf = _mst_filters(p)
    return run_query(f"""
        SELECT DISTINCT lm.ledgerid AS distributorid, lm.ledgercode AS ds_code, lm.ledgername AS ds_name,
               cm.cityname AS city, zm.zonename AS zone
        FROM ledgermaster lm
        INNER JOIN ({rbac}) accd ON accd.locationid = lm.ledgerid
        LEFT JOIN citymaster cm ON cm.cityid = lm.cityid
        LEFT JOIN zonemaster zm ON zm.zoneid = lm.zoneid
        WHERE lm.isactive IS DISTINCT FROM FALSE {mf}
        ORDER BY lm.ledgername {limit_clause}
    """, qp)


MASTERS_FLAGS = {
    "mst:distributor-detail":  (mst_distributor_detail,  "Details of distributor by name or code (in-scope only)"),
    "mst:item-detail":         (mst_item_detail,         "Details of item/SKU by code, name, or division"),
    "mst:dealer-list":         (mst_dealer_list,         "List of all dealers/retailers under my assigned distributors"),
    "mst:active-distributors": (mst_active_distributors, "List of all active distributors in my assigned hierarchy scope"),
}
