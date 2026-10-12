"""
DMS Chat Service — routes user questions to the right DMS analytics flag,
executes the query, and generates an AI answer.
"""
import json
import logging
import datetime
from typing import Any, Dict, List, Optional

from .llm import call_llm_json, call_llm_text
from .enrich import build_analytical_context, format_for_llm
try:
    from .user_prefs import OUTPUT_LANG_LABELS
except (ImportError, AttributeError):
    OUTPUT_LANG_LABELS = {
        "auto":  "Auto — match question",
        "en-IN": "English",
        "hi-IN": "हिन्दी Hindi",
        "ta-IN": "தமிழ் Tamil",
        "te-IN": "తెలుగు Telugu",
        "kn-IN": "ಕನ್ನಡ Kannada",
        "ml-IN": "മലയാളം Malayalam",
        "mr-IN": "मराठी Marathi",
        "bn-IN": "বাংলা Bengali",
        "gu-IN": "ગુજરાતી Gujarati",
        "pa-IN": "ਪੰਜਾਬੀ Punjabi",
        "ur-IN": "اردو Urdu",
    }
from ..analytics import ALL_FLAGS


def _output_lang_rule(output_lang: str) -> str:
    """Prompt block forcing the reply language when the user picked one."""
    if not output_lang or output_lang == "auto":
        return (
            "\nLANGUAGE:\n"
            "- Detect the language of the user's question and respond in the SAME language.\n"
            "- NEVER mix languages unexpectedly — stay consistent within each reply.\n"
        )
    label = OUTPUT_LANG_LABELS.get(output_lang, output_lang)
    return (
        f"\nOUTPUT LANGUAGE OVERRIDE — HIGHEST PRIORITY:\n"
        f"- The user has chosen '{label}' as their preferred answer language.\n"
        f"- Write your ENTIRE response in {label.split(' ')[-1] if ' ' in label else label} "
        f"(language code {output_lang}) REGARDLESS of the language of the user's question.\n"
        f"- Numbers, currency amounts, person/dealer/item names, and codes stay exactly as they appear in the data — never translate them.\n"
        f"- Section labels (Summary / Key Numbers / Trend / Actions) must also be written in the chosen language.\n"
    )


def _build_date_reference(today: datetime.date) -> str:
    """Pre-compute all common date ranges so the routing LLM never has to guess."""
    from datetime import timedelta

    def fy_start(d: datetime.date) -> datetime.date:
        # Indian financial year starts April 1st
        return datetime.date(d.year if d.month >= 4 else d.year - 1, 4, 1)

    month_start = datetime.date(today.year, today.month, 1)
    first_last = month_start - timedelta(days=1)
    last_m_start = datetime.date(first_last.year, first_last.month, 1)
    this_week_from = today - timedelta(days=today.weekday())
    last_week_from = this_week_from - timedelta(days=7)
    last_week_to = this_week_from - timedelta(days=1)
    q = (today.month - 1) // 3
    this_q_from = datetime.date(today.year, q * 3 + 1, 1)
    lq = q - 1
    lq_year = today.year if lq >= 0 else today.year - 1
    lq_month = (lq % 4) * 3 + 1
    last_q_from = datetime.date(lq_year, lq_month, 1)
    last_q_to = this_q_from - timedelta(days=1)
    fys = fy_start(today)
    return "\n".join([
        "DATE REFERENCE TABLE — use EXACTLY these values for date params, never compute your own:",
        f"Today              : {today.isoformat()}",
        f"Yesterday          : {(today - timedelta(days=1)).isoformat()}",
        f"This week          : {this_week_from.isoformat()} -> {today.isoformat()}",
        f"Last week          : {last_week_from.isoformat()} -> {last_week_to.isoformat()}",
        f"Last 7 days        : {(today - timedelta(days=6)).isoformat()} -> {today.isoformat()}",
        f"Last 30 days       : {(today - timedelta(days=29)).isoformat()} -> {today.isoformat()}",
        f"Last 90 days       : {(today - timedelta(days=89)).isoformat()} -> {today.isoformat()}",
        f"This month (MTD)   : {month_start.isoformat()} -> {today.isoformat()}",
        f"Last month         : {last_m_start.isoformat()} -> {first_last.isoformat()}",
        f"This quarter       : {this_q_from.isoformat()} -> {today.isoformat()}",
        f"Last quarter       : {last_q_from.isoformat()} -> {last_q_to.isoformat()}",
        f"This FY year-to-date (Apr 1) : {fys.isoformat()} -> {today.isoformat()}",
        f"Last month same span is NOT needed — always pick a row above.",
    ])


