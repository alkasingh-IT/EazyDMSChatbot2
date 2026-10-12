"""
=============================================================================
  DMS DATABASE LOAD TESTER — Real Application Flag Benchmarker (200 Queries)
  Metrics: Latency Distribution (P50/P75/P90/P95/P99), Throughput, CPU/RAM, Flag Stats
=============================================================================
"""

import os, sys, time, threading, statistics, json, csv, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure app package is importable
app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

try:
    import psutil
except ImportError:
    os.system(f"{sys.executable} -m pip install psutil -q")
    import psutil

try:
    from app.analytics import ALL_FLAGS
except ImportError:
    # Fallback import if running inside app directory
    from analytics import ALL_FLAGS

# Force target DB URL for load test execution
DB_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/dms_mdh"
os.environ["DATABASE_URL"] = DB_URL
try:
    from services.database import save_session_db_url
    save_session_db_url("1", DB_URL)
except Exception:
    try:
        from app.services.database import save_session_db_url
        save_session_db_url("1", DB_URL)
    except Exception:
        pass

TOTAL_QUERIES       = 200          # total flag queries to execute
CONCURRENCY         = 200          # 200 parallel Python threads — mirrors real API concurrency
MAX_DB_CONNECTIONS  = 50           # semaphore cap — matches db.py pool_size(30) + max_overflow(20)
                                   # 200 threads compete; 50 hold DB slots; 150 queue in Python
BATCH_DELAY_SEC     = 0.02         # 20 ms stagger between submissions (smooth CPU ramp)
METRICS_INTERVAL    = 0.2          # CPU/RAM sampling interval (seconds)
OUTPUT_DIR          = os.path.join(os.path.dirname(__file__), "load_test_results")


# Real RBAC enforced — exact same execution path as production
SAMPLE_PARAMS = {
    "date_from": "2025-01-01",
    "date_to": "2025-01-31",
    "year": "2025",
    "month": "1",
    "userid": "1",
}


# Collect active flags
ALL_KEYS = list(ALL_FLAGS.keys())
# Focus on high-frequency analytics flags for high-concurrency stress testing
FAST_FLAG_SUBSET = [k for k in ALL_KEYS if any(sub in k for sub in ["summary", "monthly", "total", "category", "by-so", "top", "growth", "trend"])]
FLAG_KEYS = FAST_FLAG_SUBSET if FAST_FLAG_SUBSET else ALL_KEYS


C_RESET  = "\033[0m"
C_GREEN  = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_RED    = "\033[1;31m"
C_CYAN   = "\033[1;36m"
C_MAGENTA= "\033[1;35m"
C_BLUE   = "\033[1;34m"
C_WHITE  = "\033[1;37m"

def clr(text, c): return f"{c}{text}{C_RESET}"
def banner(msg, c=C_CYAN): print(f"\n{c}{'='*70}\n  {msg}\n{'='*70}{C_RESET}")
def hdr(msg):  print(f"\n{C_BLUE}{'-'*60}\n  {msg}\n{'-'*60}{C_RESET}")

class SystemMetricsSampler:
    def __init__(self, interval: float = 0.2):
        self.interval = interval
        self._stop    = threading.Event()
        self.cpu_samples: list  = []
        self.ram_samples: list  = []
        self._thread  = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.cpu_samples.append(psutil.cpu_percent(interval=None))
                mem = psutil.virtual_memory()
                self.ram_samples.append(mem.percent)
            except Exception:
                pass
            time.sleep(self.interval)

    def summary(self) -> dict:
        def _s(lst):
            if not lst:
                return {"min": 0, "max": 0, "avg": 0, "p95": 0}
            s = sorted(lst)
            return {
                "min": round(min(s), 2),
                "max": round(max(s), 2),
                "avg": round(statistics.mean(s), 2),
                "p95": round(s[int(len(s) * 0.95)], 2),
            }
        return {
            "cpu": _s(self.cpu_samples),
            "ram": _s(self.ram_samples),
        }

