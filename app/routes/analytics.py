import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from ..analytics import ALL_FLAGS

router = APIRouter(prefix="/api/analytics")
logger = logging.getLogger("dms.analytics")


class ExecuteRequest(BaseModel):
    userid: str
    flag: str
    params: Optional[Dict[str, Any]] = {}


class GroupRequest(BaseModel):
    user_ids: List[str]
    flag: str
    params: Optional[Dict[str, Any]] = {}


@router.post("/execute")
async def execute_flag(req: ExecuteRequest, request: Request):
    logger.info(
        "\033[1;36m[ANALYTICS EXECUTE REQUEST]\033[0m Flag: \033[1;32m%s\033[0m | User ID: \033[1;33m%s\033[0m | Params: %s",
        req.flag, req.userid, req.params
    )
    entry = ALL_FLAGS.get(req.flag)
    if not entry:
        return {"error": f"Unknown flag: {req.flag}", "rows": [], "columns": [], "row_count": 0}
    fn, description = entry
    db_uid = request.headers.get("u-uid") or request.headers.get("x-uid")
    params = {**(req.params or {}), "_db_uid": db_uid} if db_uid else (req.params or {})
    result = fn(req.userid, params)
    result["flag"] = req.flag
    result["description"] = description
    logger.info(
        "\033[1;35m[DECODED ANALYTICS LAYOUT]\033[0m Flag: %s | Columns: %s | Total Rows: %d",
        req.flag, result.get("columns", []), result.get("row_count", 0)
    )
    return result


@router.post("/group")
async def group_execute(req: GroupRequest, request: Request):
    """Execute the same flag for multiple user IDs."""
    logger.info(
        "\033[1;36m[ANALYTICS GROUP EXECUTE REQUEST]\033[0m Flag: \033[1;32m%s\033[0m | User IDs: %s | Params: %s",
        req.flag, req.user_ids, req.params
    )
    entry = ALL_FLAGS.get(req.flag)
    if not entry:
        return {"error": f"Unknown flag: {req.flag}", "rows": [], "columns": [], "row_count": 0}
    fn, description = entry
    db_uid = request.headers.get("u-uid") or request.headers.get("x-uid")
    p = {**(req.params or {}), "_db_uid": db_uid} if db_uid else (req.params or {})
    all_rows = []
    all_cols = []
    for uid in req.user_ids:
        r = fn(uid.strip(), {**p, "group_uid": uid.strip()})
        if r.get("error"):
            continue
        if not all_cols:
            all_cols = r.get("columns", [])
        for row in (r.get("rows") or []):
            row["_userid"] = uid.strip()
            all_rows.append(row)
    if all_rows and "_userid" not in all_cols:
        all_cols = ["_userid"] + all_cols
    logger.info(
        "\033[1;35m[DECODED GROUP ANALYTICS LAYOUT]\033[0m Flag: %s | Columns: %s | Total Rows: %d",
        req.flag, all_cols, len(all_rows)
    )
    return {"rows": all_rows, "columns": all_cols, "row_count": len(all_rows),
            "flag": req.flag, "description": description, "error": None}


@router.get("/flags")
async def list_flags():
    return {
        "flags": [
            {"flag": k, "description": v[1]}
            for k, v in ALL_FLAGS.items()
        ]
    }