# Build a compact flag menu for the routing prompt
def _build_flag_menu() -> str:
    lines = []
    for flag, (fn, desc) in ALL_FLAGS.items():
        module = flag.split(":")[0] if ":" in flag else ""
        if module == "pur": prefix = "[PUR] "
        elif module == "ss": prefix = "[SS] "
        elif module == "pr": prefix = "[PR] "
        elif module == "sc": prefix = "[SC] "
        elif module == "sm": prefix = "[SM] "
        elif module == "sch": prefix = "[SCH] "
        elif module == "clm": prefix = "[CLM] "
        elif module == "mst": prefix = "[MST] "
        elif module == "combined": prefix = "[ALL] "
        else: prefix = ""
        lines.append(f'  "{flag}": "{prefix}{desc}"')
    return "{\n" + ",\n".join(lines) + "\n}"


FLAG_MENU = _build_flag_menu()


def route_question(question: str, userid: str, staff_context: Dict = None, history: List[Dict] = None) -> Dict[str, Any]:
    """
    Step 1 — Ask the LLM which flag (if any) best answers the question.
    Returns {"flag": str, "params": dict} or {"flag": null} for general chat.
    """
    staff_info = ""
    if staff_context:
        staff_info = f"You are assisting: {staff_context.get('name')} ({staff_context.get('designation', 'Staff')}).\n"

    # Extract previous topic from last assistant message for continuity
    prev_topic = ""
    if history:
        for t in reversed(history):
            if t.get("role") == "assistant":
                content = (t.get("content") or "").lower()
                if any(w in content for w in ["purchase", "purchases", "pur:"]):
                    prev_topic = " [PREVIOUS TOPIC: Purchases]"
                elif any(w in content for w in ["secondary sales", "ss:", "sales data", "items sold"]):
                    prev_topic = " [PREVIOUS TOPIC: Secondary Sales]"
                elif any(w in content for w in ["primary sales", "pr:", "primary inflow"]):
                    prev_topic = " [PREVIOUS TOPIC: Primary Sales]"
                elif any(w in content for w in ["stock clearance", "dead stock", "slow stock", "sc:", "clearance", "expiry", "ageing"]):
                    prev_topic = " [PREVIOUS TOPIC: Stock Clearance]"
                elif any(w in content for w in ["stock movement", "stock inflow", "stock outflow", "sm:", "inflow", "outflow", "net movement", "stagnant"]):
                    prev_topic = " [PREVIOUS TOPIC: Stock Movement]"
                elif any(w in content for w in ["scheme", "schemes", "sch:", "promotion", "free stock"]):
                    prev_topic = " [PREVIOUS TOPIC: Schemes]"
                elif any(w in content for w in ["claim", "claims", "clm:", "rejection", "aging report"]):
                    prev_topic = " [PREVIOUS TOPIC: Claims]"
                elif any(w in content for w in ["master", "masters", "mst:", "distributor detail", "dealer list"]):
                    prev_topic = " [PREVIOUS TOPIC: Masters]"
                break

    history_txt = ""
    if history:
        turns = []
        for t in history[-6:]:
            role = "User" if t.get("role") == "user" else "Assistant"
            txt = t.get("content", "")[:200]
            turns.append(f"{role}: {txt}")
        history_txt = "Recent conversation:\n" + "\n".join(turns) + "\n\n"

    today = datetime.date.today()
    system = (
        "You are a routing assistant for a Distributor Management System (DMS) analytics platform.\n"
        f"{staff_info}"
        f"Today's date is {today.isoformat()} ({today.strftime('%B %Y')}).\n"
        f"{history_txt}"
        "IMPORTANT — DATA SCOPE: All data returned by this system is already limited to what this user is allowed to see. "
        "This includes: (1) areas and distributors directly assigned to them, AND "
        "(2) areas and distributors assigned to anyone in their team — direct reportees, their reportees, and so on, all the way down the chain. "
        "In short: they see their own work + the work of their entire team below them. "
        "When the user says 'all sales', 'entire data', 'everyone', 'whole country', 'my team data', or similar — "
        "they mean everything within this combined scope. Route normally; do NOT treat it as an out-of-scope request.\n"
        "Given a user question and the conversation history above, select the BEST analytics flag(s) from the list below.\n"
        "Read flag descriptions carefully. The [PUR]/[SS]/[PR]/[SC]/[SM]/[ALL] prefix tells you the module.\n"
        "CRITICAL MODULE DISAMBIGUATION — [SC] vs [SM] — READ CAREFULLY:\n"
        "- [SC] = Stock CLEARANCE — use for questions about dead stock, slow-moving stock, stock health, expiry risk, "
        "clearance recommendations, ageing items, scheme suggestions, transfer routes, and recovery potential. "
        "Data comes from the AI-computed 'stock_clearance_recommendations' table. "
        "Keywords: dead stock, slow stock, expiry, clearance, ageing, stock health, transfer recommendation, scheme.\n"
        "- [SM] = Stock MOVEMENT — use for questions about raw transactional stock flow: inflow, outflow, purchases, "
        "net movement, stagnant distributors, inflow vs outflow comparison, and stock accumulation vs sales velocity. "
        "Data comes from live 'transactiondetail' transaction records. "
        "Keywords: stock movement, inflow, outflow, net stock, stock flow, stagnant, purchase vs sales ratio, stock accumulation.\n"
        "NEVER mix [SC] and [SM] flags in the same response unless the user explicitly asks for both topics together.\n"
        "CRITICAL: If the user is just greeting, thanking, or making casual conversation (\"hi\", \"hello\", \"thanks\", \"good morning\"), "
        "return {\"flags\": []}. Those are NOT analytics questions.\n"
        "CRITICAL: Use the conversation history to infer months, modules, or context the user didn't re-state. "
        f"E.g., if the previous question was about 'purchases for march' and now they say 'month wise data', route to purchases monthly-summary with March dates.{prev_topic}\n"
        "When the user asks for 'breakdown' or 'overview', select up to 2 complementary lightweight flags — "
        "prefer the -summary flag plus one -by-* flag (e.g., monthly-summary + by-category). "
        "NEVER include flags ending in -monthly (distributor-monthly, item-monthly, category-monthly) — "
        "those are extremely slow on full-year ranges because they GROUP BY month.\n"
        "DATE RESOLUTION RULES — MANDATORY:\n"
        "- When the user asks for a specific month/date/period, include date_from and date_to in params (YYYY-MM-DD format).\n"
        "- Use the DATE REFERENCE TABLE below to pick EXACT from_date/to_date values — never compute dates yourself.\n"
        "- 'this month' / 'current month' / 'MTD' → This month (MTD) row. 'last month' → Last month row.\n"
        "- 'this quarter' / 'last quarter' / 'YTD' / 'year to date' → matching row from the table.\n"
        "- If the user names an explicit month (e.g. 'March'), use its first and last calendar day of the CURRENT year unless they say otherwise.\n\n"
        f"{_build_date_reference(today)}\n\n"
        "If none of the flags are relevant, return {\"flags\": []}.\n"
        "Return ONLY valid JSON with keys: flags (array of strings, at least 1 if relevant), params (object, applied to ALL flags).\n\n"
        f"Available flags:\n{FLAG_MENU}"
    )
    logger = logging.getLogger("dms.chat")
    staff_name = (staff_context or {}).get("name", userid)
    staff_desig = (staff_context or {}).get("designation", "Staff")
    logger.info(
        "\033[1;33m[SYSTEM UNDERSTOOD]\033[0m Processing question: '\033[1;37m%s\033[0m' | User ID: \033[1;33m%s\033[0m | User: %s (%s)",
        question, userid, staff_name, staff_desig
    )

    user = f"User question: {question}"
    result = call_llm_json(system=system, user=user)

    if not isinstance(result, dict):
        logger.warning("\033[1;31m[ROUTING FAIL]\033[0m Routing returned non-dict for '%s': %s", question[:80], result)
        return {"flags": [], "params": {}}
    flags = result.get("flags")
    if isinstance(flags, str):
        flags = [flags]
    if not isinstance(flags, list):
        flags = [result.get("flag")] if result.get("flag") else []

    logger.info(
        "\033[1;35m[DECODED ROUTING INTENT]\033[0m Decoded Flags: \033[1;32m%s\033[0m | Decoded Params: \033[1;36m%s\033[0m",
        flags, result.get("params") or {}
    )
    return {"flags": flags, "params": result.get("params") or {}}