def run_single_flag(query_id: int, flag_name: str, fn, desc: str) -> dict:
    t0  = time.perf_counter()
    ts  = datetime.now().isoformat(timespec="milliseconds")
    tid = threading.get_ident()
    result = {
        "query_id":   query_id,
        "thread_id":  tid,
        "timestamp":  ts,
        "flag":       flag_name,
        "desc":       desc[:60],
        "status":     "ok",
        "rows":       0,
        "latency_ms": 0,
        "error":      None,
    }
    try:
        # Call the real application analytics flag function
        res = fn("1", SAMPLE_PARAMS)
        if isinstance(res, dict):
            if res.get("error"):
                result["status"] = "error"
                result["error"]  = str(res["error"])[:300]
            else:
                result["rows"]   = res.get("row_count", len(res.get("rows", [])))
        else:
            result["rows"] = len(res) if hasattr(res, "__len__") else 0
    except Exception as e:
        result["status"] = "error"
        result["error"]  = str(e)[:300]
    finally:
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return result

# DB connection semaphore — hard cap on simultaneous PG connections
_DB_SEMAPHORE = threading.Semaphore(MAX_DB_CONNECTIONS)


def run_load_test() -> list:
    all_queries = []
    num_flags = len(FLAG_KEYS)
    for i in range(TOTAL_QUERIES):
        flag_name = FLAG_KEYS[i % num_flags]
        fn, desc = ALL_FLAGS[flag_name]
        all_queries.append((i + 1, flag_name, fn, desc))

    hdr(
        f"Executing {TOTAL_QUERIES} Real Analytics Flag Queries "
        f"| Workers = {CONCURRENCY}  | Max DB Connections = {MAX_DB_CONNECTIONS}"
    )
    print(f"  Available Real Flags : {num_flags} flags")
    print(f"  Concurrency (threads): {CONCURRENCY}")
    print(f"  DB connection cap    : {MAX_DB_CONNECTIONS}  (semaphore)")
    print(f"  Submission delay     : {BATCH_DELAY_SEC * 1000:.0f} ms between tasks")

    results    = [None] * TOTAL_QUERIES
    completed  = 0
    lock       = threading.Lock()

    def _task(args):
        nonlocal completed
        qid, flag_name, fn, desc = args
        # Acquire semaphore before touching the DB
        with _DB_SEMAPHORE:
            r = run_single_flag(qid, flag_name, fn, desc)
        with lock:
            completed += 1
            if completed % 20 == 0 or completed == TOTAL_QUERIES:
                pct = completed / TOTAL_QUERIES * 100
                status_icon = clr("✔", C_GREEN) if r["status"] == "ok" else clr("✘", C_RED)
                print(
                    f"  {status_icon} [PROGRESS] {completed}/{TOTAL_QUERIES} ({pct:.1f}%) "
                    f"| last: {r['flag']} {r['latency_ms']:.0f}ms",
                    flush=True,
                )
        return qid - 1, r

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {}
        for q in all_queries:
            # Small delay between submissions to spread CPU/IO load
            time.sleep(BATCH_DELAY_SEC)
            futures[pool.submit(_task, q)] = q[0]
        for f in as_completed(futures):
            idx, res = f.result()
            results[idx] = res

    return results

def calc_stats(results: list, wall_time: float) -> dict:
    latencies = [r["latency_ms"] for r in results if r]
    errors    = [r for r in results if r and r["status"] == "error"]
    ok_count  = len(results) - len(errors)

    def pct(lst, p):
        if not lst: return 0
        s = sorted(lst)
        return round(s[int(len(s) * p / 100)], 2)

    flag_breakdown = {}
    for r in results:
        if r:
            fg = r["flag"]
            if fg not in flag_breakdown:
                flag_breakdown[fg] = {"count": 0, "errors": 0, "latencies": []}
            flag_breakdown[fg]["count"] += 1
            if r["status"] == "error":
                flag_breakdown[fg]["errors"] += 1
            flag_breakdown[fg]["latencies"].append(r["latency_ms"])

    for fg, d in flag_breakdown.items():
        lats = d["latencies"]
        d["avg_ms"] = round(statistics.mean(lats), 2) if lats else 0
        d["max_ms"] = round(max(lats), 2) if lats else 0

    return {
        "total_queries":    len(results),
        "successful":       ok_count,
        "failed":           len(errors),
        "error_rate_pct":   round(len(errors) / max(len(results), 1) * 100, 2),
        "wall_time_sec":    round(wall_time, 3),
        "throughput_qps":   round(ok_count / wall_time, 2) if wall_time > 0 else 0,
        "latency_ms": {
            "min":    round(min(latencies), 2) if latencies else 0,
            "max":    round(max(latencies), 2) if latencies else 0,
            "mean":   round(statistics.mean(latencies), 2) if latencies else 0,
            "median": round(statistics.median(latencies), 2) if latencies else 0,
            "p50":    pct(latencies, 50),
            "p75":    pct(latencies, 75),
            "p90":    pct(latencies, 90),
            "p95":    pct(latencies, 95),
            "p99":    pct(latencies, 99),
        },
        "flag_breakdown": flag_breakdown,
        "errors": [{"query_id": e["query_id"], "flag": e["flag"], "error": e["error"]} for e in errors[:10]],
    }

