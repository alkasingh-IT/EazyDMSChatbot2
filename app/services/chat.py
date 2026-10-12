"""
DMS Chat Service — routes user questions to the right DMS analytics flag,
executes the query, and generates an AI answer.
"""
import json
import logging
import datetime
from pathlib import Path
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


def _output_lang_rule(output_lang: str, output_script: str = "native") -> str:
    """Prompt block forcing the reply language and script when the user picked an override."""
    script_mode = (output_script or "native").strip().lower()
    if script_mode not in ("native", "roman"):
        script_mode = "native"

    if not output_lang or output_lang == "auto":
        if script_mode == "roman":
            return (
                "\nCRITICAL LANGUAGE & SCRIPT RULE: You MUST respond in the EXACT same language as the user. "
                "If the user asks in pure English, you MUST respond ONLY in pure English. "
                "If the user asks in an Indian language or Hinglish, respond using the Roman/Latin alphabet (transliterated). "
                "Do NOT use regional native script characters."
            )
        return (
            "\nCRITICAL LANGUAGE RULE: You MUST respond in the EXACT same language as the user. "
            "If the user asks in pure English, you MUST respond ONLY in pure English. "
            "If the user asks in Hinglish, respond in Hinglish."
        )

    label = OUTPUT_LANG_LABELS.get(output_lang, output_lang)
    short = label.split(" (", 1)[0].strip()

    script_instruction = ""
    if output_lang != "en-IN":
        if script_mode == "roman":
            script_instruction = (
                f"\nSTRICT SCRIPT REQUIREMENT — ROMAN / LATIN ALPHABET ONLY:\n"
                f"The user has explicitly selected Roman script for {short}. "
                f"You MUST write your entire response using the vocabulary, grammar, and expressions of {short}, "
                f"but write it STRICTLY transliterated into the Latin/English alphabet (Roman script). "
                f"DO NOT use native non-Latin script characters under any circumstances! "
                f"Example: write 'Aapka secondary sales data yahan hai' NOT Devanagari script.\n"
            )
        else:
            script_instruction = (
                f"\nSTRICT SCRIPT REQUIREMENT — NATIVE REGIONAL SCRIPT ONLY:\n"
                f"The user has explicitly selected Native script for {short}. "
                f"Write your response using the authentic native script of {short}.\n"
            )

    return (
        f"\nOUTPUT LANGUAGE OVERRIDE — HIGHEST PRIORITY:\n"
        f"- The user has chosen '{label}' as their preferred answer language.\n"
        f"- Write your ENTIRE response in {short} (language code {output_lang}) REGARDLESS of the language of the user's question.\n"
        f"- Numbers, currency amounts, person/dealer/distributor/item names, and codes stay exactly as they appear in the data — never translate them.\n"
        f"- Section labels (Summary / Key Numbers / Trend / Actions) must also be written in the chosen language.\n"
        f"{script_instruction}"
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


# ─────────────────────────────────────────────────────────────────────────────
# Response-shape engine (model-decided, data-validated)
# The routing LLM picks the shape alongside the flags; Python validates it
# against the EXECUTED data and only ever upgrades to the safe full format.
# The shape gates WHICH blocks render — it never supplies or alters a number.
# ─────────────────────────────────────────────────────────────────────────────

_SHAPE_KINDS = ("lookup", "comparison", "ranking", "trend", "analytical", "general")
_SHAPE_LOG_PATH = Path(__file__).resolve().parent.parent / "metadata_reports" / "shape_decisions.jsonl"


def _parse_response_shape(routing_raw: Any) -> Dict[str, Any]:
    """Extract response_shape from the routing JSON. Missing/invalid → analytical default."""
    raw = routing_raw.get("response_shape") if isinstance(routing_raw, dict) else None
    kind, reasoning = "", ""
    if isinstance(raw, dict):
        kind = str(raw.get("kind") or "").strip().lower()
        reasoning = str(raw.get("reasoning") or "").strip()[:300]
    elif isinstance(raw, str):
        kind = raw.strip().lower()
    if kind not in _SHAPE_KINDS:
        return {"kind": "analytical", "reasoning": "router gave no valid shape; defaulting", "upgraded": False}
    return {"kind": kind, "reasoning": reasoning, "upgraded": False}


def _has_time_column(cols: List[str]) -> bool:
    keys = ("date", "day", "month", "quarter", "year", "time", "period", "week")
    return any(any(k in str(c).lower() for k in keys) for c in (cols or []))


def _has_numeric_value_column(rows: List[Dict], cols: List[str]) -> bool:
    import decimal as _decimal
    for c in (cols or []):
        if c.startswith("_") or "uid" in str(c).lower():
            continue
        for r in (rows or [])[:5]:
            v = r.get(c)
            if v is None or isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) or isinstance(v, _decimal.Decimal):
                return True
            try:
                float(str(v).replace(",", "").strip())
                return True
            except Exception:
                continue
    return False