_FALLBACK_SUGGESTIONS = [
    "What were my secondary sales this month?",
    "Show top distributors by secondary sales value",
    "Give me a category-wise secondary sales breakdown",
    "Show me purchase summary for this month",
    "What is the total dead stock value across my distributors?",
    "What are the top 5 urgent stock clearance actions today?",
    "Which items have recommended stock transfers in my area?",
    "Show me discount scheme recommendations for dead stock",
]

# (module, probe SQL template, suggested questions) — probed against the user's
# RBAC scope so we only suggest questions for modules that actually have data.
_SUGGESTION_PROBES = [
    (
        "ss",
        """
        SELECT COUNT(*) AS n FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='sales'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
        """,
        [
            "What were my secondary sales this month?",
            "Show top dealers by secondary sales value",
            "Give me a category-wise secondary sales breakdown",
            "What is my secondary sales growth vs last month?",
            "Show secondary sales trend for last 3 months",
        ],
    ),
    (
        "pur",
        """
        SELECT COUNT(*) AS n FROM transactiondetail td
        INNER JOIN ({rbac}) accd ON accd.locationid = td.distributorid
        WHERE LOWER(td.trn_type)='purchase'
          AND td.iscancelled IS DISTINCT FROM TRUE AND td.isdeleted IS DISTINCT FROM TRUE
        """,
        [
            "Show me purchase summary for this month",
            "What are the top purchased items in my area?",
            "Show distributor-wise purchase summary",
            "Which distributor has the highest purchase volume?",
            "Show purchase trend for the last 6 months",
        ],
    ),
    (
        "pr",
        """
        SELECT COUNT(*) AS n FROM sale_salesinvoice si
        INNER JOIN ({rbac}) accd ON accd.locationid = si.distributorid
        WHERE si.iscancelled = FALSE
        """,
        [
            "Show primary sales overview for this month",
            "What is the primary vs secondary sales ratio?",
            "Top products by primary inflow this quarter",
            "Show primary sales by distributor",
        ],
    ),
    (
        "sc",
        """
        SELECT COUNT(*) AS n FROM ai_output.stock_clearance_recommendations sc
        LEFT JOIN ledgermaster lm ON lm.ledgercode = sc.distributor_code
        INNER JOIN ({rbac}) accd ON accd.locationid = COALESCE(sc.distributor_ledger_id, lm.ledgerid)
        """,
        [
            "What is the total dead stock value across my distributors?",
            "What are the top 5 urgent stock clearance actions today?",
            "Which items have recommended stock transfers in my area?",
            "Show me discount scheme recommendations for dead stock",
            "Which items are on seasonal hold (HOLD_FOR_SEASON)?",
            "Which items are facing critical expiry risk?",
        ],
    ),
]