def print_report(stats: dict, sys_metrics: dict):
    banner("🚀  REAL DMS ANALYTICS FLAGS LOAD TEST — FINAL REPORT", C_CYAN)
    hdr("Query Performance")
    lm = stats["latency_ms"]
    tput_str = f"{stats['throughput_qps']} queries/sec"
    err_rate_str = f"{stats['error_rate_pct']}%"
    wall_str = f"{stats['wall_time_sec']}s"

    print(f"  Total Queries   : {stats['total_queries']}")
    print(f"  Successful      : {clr(stats['successful'], C_GREEN)}")
    print(f"  Failed          : {clr(stats['failed'], C_RED if stats['failed'] > 0 else C_GREEN)}")
    print(f"  Error Rate      : {clr(err_rate_str, C_RED if stats['failed'] > 0 else C_GREEN)}")
    print(f"  Wall Time       : {clr(wall_str, C_YELLOW)}")
    print(f"  Throughput      : {clr(tput_str, C_CYAN)}")
    print(f"\n  Latency Distribution (ms)")
    print(f"    Min     : {lm['min']} ms")
    print(f"    Max     : {lm['max']} ms")
    print(f"    Mean    : {lm['mean']} ms")
    print(f"    P50     : {lm['p50']} ms")
    print(f"    P75     : {lm['p75']} ms")
    print(f"    P90     : {lm['p90']} ms")
    print(f"    P95     : {clr(str(lm['p95']), C_YELLOW)} ms")
    print(f"    P99     : {clr(str(lm['p99']), C_RED)} ms")

    hdr("System Resource Usage")
    cpu = sys_metrics["cpu"]
    ram = sys_metrics["ram"]
    print(f"  CPU Usage  -> avg: {cpu['avg']}%  |  max: {cpu['max']}%  |  p95: {cpu['p95']}%")
    print(f"  RAM Usage  -> avg: {ram['avg']}%  |  max: {ram['max']}%  |  p95: {ram['p95']}%")

    if stats.get("flag_breakdown"):
        hdr("Top Flag Execution Times")
        sorted_flags = sorted(stats["flag_breakdown"].items(), key=lambda x: x[1]["avg_ms"], reverse=True)[:10]
        for fg, d in sorted_flags:
            err_lbl = clr(f" ({d['errors']} errs)", C_RED) if d['errors'] > 0 else ""
            print(f"  {fg:30s} -> avg: {d['avg_ms']:7.2f} ms | max: {d['max_ms']:7.2f} ms | calls: {d['count']}{err_lbl}")

    if stats["errors"]:
        hdr("Error Sample")
        for err_info in stats["errors"]:
            print(f"  Q{err_info['query_id']} [{err_info['flag']}]: {clr(err_info['error'], C_RED)}")

def main():
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner(f"DMS REAL FLAG BENCHMARK | {TOTAL_QUERIES} QUERIES | {run_ts}", C_CYAN)
    print(f"  Target DB        : {DB_URL}")
    print(f"  Total Real Flags : {len(FLAG_KEYS)}")
    print(f"  Total Queries    : {TOTAL_QUERIES}")
    print(f"  Concurrency      : {CONCURRENCY} parallel workers")
    print(f"  Max DB Conns     : {MAX_DB_CONNECTIONS} (semaphore-guarded)")
    print(f"  Submission Delay : {BATCH_DELAY_SEC * 1000:.0f} ms")

    sampler = SystemMetricsSampler(interval=METRICS_INTERVAL).start()
    t_start = time.perf_counter()
    results = run_load_test()
    wall_time = time.perf_counter() - t_start
    sampler.stop()

    stats       = calc_stats(results, wall_time)
    sys_metrics = sampler.summary()
    print_report(stats, sys_metrics)

if __name__ == "__main__":
    main()