def _validate_shape_against_data(
    shape: Dict[str, Any],
    executed_data: List[Dict[str, Any]],
    flag_selection: List[str],
) -> Dict[str, Any]:
    """
    Cross-check the router's shape against the REAL executed data. Failed checks
    upgrade the shape to 'analytical' (full format) — a wrong choice can only
    degrade presentation, never emit wrong or missing data.
    """
    kind = shape.get("kind")
    if kind == "general":
        if (executed_data or flag_selection):
            return {**shape, "kind": "analytical", "upgraded": True,
                    "upgrade_reason": "general chosen but flags were selected; data must be shown"}
        return shape
    if kind == "analytical":
        return shape

    paired = [
        ((ds.get("rows_full") or ds.get("rows") or []), (ds.get("columns") or []))
        for ds in (executed_data or [])
        if isinstance(ds, dict) and not ds.get("error")
        and len(ds.get("rows") or ds.get("rows_full") or []) > 0
    ]

    def _upgrade(reason: str) -> Dict[str, Any]:
        return {**shape, "kind": "analytical", "upgraded": True, "upgrade_reason": reason}

    if kind == "comparison":
        if len(paired) < 2:
            return _upgrade(f"comparison needs ≥2 non-empty data slices; got {len(paired)}")
        return shape
    if kind == "trend":
        if not paired:
            return _upgrade("trend needs data; none returned")
        rows0, cols0 = paired[0]
        if len(rows0) < 2 or not _has_time_column(cols0):
            return _upgrade("trend needs ≥2 time-ordered rows with a time column")
        return shape
    if kind == "ranking":
        if not paired:
            return _upgrade("ranking needs data; none returned")
        rows0, cols0 = paired[0]
        if not _has_numeric_value_column(rows0, cols0) or len(rows0) < 2:
            return _upgrade("ranking needs ≥2 rows with a numeric value column")
        return shape
    if kind == "lookup":
        if len(paired) > 1 or (paired and len(paired[0][0]) > 3):
            return _upgrade("lookup expects a single small result set")
        return shape
    return shape


def _shape_rule(shape: Dict[str, Any]) -> str:
    """Answer-style block appended to the analytical system prompt."""
    kind = (shape or {}).get("kind") or "analytical"
    if kind == "lookup":
        return (
            "\n\nANSWER SHAPE FOR THIS TURN: LOOKUP — OVERRIDES the default structure choice.\n"
            "The user asked a single-fact question. Use the COMPACT STRUCTURE: the bold direct answer line plus 2-3 short supporting bullets, nothing more.\n"
            "Do NOT use the FULL STRUCTURE sections."
        )
    if kind == "comparison":
        return (
            "\n\nANSWER SHAPE FOR THIS TURN: COMPARISON — OVERRIDES the default structure choice.\n"
            "Lead with a compact markdown TABLE comparing both sides — one row per metric, one column per side "
            "(e.g. | Metric | Side A | Side B |), using ONLY figures present in the data. If a metric is missing for "
            "one side, omit that row rather than guessing.\n"
            "After the table, 3-4 lines: the difference, the % change, and which side is ahead.\n"
            "Do NOT use the FULL STRUCTURE sections (no Trend / 3 Actions lists)."
        )
    if kind == "ranking":
        return (
            "\n\nANSWER SHAPE FOR THIS TURN: RANKING — OVERRIDES the default structure choice.\n"
            "Show the top entries as a compact markdown TABLE (| # | Name | Value | Share% |), then one closing line "
            "highlighting the leader. Use ONLY names and figures from the data; never add entries that are not present.\n"
            "Do NOT use the FULL STRUCTURE sections."
        )
    if kind == "trend":
        return (
            "\n\nANSWER SHAPE FOR THIS TURN: TREND — OVERRIDES the default structure choice.\n"
            "Answer in 2-4 lines: direction, momentum, and any notable shift; the chart renders automatically as the hero.\n"
            "Do NOT use the FULL STRUCTURE sections."
        )
    return ""