def get_scope_suggestions(userid: str = "", db_uid: str = None) -> List[str]:
    """Return relevant suggested business questions for DMS scope when queries return no data.

    Probes each data module (secondary sales / purchases / primary sales) within the
    user's RBAC scope and only suggests questions for modules that actually have rows,
    so users never get pointed at empty areas of their own data.
    Falls back to a static list if probing fails.
    """
    import random
    try:
        from ..db import run_query
        from ..analytics._rbac import rbac_clause, build_params

        suggestions: List[str] = []
        params = {"_db_uid": db_uid} if db_uid else {}
        qp_base = build_params(userid, params)
        for _module, sql_tpl, templates in _SUGGESTION_PROBES:
            try:
                res = run_query(sql_tpl.format(rbac=rbac_clause(params)), qp_base)
                count = 0
                if res.get("rows"):
                    count = int(res["rows"][0].get("n") or 0)
                if count > 0:
                    picks = random.sample(templates, min(2, len(templates)))
                    suggestions.extend(picks)
            except Exception:
                continue
        if not suggestions:
            return random.sample(_FALLBACK_SUGGESTIONS, min(5, len(_FALLBACK_SUGGESTIONS)))
        random.shuffle(suggestions)
        return suggestions[:6]
    except Exception as exc:
        logging.getLogger("dms.chat").warning("[SUGGESTIONS] probe failed (%s) — using static list", exc)
        return random.sample(_FALLBACK_SUGGESTIONS, min(5, len(_FALLBACK_SUGGESTIONS)))


