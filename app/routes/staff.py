"""
DMS Staff Route — lists available staff users from location_access_detail.
GET  /api/staff  — list all distinct userids (for the staff selector)
"""
from fastapi import APIRouter
from ..db import run_query, allow_default_db

router = APIRouter(prefix="/api")


@router.get("/staff")
async def list_staff():
    """Return all staff users available in location_access_detail.

    Public master-list helper used by the chat's staff selector. There is no
    per-user session for this call, so it is an EXPLICIT, read-only exception
    allowed to use the default DB.
    """
    allow_default_db.set(True)
    result = run_query("""
        SELECT DISTINCT
            u.id AS userid,
            u.username,
            COALESCE(e.employeename, u.description, u.username) AS name,
            COALESCE(e.employeecode, '') AS employee_code,
            COALESCE(d.designationname, '') AS designation,
            COALESCE(u.email, e.email, '') AS email,
            COALESCE(u.mobile, e.presentcontactno, '') AS mobile
        FROM location_access_detail lad
        JOIN sec_usermaster u ON u.id = lad.userid
        LEFT JOIN hr_employeemaster e ON e.employeeid = u.employeeid
        LEFT JOIN designationmaster d ON d.designationid = e.designationid
        ORDER BY name
    """, {})

    if result.get("error"):
        # Fallback: just return userids without join
        result2 = run_query("""
            SELECT DISTINCT userid FROM location_access_detail ORDER BY userid LIMIT 200
        """, {})
        staff = [
            {
                "userid": str(r.get("userid", "")),
                "username": str(r.get("userid", "")),
                "name": str(r.get("userid", "")),
                "employee_code": "",
                "designation": "",
                "email": "",
                "mobile": ""
            }
            for r in (result2.get("rows") or [])
        ]
        return {"staff": staff}

    staff = []
    for r in (result.get("rows") or []):
        staff.append({
            "userid": str(r.get("userid", "")),
            "username": str(r.get("username") or ""),
            "name": str(r.get("name") or r.get("userid", "")),
            "employee_code": str(r.get("employee_code") or ""),
            "designation": str(r.get("designation") or ""),
            "email": str(r.get("email") or ""),
            "mobile": str(r.get("mobile") or ""),
        })
    return {"staff": staff}