def _log_shape_decision(
    question: str,
    flag_selection: List[str],
    shape: Dict[str, Any],
    uid: str,
) -> None:
    """Append the shape decision to a JSONL audit log (best-effort, never blocks)."""
    try:
        rec = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "uid": (uid or "")[:64],
            "question": (question or "")[:200],
            "flags": [str(f or "") for f in (flag_selection or [])][:8],
            "kind": shape.get("kind"),
            "reasoning": shape.get("reasoning", "")[:300],
            "upgraded": bool(shape.get("upgraded")),
            "upgrade_reason": shape.get("upgrade_reason", ""),
        }
        _SHAPE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SHAPE_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def route_question(question: str, userid: str, staff_context: Dict = None, history: List[Dict] = None, output_lang: str = 'auto', output_script: str = 'native') -> Dict[str, Any]:
    """
    Step 1 — Ask the LLM which flag (if any) best answers the question.
    Returns {"flags", "params", "direct_answer", "response_shape"} — the same
    routing call also decides the presentation kind (response-shape engine).
    """
    staff_info = ""
    raw_name = (staff_context or {}).get('name') or userid
    raw_desig = (staff_context or {}).get('designation') or 'Staff'
    is_firm = any(t in str(raw_name).upper() for t in ["TRADERS", "ENTERPRISES", "AGENCIES", "DISTRIBUTORS", "PVT LTD", "LTD", "STORE", "CENTRE", "LLP", "COMPANY"])
    if staff_context:
        firm_note = f" (Corporate Distributor Firm Entity: {raw_name})" if is_firm else ""
        staff_info = f"LOGGED-IN PROFILE: Name/Firm='{raw_name}', Designation='{raw_desig}'{firm_note}.\n"


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
        "SELECTION RULES (follow strictly):\n"
        "0. GENERAL & CONVERSATIONAL QUESTIONS — AUTONOMOUS INTELLECTUAL RESOLUTION (SELECT NO FLAGS):\n"
        "   You possess advanced natural language understanding. Autonomously analyze the user's intent. Any question that does NOT require querying specific operational database records (e.g. transactional sales numbers, order lists, inventory stock, purchase orders, claims) is a GENERAL QUESTION.\n\n"
        "   CRITICAL STEP-1 RESOLUTION RULE:\n"
        "   Whenever the user asks a general or conversational question:\n"
        "   → Select NO flags: \"flags\": []\n"
        "   → Synthesize your complete, articulate, beautifully formatted answer directly in the \"direct_answer\" field of your JSON response!\n"
        "   → Do NOT leave \"direct_answer\" empty or null for these questions.\n"
        "   → Do NOT rely on rigid keywords — use your semantic intelligence to understand the user's meaning in ANY phrasing, dialect, language, slang, or typo (English, Hindi, Hinglish in Roman script, etc.).\n\n"
        "   General Question Domains (autonomously recognize and resolve):\n"
        "   a) USER IDENTITY & PROFILE:\n"
        "      - Any question asking who they are, their name, designation, firm details, or who is logged in.\n"
        "      - Examples: 'who am I', 'mera naam kya h', 'mera naam batao', 'bhai m kaun hu', 'main kaun hoon', 'meri details', 'what is my designation', 'meri profile dikhao', 'kiske account se login hu', 'who is authenticated'.\n"
        "      - CORPORATE / DISTRIBUTOR ACCOUNT IDENTITY RULE:\n"
        "        * Look at the LOGGED-IN PROFILE above.\n"
        "        * If the Account Name represents a distributor / corporate entity (e.g. contains TRADERS, ENTERPRISES, AGENCIES, DISTRIBUTORS, PVT LTD, LTD, etc.):\n"
        "          Explain clearly and politely that they are authenticated in the DMS portal under the authorized distributor/corporate account of **{raw_name}**.\n"
        "          Mention that all primary purchases, secondary liquidation, stock movement, and claims are scoped to this entity.\n"
        "          NEVER claim or say that the user's personal human name is the corporate distributor firm!\n"
        "        * If the profile contains an individual human name, greet them warmly by their name and state their designation.\n\n"
        "   b) SYSTEM & ASSISTANT IDENTITY:\n"
        "      - Any query asking who you are, what is Eazy AI, or your purpose.\n"
        "      - Examples: 'who are you', 'tum kaun ho', 'apna parichay do', 'what is this system', 'introduce yourself', 'kya ho tum'.\n"
        "      - Explain that you are Eazy AI — the dedicated Distributor Management System (DMS) Executive Intelligence Assistant, designed to analyze distributor purchases, secondary sales liquidation, stock movement, clearance health, and claims.\n\n"
        "   c) GREETINGS, WELL-BEING & RAPPORT:\n"
        "      - Salutations, friendly check-ins, well-wishing in any natural language or slang.\n"
        "      - Examples: 'kaise ho', 'kese ho', 'kya haal hai', 'kaisa chal raha hai', 'how are you', 'how\'s it going', 'hi', 'hello', 'namaste', 'good morning', 'wassup', 'kem cho'.\n"
        "      - Respond warmly and professionally, noting that you are operating at peak analytical capacity and ready to assist with DMS operations.\n\n"
        "   d) CAPABILITIES, GUIDANCE & HELP:\n"
        "      - Asking what you can do, what questions can be asked, asking for examples.\n"
        "      - Examples: 'what can you do', 'kya kar sakte ho', 'help', 'guide', 'menu', 'sample questions', 'options dikhao'.\n"
        "      - Provide a clean, structured overview of capabilities (Secondary Sales, Primary Purchases, Stock Movement & Health, Dead Stock Clearance, Schemes & Claims) with 3-4 example questions.\n\n"
        "   e) FMCG & DMS DOMAIN CONCEPTS & DEFINITIONS:\n"
        "      - Asking to explain a business term, formula, or concept without querying specific transactional data.\n"
        "      - Examples: 'what is secondary sales', 'difference between primary and secondary sales', 'what is dead stock', 'what is stock cover', 'what is claim settlement ratio'.\n"
        "      - Provide an authoritative, clear, and concise FMCG/DMS explanation tailored for commercial and distributor leadership.\n\n"
        "   f) COURTESIES, APPRECIATION & FAREWELLS:\n"
        "      - 'thank you', 'thanks', 'dhanyawad', 'shukriya', 'great job', 'awesome', 'bye', 'good night', 'ok', 'got it', 'noted'.\n"
        "      - Respond graciously and invite them to ask their next business question whenever ready.\n\n"
        "   STYLING OF direct_answer:\n"
        "   - Use clean markdown with **bold** text and bullet points.\n"
        "   - Respect the requested language and script.\n"
        f"{_output_lang_rule(output_lang, output_script)}\n\n"
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
        "CRITICAL — TWO-PERIOD COMPARISON QUESTIONS (\"q1 vs q2\", \"this month vs last month\", \"Q1 2025 vs Q2 2025\", "
        "\"compare X and Y periods\"):\n"
        "- ALWAYS use the module's -compare-periods flag (ss:compare-periods / pur:compare-periods / pr:compare-periods) "
        "with FOUR params: date_from_1, date_to_1, date_from_2, date_to_2 (period 1 and period 2, YYYY-MM-DD).\n"
        "- Example: 'secondary sales q1 vs q2 2025' → flag ss:compare-periods, params "
        "{\"date_from_1\": \"2025-01-01\", \"date_to_1\": \"2025-03-31\", \"date_from_2\": \"2025-04-01\", \"date_to_2\": \"2025-06-30\"}.\n"
        "- NEVER route a comparison to -monthly-summary, -summary or full-year dates — those answer ONE period, not two.\n"
        "\n"
        "SPECIAL PARAM CHEAT-SHEET — use the EXACT param names below; ALWAYS pass entity names exactly as the user wrote them:\n"
        "- Entity lookups — pass the NAME (or code) the user mentioned, never invent an internal ID:\n"
        "  * mst:distributor-detail → {\"distributor_name\": \"<name or code>\"}\n"
        "  * mst:item-detail → {\"item_name\": \"<name or code>\"} (optionally division_name)\n"
        "  * sch:scheme-details → {\"scheme_name\": \"<name or code>\"}\n"
        "  * clm:status → {\"claim_no\": \"<claim number>\"} (or claim_id)\n"
        "  * pur:item-history → {\"item_name\": \"<item name or code>\"} (or item_id)\n"
        "  * combined:distributor-snapshot / combined:distributor-deep → {\"distributor_name\": \"<name>\"} (or distributor_id)\n"
        "- Comparing TWO or more distributors → ss:/pur:/pr:distributor-compare with "
        "{\"distributor_names\": \"Name A, Name B\"} (or distributor_ids) plus date_from/date_to.\n"
        "- Top-N by a specific grouping (custom-top flags) → {\"group_col\": \"ds_name|dealer_name|item_name|item_group|item_division\", "
        "\"metric\": \"billed_value|billed_qty\", \"order\": \"desc|asc\", \"limit\": N}. "
        "e.g. 'top 5 distributors by quantity' → ss:custom-top with group_col=ds_name, metric=billed_qty.\n"
        "- by-category flags → optional {\"category_column\": \"item_group|item_division\"}.\n"
        "- filtered flags → {\"filter_col\": \"<column>\", \"filter_op\": \"=|>|<|>=|<=|LIKE\", \"filter_val\": \"<value>\"}.\n"
        "- sm:closing-stock / sm:stock-statement → optional {\"group_by\": \"distributor|zone|state|item\"}; "
        "sm:stock-cover → optional {\"cover_type\": \"low|overstock\"}; sm:misc-adjustments → optional {\"adj_type\": \"in|out\"}.\n"
        "- Flags marked 'this month' / 'current month' in their description ALWAYS answer the CURRENT month "
        "regardless of dates — never pick them for a historical period.\n"
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
        "\n"
        "RESPONSE SHAPE — how the answer should be PRESENTED (decide carefully):\n"
        "In the SAME JSON you return, also add a \"response_shape\" describing what KIND of\n"
        "answer the user's question needs. Judge the question's INTENT with your own\n"
        "semantic understanding (any language, any phrasing) — do NOT pattern-match keywords.\n"
        "Choose exactly ONE kind:\n"
        "- \"general\"    : needs NO operational data (greeting, identity, concept explanation, help, courtesy).\n"
        "- \"lookup\"     : a single fact or a small set of figures, nothing more (one period's total, one count, one distributor's number).\n"
        "- \"comparison\" : the question EXPLICITLY compares TWO concrete things — two periods (Q1 vs Q2, this month vs last month) or two named distributors/items. In \"reasoning\" you MUST name BOTH things being compared. A breakdown list or a broad overview is NOT a comparison.\n"
        "- \"trend\"      : asks HOW something evolves over time (month-wise, day-wise, over the last 6 months) and the time axis is the hero.\n"
        "- \"ranking\"    : asks for ordering / best / worst / top-N (\"which distributor is highest\", \"top 5 items\", \"who has the most\").\n"
        "- \"analytical\" : everything else — synthesis, overview, multi-part questions, or whenever you are genuinely unsure. Uncertainty ALWAYS defaults here.\n"
        "Rules:\n"
        "- Always include response_shape (never null, never missing).\n"
        "- The kind must be supported by the flags you selected: for trend, the selected flags must return time-wise data; for comparison, both sides must be answerable from your selected flags.\n"
        "- Only the PRESENTATION type is decided here. Never invent or alter any data in this field.\n\n"
        "Return ONLY valid JSON with keys:\n"
        "  - flags: array of strings (empty [] if general question)\n"
        "  - params: object (applied to ALL flags)\n"
        "  - direct_answer: string (full markdown answer if general question, null/empty if flags are selected)\n"
        "  - response_shape: object {\"kind\": \"lookup|comparison|ranking|trend|analytical|general\", \"reasoning\": \"<one short line>\"}\n\n"
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
        return {"flags": [], "params": {}, "response_shape": {"kind": "analytical", "reasoning": "routing returned non-dict; defaulting", "upgraded": False}}
    flags = result.get("flags")
    if isinstance(flags, str):
        flags = [flags]
    if not isinstance(flags, list):
        flags = [result.get("flag")] if result.get("flag") else []

    direct_ans = (result.get("direct_answer") or "").strip()
    shape = _parse_response_shape(result)
    logger.info(
        "\033[1;35m[DECODED ROUTING INTENT]\033[0m Decoded Flags: \033[1;32m%s\033[0m | Decoded Params: \033[1;36m%s\033[0m | Has Direct Answer: %s | Shape: %s",
        flags, result.get("params") or {}, bool(direct_ans), shape.get("kind")
    )
    return {"flags": flags, "params": result.get("params") or {}, "direct_answer": direct_ans, "response_shape": shape}


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


def build_answer_prompts(
    question: str,
    flag: str,
    execution: Dict[str, Any],
    staff_context: Dict = None,
    history: List[Dict] = None,
    multi_flags: List[str] = None,
    scope_suggestions: List[str] = None,
    output_lang: str = "auto",
    output_script: str = "native",
    shape: Dict[str, Any] = None,
) -> tuple:
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
        + _output_lang_rule(output_lang, output_script)
        + _shape_rule(shape)
    )

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
    return system, user


def generate_answer(
    question: str,
    flag: str,
    execution: Dict[str, Any],
    staff_context: Dict = None,
    history: List[Dict] = None,
    multi_flags: List[str] = None,
    scope_suggestions: List[str] = None,
    output_lang: str = "auto",
    output_script: str = "native",
    shape: Dict[str, Any] = None,
) -> str:
    system, user = build_answer_prompts(
        question, flag, execution, staff_context, history, multi_flags, scope_suggestions, output_lang, output_script, shape
    )
    ans = call_llm_text(system=system, user=user)
    name = (staff_context or {}).get("name", "there")
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