def generate_answer(question: str, flag: str, execution: Dict[str, Any], staff_context: Dict = None, history: List[Dict] = None, multi_flags: List[str] = None, scope_suggestions: List[str] = None, output_lang: str = "auto") -> str:
    """
    Step 2 — Generate a natural-language answer from the query result.
    multi_flags: list of flag names when multiple were executed for one answer.
    """
    rows = execution.get("rows") or []
    cols = execution.get("columns") or []
    row_count = execution.get("row_count", 0)
    descriptions = execution.get("descriptions", [])

    safe_rows = rows[:40]

    history_txt = ""
    if history:
        turns = []
        for t in history[-4:]:
            role = "User" if t.get("role") == "user" else "Assistant"
            turns.append(f"{role}: {t['content'][:200]}")
        history_txt = "\n".join(turns) + "\n\n"

    staff_info = ""
    name = (staff_context or {}).get("name", "there")
    designation = (staff_context or {}).get("designation", "")
    if staff_context:
        staff_info = f"The user you are helping is {name}"
        if designation:
            staff_info += f", {designation}"
        staff_info += ".\n"

    # Build flag context for answer generation
    if multi_flags and len(multi_flags) > 1:
        flag_list_str = ", ".join(multi_flags)
        flag_context = (
            f"Multiple analytics flags were queried: {flag_list_str}. "
            "Each row has a '_flag' field showing which flag produced it. "
            "Use the combined data to give a comprehensive answer covering all angles."
        )
    else:
        flag_context = f"Analytics flag used: {flag}"

    is_aggregated = any(col.startswith(("total_", "sum_", "avg_", "count_", "growth_", "change_")) for col in cols)
    detail_flag = flag.endswith(("this-month", "last-30d", "pending", "item-history"))
    if detail_flag and not is_aggregated and rows:
        total_val = 0
        for row in rows:
            for c in row:
                if any(k in c.lower() for k in ["value","amount","total","billed"]):
                    try: total_val += float(row[c]) if row[c] is not None else 0
                    except: pass
                    break
        safe_rows = [{"summary": f"Showing {len(rows)} of {row_count} detail rows", "total_value": round(total_val, 2)}]
        is_aggregated = True
        agg_note = f"NOTE: Detail query — {row_count} total rows, showing {len(rows)}. Computed sample total: {round(total_val, 2)}. Only give a high-level summary."
    else:
        agg_note = (
            'NOTE: The data is already AGGREGATED (totals, sums, counts). Use these values directly.'
            if is_aggregated else
            'NOTE: RAW/SAMPLE rows. Give ONLY a high-level summary: total rows, date range, and a brief summary of the first 2-3 rows. NEVER list individual rows.'
        )

    module_hint = "The flag prefix tells you the module: pur=Purchase, ss=Secondary Sales, pr=Primary Sales, sc=Stock Clearance, combined=Combined."

    system = (
        f"You are a friendly and professional business analytics assistant for a Distributor Management System.\n"
        f"{staff_info}"
        f"You are helping {name} — a business user, NOT a technical person.\n"
        "Your job is to explain sales and business data in simple, plain business language.\n"
        "\n"
        "CRITICAL — DATA SCOPE AWARENESS:\n"
        "Every figure you are given covers exactly what this user is entitled to see as a business person: "
        "(1) the areas, distributors, and territories directly assigned to them, PLUS "
        "(2) everything assigned to their team — their direct reportees, those reportees' teams, and so on down the hierarchy. "
        "Think of it as: their own business + the entire business of everyone working under them. "
        "You must NEVER mention or hint at how this works. Simply treat all the data as this person's natural business view.\n"
        "- When presenting totals or summaries, use phrases like: 'your sales', 'across your area', "
        "  'your team's purchases', 'in your territory', 'for your distributors'. "
        "  NEVER say 'all sales', 'total company data', or anything implying a broader company-wide view.\n"
        "- If a user says 'show me my team's data', 'what is my area doing', 'give me all', 'everyone's numbers' — "
        "  these all mean the same thing: their scope. Present the data confidently as their complete business view.\n"
        "- If a user asks for data clearly outside their scope (e.g. a specific region they don't manage, "
        "  another person's individual figures, a national rollup they shouldn't see) and the result is limited or empty, "
        "  say warmly: 'Those figures are outside your current area. For a wider view, you may want to check with your manager.' "
        "  NEVER use words like 'access', 'permissions', 'restricted', 'role', 'system limit', 'filter'.\n"
        "- If the result is empty or very limited when the user expected data, say: "
        "  'It looks like there's no activity recorded in your area for this period. "
        "  You may want to confirm with your team if this is expected.' — NEVER say 'no records found' or '0 rows'.\n"
        "\n"
        "STRICT LANGUAGE RULES:\n"
        "- NEVER mention technical words like: SQL, query, database, flag, JSON, columns, API, error, stack trace, exception, timeout, system, server, code, null, undefined, index, RBAC, role-based, access control, filter, permissions.\n"
        "- NEVER show raw numbers without context — always say what they mean (e.g. '₹45L in secondary sales' not just '4500000').\n"
        "- ALWAYS refer to distributors, items, dealers, and salespersons by their full NAME (e.g. 'Apex Distributors', 'Product ABC', 'Rajesh Sharma'), NEVER by numeric IDs. If a code is present, you may include it in parentheses (e.g. 'Apex Distributors (DS001)').\n"
        "- NEVER expose any errors or failures to the user. If something went wrong, say 'I wasn't able to pull that information right now. Please try again in a moment.' and nothing else.\n"
        "- Address the user warmly by their first name.\n"
        "- Write like a smart business colleague giving a quick briefing — confident, concise, and clear.\n"
        "- Use ₹ in Lakhs (₹1L) or Crores (₹1Cr) for amounts.\n"
        "- Only use data from the rows shown. NEVER invent items, names, or numbers.\n"
        "- If the data note says 'AGGREGATED', use the totals as-is — they are the real totals.\n"
        "- If the data note says 'RAW/SAMPLE', say 'Showing X of Y records' and briefly summarize the first 2-3.\n"
        "- When multiple data sources were used, weave the insights into one cohesive business summary.\n"
        "\n"
        "OUTPUT FORMAT RULES:\n"
        "- If RAW DATA rows or AUTHORITATIVE FACTS are present, ALWAYS use them. Never ignore real data.\n"
        "\n"
        "CLASSIFY FIRST — LENGTH OF THE QUESTION DOES NOT DECIDE THE FORMAT:\n"
        "- Any question that touches business data — totals, summaries, sales, purchases, trends, comparisons, "
        "rankings, lists, performance — is a BROAD DATA question, EVEN IF ASKED IN ONE SHORT LINE "
        "(e.g. 'secondary sales this month?', 'purchase summary', 'top dealers?', 'show my primary sales'). "
        "Data answers always need an overview. Use the FULL STRUCTURE for them.\n"
        "- Only single-fact lookups (one specific value: highest/count/growth%/one entity's total) use the COMPACT STRUCTURE.\n"
        "- Only pure greetings, thanks, or small-talk get a plain conversational reply with no structure.\n"
        "- NEVER reduce a data answer to bare unformatted text.\n"
        "\n"
        "FULL STRUCTURE — for every BROAD DATA question:\n"
        "  **�� One-line Summary:** The single most important insight + its number.\n"
        "  **�� Key Numbers:** Critical metrics as a tight markdown table. Call out best and worst performer BY NAME (never by ID).\n"
        "  **�� Trend:** Direction + root-cause hypothesis. Flag anomalies only if significant.\n"
        "  **✅ 3 Actions:** Exactly 3 recommended actions, each in the form: **Action** → because [data point].\n"
        "  End with one helpful follow-up suggestion the user might ask next.\n"
        "\n"
        "COMPACT STRUCTURE — ONLY for single-fact lookups ('which distributor is highest?', 'what was the total?', "
        "'how many invoices?', 'what is the growth %?'):\n"
        "  Line 1: **Bold direct answer** with the key figure and period (e.g. '**D001 — ₹45.20L** (97% of purchases this month)').\n"
        "  Lines 2-4: two or three short supporting bullets from AUTHORITATIVE FACTS (vs previous period, share of total, runner-up).\n"
        "  Last line: one follow-up starting with 'Ask me next:'.\n"
        "  Maximum 6 lines — but NEVER a single bare sentence.\n"
        "\n"
        "- When multiple data sources report different totals for the same thing, prefer the per-entity breakdown "
        "(by-distributor / by-item / by-month rows) over merged summary totals — sum the breakdown rows as the true total.\n"
        + _output_lang_rule(output_lang)
    )

    # Pre-LLM enrichment: totals, growth, top/bottom performers computed in Python
    facts_block = ""
    if row_count > 0:
        try:
            enrich_ctx = build_analytical_context(question, execution)
            facts_block = format_for_llm(enrich_ctx)
        except Exception as exc:
            logging.getLogger("dms.chat").warning("[ENRICH] enrichment failed: %s", exc)

    if row_count == 0 and scope_suggestions:
        system += (
            f"\n\n[SYSTEM NOTE: No activity was found in this user's area for the requested period. "
            f"Do NOT say 'permission denied', 'access denied', 'RBAC', 'scope', or 'no records found'. "
            f"In ONE warm, short sentence tell the user nothing was found in their area for this period. "
            f"Do NOT list example questions yourself and do not add any other sections — "
            f"the system automatically appends clickable suggestions after your reply.]"
        )
    user = (
        f"{history_txt}"
        f"User question:\n{question}\n\n"
        f"{flag_context}\n"
        f"Result columns: {cols}\n"
        f"Total rows in result: {row_count}\n"
        f"{module_hint}\n"
        f"{agg_note}\n"
        + (f"{facts_block}\n\n" if facts_block else "")
        + f"Rows shown to you:\n{json.dumps(safe_rows, ensure_ascii=False, default=str)}"
    )
    ans = call_llm_text(system=system, user=user)
    logger = logging.getLogger("dms.chat")
    logger.info(
        "\033[1;32m[SYSTEM ANSWER GENERATED]\033[0m User: %s | Length: %d chars | Preview: '\033[1;37m%.150s...\033[0m'",
        name, len(ans), ans.replace("\n", " ")
    )
    return ans



def generate_general_answer(question: str, history: List[Dict] = None, staff_context: Dict = None, output_lang: str = "auto") -> str:
    """Fallback general-chat answer when no flag matches."""
    history_txt = ""
    if history:
        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            history_txt += f"{role.upper()}: {content}\n"

    name = (staff_context or {}).get("name", "there")

    profile_lines = []
    if staff_context:
        if staff_context.get('name'):         profile_lines.append(f"Name: {staff_context['name']}")
        if staff_context.get('designation'):  profile_lines.append(f"Designation: {staff_context['designation']}")
        if staff_context.get('username'):     profile_lines.append(f"Username: {staff_context['username']}")
        if staff_context.get('employee_code'):profile_lines.append(f"Employee Code: {staff_context['employee_code']}")
        if staff_context.get('email'):        profile_lines.append(f"Email: {staff_context['email']}")
        if staff_context.get('mobile'):       profile_lines.append(f"Mobile: {staff_context['mobile']}")
    profile_block = "\n".join(profile_lines)

    system = (
        f"You are a friendly and professional business analytics assistant for a Distributor Management System.\n"
        f"You are talking to {name} — a business user, NOT a technical person.\n"
        f"Their profile:\n{profile_block}\n\n"
        "Your tone should be warm, confident, and professional — like a knowledgeable business colleague.\n"
        "\n"
        "CRITICAL — DATA SCOPE AWARENESS:\n"
        "This user's business view covers: their own assigned territory and distributors, "
        "PLUS everything assigned to their team — direct reportees and their teams all the way down. "
        "Their 'allowed data' is their personal work combined with their entire team's work beneath them. "
        "You must NEVER explain or hint at this. Treat it as simply the natural scope of their business.\n"
        "- If they ask 'can I see all data?', 'why don't I see other areas?', or similar: "
        "  say 'The information shown here covers your area and your team. "
        "  If you need figures beyond that, please speak with your manager.' "
        "  NEVER say 'access', 'permissions', 'restricted', 'filter', 'role-based', 'system'.\n"
        "- If they say 'show me all', 'my team's data', 'entire territory', 'everyone below me', or similar — "
        "  treat it as 'show me everything in my business scope' and respond accordingly.\n"
        "- If they ask about a specific subordinate's area or their team's performance, that is within scope — answer it naturally.\n"
        "\n"
        "STRICT RULES:\n"
        "- NEVER mention technical words: SQL, database, query, API, JSON, server, error, system, code, null, undefined, exception, RBAC, access control, permissions, filter, role.\n"
        "- NEVER expose any errors or system problems. If something is unclear, just say you didn't quite catch that and ask them to rephrase.\n"
        "- If they ask about their own profile details (email, mobile, designation), answer directly from the profile above.\n"
        "- Address the user warmly by their first name.\n"
        "- If a question is about business data, guide them on what they can ask — e.g. 'You can ask me about your secondary sales, purchases, or primary inflows for any month.'\n"
        "- Keep answers short and to the point. Use plain business English.\n"
        "- Respond in the same language the user is writing in.\n"
        + _output_lang_rule(output_lang)
    )
    user = (
        (f"Conversation so far:\n{history_txt}\n\n" if history_txt else "")
        + f"User question:\n{question}"
    )
    ans = call_llm_text(system=system, user=user)
    logger = logging.getLogger("dms.chat")
    logger.info(
        "\033[1;32m[SYSTEM GENERAL ANSWER GENERATED]\033[0m Preview: '\033[1;37m%.150s...\033[0m'",
        ans.replace("\n", " ")
    )
    return ans


def suggest_chart(question: str, execution: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest chart_type, x-column, y-column for the result set."""
    cols = execution.get("columns") or []
    rows = (execution.get("rows") or [])[:30]
    if not cols or not rows:
        return {}

    system = (
        "You are a data visualization assistant. "
        "Given the user question and result columns/rows, suggest the best chart.\n"
        "Return ONLY JSON: {\"chart_type\": \"bar|line|pie\", \"x\": \"<col>\", \"y\": \"<col>\"}\n"
        "Use 'pie' for ≤6 categorical segments. 'line' for time trends. 'bar' otherwise.\n"
        "x and y MUST be existing column names."
    )
    user = (
        f"Question: {question}\n"
        f"Columns: {cols}\n"
        f"Sample rows: {json.dumps(rows, default=str)}"
    )
    spec = call_llm_json(system=system, user=user)
    logger = logging.getLogger("dms.chat")
    if not isinstance(spec, dict):
        logger.info("\033[1;33m[DECODED LAYOUT]\033[0m No valid chart spec returned by LLM")
        return {}
    ct = (spec.get("chart_type") or "").lower()
    x = spec.get("x", "")
    y = spec.get("y", "")
    if ct not in {"bar", "line", "pie"} or x not in cols or y not in cols:
        logger.info("\033[1;33m[DECODED LAYOUT]\033[0m Chart spec candidate rejected: %s (cols=%s)", spec, cols)
        return {}

    logger.info(
        "\033[1;35m[DECODED LAYOUT]\033[0m Chart Type: \033[1;33m%s\033[0m | X-Axis: '\033[1;36m%s\033[0m' | Y-Axis: '\033[1;36m%s\033[0m' | Columns: %s | Sample Rows: %d",
        ct, x, y, cols, len(rows)
    )
    return {"chart_type": ct, "x": x, "y": y, "rows": rows}

