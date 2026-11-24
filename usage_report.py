"""Per-chat and per-task usage report for Claude Code transcripts.

Reads ~/.claude/projects/**/*.jsonl and writes two CSV files (UTF-8 with BOM,
opens in Excel) into _usage/ next to this script:

  sessions.csv  one row per chat
  turns.csv     one row per user prompt (a "task") inside a chat

Costs are estimates at Claude API list prices; the subscription is not billed
this way, but the numbers let tasks be compared with each other.

Usage:
  python usage_report.py                 rebuild both files from all transcripts
  python usage_report.py --days 14       only chats active in the last 14 days
  python usage_report.py --summary       print a breakdown of the current chat
                                         (most recently written transcript)
  python usage_report.py --hook          Claude Code Stop hook: reads the hook
                                         JSON on stdin, updates only that chat
"""
import argparse
import base64
import csv
import datetime as dt
import glob
import json
import os
import re
import struct
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "_usage")
PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")

# USD per 1M tokens: input, output, cache read. Cache writes: 5m = 1.25x input,
# 1h = 2x input.
PRICES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]

AI_RUN_RE = re.compile(r'ai_run\.py\s+"([^"]+)"|ai_run\.py\s+(\S+)')
COMMAND_RE = re.compile(r'--command\s+(?:"([^"]+)"|(\S+))')
SCREENSHOT_RE = re.compile(r"screenshot")


def price_of(model):
    for key in sorted(PRICES, key=len, reverse=True):
        if model and model.startswith(key):
            return PRICES[key]
    return DEFAULT_PRICE


def cost_parts(model, u):
    p_in, p_out, p_read = price_of(model)
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens")
    w5m = cc.get("ephemeral_5m_input_tokens")
    total_w = u.get("cache_creation_input_tokens") or 0
    if w1h is None and w5m is None:
        w1h, w5m = total_w, 0
    write = ((w5m or 0) * p_in * 1.25 + (w1h or 0) * p_in * 2.0) / 1e6
    return {
        "input": (u.get("input_tokens") or 0) * p_in / 1e6,
        "write": write,
        "read": (u.get("cache_read_input_tokens") or 0) * p_read / 1e6,
        "output": (u.get("output_tokens") or 0) * p_out / 1e6,
    }


def image_dims(b64):
    """Width/height from the header of a base64 PNG, JPEG or WebP."""
    raw = base64.b64decode(b64[:64])
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", raw[16:24])
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        raw = base64.b64decode(b64[:96])
        kind = raw[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(raw[24:27], "little") + 1,
                    int.from_bytes(raw[27:30], "little") + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", raw[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":
            bits = int.from_bytes(raw[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None, None
    if raw[:2] == b"\xff\xd8":
        raw = base64.b64decode(b64[:87384])  # first 64 KB
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", raw[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return w, h
            i += 2 + seg
    return None, None


def image_info(block):
    """(width, height, rough tokens). Tokens = w*h/750, long edge capped at 1568."""
    try:
        w, h = image_dims(block["source"]["data"])
    except Exception:
        w = h = None
    if not w or not h:
        return None, None, 1600
    scale = min(1.0, 1568 / max(w, h))
    return w, h, int(w * scale * h * scale / 750)


def new_bucket():
    return {
        "calls": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0,
        "cost": 0.0, "cost_read": 0.0, "cost_write": 0.0, "cost_output": 0.0,
        "images": 0, "image_tokens": 0, "image_sizes": Counter(), "screenshot_steps": 0, "ai_runs": 0,
        "games": Counter(), "commands": Counter(), "tools": Counter(),
        "models": Counter(), "context_start": None, "context_end": 0,
        "subagent_cost": 0.0,
    }


def add_usage(b, model, u, sidechain=False):
    parts = cost_parts(model, u)
    c = sum(parts.values())
    if sidechain:
        b["subagent_cost"] += c
    b["calls"] += 1
    b["input"] += u.get("input_tokens") or 0
    b["cache_write"] += u.get("cache_creation_input_tokens") or 0
    b["cache_read"] += u.get("cache_read_input_tokens") or 0
    b["output"] += u.get("output_tokens") or 0
    b["cost"] += c
    b["cost_read"] += parts["read"]
    b["cost_write"] += parts["write"] + parts["input"]
    b["cost_output"] += parts["output"]
    b["models"][model or "?"] += 1
    if not sidechain:
        ctx = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
        if b["context_start"] is None:
            b["context_start"] = ctx
        b["context_end"] = ctx


def add_tool_use(b, block):
    name = block.get("name", "?")
    b["tools"][name] += 1
    inp = block.get("input") or {}
    cmd = inp.get("command") if isinstance(inp, dict) else None
    if isinstance(cmd, str) and "ai_run" in cmd:
        b["ai_runs"] += 1
        for m in AI_RUN_RE.finditer(cmd):
            game = os.path.basename((m.group(1) or m.group(2)).rstrip("/\\"))
            if game and game[0] not in "-|$<>&;":
                b["games"][game] += 1
        for m in COMMAND_RE.finditer(cmd):
            b["commands"][m.group(1) or m.group(2)] += 1
        b["screenshot_steps"] += len(SCREENSHOT_RE.findall(cmd))
    elif name.endswith("screenshot") or name.endswith("zoom"):
        b["screenshot_steps"] += 1


def tool_label(block):
    """Short human-readable description of one tool call."""
    name = block.get("name", "?")
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return name
    if name == "Skill":
        return f"載入技能 {inp.get('skill', '?')}"
    if name in ("Read", "Write", "Edit") and inp.get("file_path"):
        return f"{name} {os.path.basename(inp['file_path'])}"
    if name in ("Bash", "PowerShell"):
        return f"{name}：{inp.get('description') or (inp.get('command') or '')[:40]}"
    if name in ("Grep", "Glob"):
        return f"{name} {inp.get('pattern', '')[:30]}"
    if name in ("Agent", "Task"):
        return f"子代理：{inp.get('description', '')}"
    if name == "ToolSearch":
        return f"載入工具 {inp.get('query', '')[:40]}"
    return name.replace("mcp__", "")


def add_images(b, content):
    if not isinstance(content, list):
        return
    for x in content:
        if isinstance(x, dict) and x.get("type") == "image":
            w, h, tok = image_info(x)
            b["images"] += 1
            b["image_tokens"] += tok
            b["image_sizes"][f"{w}x{h}" if w else "?"] += 1


def prompt_text(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c
                        if isinstance(x, dict) and x.get("type") == "text")
    return ""


def is_human_prompt(d):
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain") \
            or d.get("isCompactSummary"):
        return False
    if d.get("turnOrigin") not in (None, "human"):
        return False
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result"
                                   for x in c):
        return False
    text = prompt_text(d.get("message") or {}).strip()
    return bool(text) and not text.startswith(("<", "[Request interrupted"))


def parse_session(paths):
    """paths: main transcript first, then subagent transcripts."""
    sess = new_bucket()
    sess.update(id=None, title="", cwd="", start=None, end=None, jumps=[])
    prev_ctx, pending = None, []   # context of previous main call; what was added since
    turns = []
    cur = None
    seen = set()
    for i, path in enumerate(paths):
        sidechain_file = i > 0
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("type")
                if t == "custom-title" and d.get("customTitle"):
                    sess["title"] = d["customTitle"]
                    continue
                if t == "ai-title" and d.get("aiTitle") and not sess["title"]:
                    sess["title"] = d["aiTitle"]
                    continue
                if t not in ("user", "assistant"):
                    continue
                if not sidechain_file:
                    sess["id"] = sess["id"] or d.get("sessionId")
                    sess["cwd"] = sess["cwd"] or d.get("cwd", "")
                    ts = d.get("timestamp")
                    if ts:
                        sess["start"] = sess["start"] or ts
                        sess["end"] = ts
                side = sidechain_file or bool(d.get("isSidechain"))
                msg = d.get("message") or {}

                if not side and is_human_prompt(d):
                    cur = new_bucket()
                    cur.update(n=len(turns) + 1, time=d.get("timestamp", ""),
                               prompt=" ".join(prompt_text(msg).split())[:120])
                    turns.append(cur)
                    pending.append("你的指示「" + cur["prompt"][:30] + "」")
                buckets = [sess] + ([cur] if cur is not None else [])

                if t == "assistant":
                    u = msg.get("usage")
                    key = msg.get("id") or d.get("uuid")
                    if u and key not in seen:
                        seen.add(key)
                        for b in buckets:
                            add_usage(b, msg.get("model"), u, side)
                        if not side:
                            ctx = sum(u.get(k) or 0 for k in ("input_tokens",
                                      "cache_read_input_tokens", "cache_creation_input_tokens"))
                            if prev_ctx is not None:
                                sess["jumps"].append({
                                    "delta": ctx - prev_ctx, "ctx": ctx,
                                    "turn": cur["n"] if cur else 0,
                                    "time": d.get("timestamp", ""),
                                    "cause": pending[:]})
                            prev_ctx, pending = ctx, []
                    for blk in msg.get("content") or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_use":
                            for b in buckets:
                                add_tool_use(b, blk)
                            if not side:
                                pending.append(tool_label(blk))
                elif t == "user":
                    c = msg.get("content")
                    if isinstance(c, list):
                        for blk in c:
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "tool_result":
                                for b in buckets:
                                    add_images(b, blk.get("content"))
                                n_img = sum(1 for x in (blk.get("content") or [])
                                            if isinstance(x, dict) and x.get("type") == "image")
                                if n_img and not side:
                                    pending.append(f"{n_img} 張圖")
                            elif blk.get("type") == "image":
                                for b in buckets:
                                    add_images(b, [blk])
    return sess, turns


def top(counter, n=6):
    return "; ".join(f"{k}×{v}" if v > 1 else k for k, v in counter.most_common(n))


def local_time(ts):
    if not ts:
        return ""
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return t.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


SESSION_COLS = ["session_id", "title", "folder", "start", "end", "models",
                "api_calls", "cost_usd", "cost_cache_read", "cost_cache_write",
                "cost_output", "subagent_cost", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "context_end", "images_read", "image_tokens_est",
                "image_sizes", "screenshot_steps", "ai_runs", "games", "commands", "turns", "top_tools"]
TURN_COLS = ["session_id", "title", "turn", "time", "prompt", "api_calls", "cost_usd",
             "cost_cache_read", "cost_cache_write", "cost_output", "output_tokens",
             "context_start", "context_end", "images_read", "image_tokens_est",
             "image_sizes", "screenshot_steps", "ai_runs", "games", "commands", "top_tools"]


def common_cols(b):
    return {
        "api_calls": b["calls"], "cost_usd": round(b["cost"], 3),
        "cost_cache_read": round(b["cost_read"], 3),
        "cost_cache_write": round(b["cost_write"], 3),
        "cost_output": round(b["cost_output"], 3), "output_tokens": b["output"],
        "context_end": b["context_end"], "images_read": b["images"],
        "image_tokens_est": b["image_tokens"],
        "image_sizes": top(b["image_sizes"], 8), "screenshot_steps": b["screenshot_steps"],
        "ai_runs": b["ai_runs"], "games": top(b["games"]), "commands": top(b["commands"]),
        "top_tools": top(b["tools"]),
    }


def rows_for(sess, turns):
    srow = common_cols(sess)
    srow.update(session_id=sess["id"], title=sess["title"], folder=sess["cwd"],
                start=local_time(sess["start"]), end=local_time(sess["end"]),
                models=top(sess["models"]), subagent_cost=round(sess["subagent_cost"], 3),
                cache_read_tokens=sess["cache_read"], cache_write_tokens=sess["cache_write"],
                turns=len(turns))
    trows = []
    for t in turns:
        r = common_cols(t)
        r.update(session_id=sess["id"], title=sess["title"], turn=t["n"],
                 time=local_time(t["time"]), prompt=t["prompt"],
                 context_start=t["context_start"] or 0)
        trows.append(r)
    return srow, trows


def session_files(main_path):
    sub = os.path.join(os.path.splitext(main_path)[0], "**", "*.jsonl")
    return [main_path] + sorted(glob.glob(sub, recursive=True))


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, cols, rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = path + ".tmp"
    for attempt in range(5):
        try:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, path)
            return True
        except PermissionError:  # file open in Excel, or another hook writing
            time.sleep(0.5)
    print(f"usage_report: could not write {path} (open in Excel?)", file=sys.stderr)
    return False


def latest_transcript():
    """The chat being written right now is the most recently modified transcript."""
    paths = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    return max(paths, key=os.path.getmtime) if paths else None


def upsert(spath, tpath, srow, trows):
    sid = srow["session_id"]
    srows = [r for r in read_csv(spath) if r.get("session_id") != sid] + [srow]
    old_t = [r for r in read_csv(tpath) if r.get("session_id") != sid]
    srows.sort(key=lambda r: r.get("start", ""), reverse=True)
    write_csv(spath, SESSION_COLS, srows)
    write_csv(tpath, TURN_COLS, trows + old_t)


def print_summary(sess, turns, spath):
    """Plain-text breakdown of one chat for the AI to explain to the user."""
    s = sess
    pct = lambda x: f"{x / s['cost'] * 100:.0f}%" if s["cost"] else "-"
    print(f"聊天：{s['title'] or s['id']}  ({local_time(s['start'])} ~ {local_time(s['end'])})")
    print(f"估計花費 ${s['cost']:.2f}（API 牌價）｜呼叫 {s['calls']} 次｜"
          f"平均每次 ${s['cost'] / max(s['calls'], 1):.3f}")
    print(f"  重送舊上下文 ${s['cost_read']:.2f} ({pct(s['cost_read'])})｜"
          f"寫入新內容 ${s['cost_write']:.2f} ({pct(s['cost_write'])})｜"
          f"輸出 ${s['cost_output']:.2f} ({pct(s['cost_output'])})")
    print(f"  上下文 {turns[0]['context_start'] if turns else 0:,} → {s['context_end']:,} tokens")
    print(f"  讀圖 {s['images']} 張，約 {s['image_tokens']:,} tokens；尺寸：{top(s['image_sizes'], 8) or '-'}")
    print(f"  screenshot 步驟 {s['screenshot_steps']}｜ai_run {s['ai_runs']} 次｜"
          f"指令：{top(s['commands']) or '-'}")
    print(f"  工具：{top(s['tools'], 8)}")
    if s["subagent_cost"]:
        print(f"  子代理 ${s['subagent_cost']:.2f}")
    print("\n各次指示（依花費排序）：")
    for t in sorted(turns, key=lambda t: -t["cost"]):
        print(f"  #{t['n']} {local_time(t['time'])[11:]} ${t['cost']:.2f} 呼叫{t['calls']} "
              f"讀圖{t['images']} 上下文{t['context_start'] or 0:,}→{t['context_end']:,} "
              f"｜{t['prompt'][:50]}")
    jumps = [j for j in s.get("jumps", []) if j["delta"] >= 5000]
    if jumps:
        print("\n上下文暴增的步驟（單次增加 ≥5,000 tokens，依增加量排序）：")
        for j in sorted(jumps, key=lambda j: -j["delta"])[:8]:
            cause = "、".join(dict.fromkeys(j["cause"])) or "（看不出來源）"
            print(f"  +{j['delta']:,} → {j['ctx']:,}｜#{j['turn']} "
                  f"{local_time(j['time'])[11:]}｜{cause[:90]}")
        big = sum(j["delta"] for j in jumps)
        print(f"  這些步驟合計 +{big:,}，之後每次呼叫都要重送")
    drops = [j for j in s.get("jumps", []) if j["delta"] < -20000]
    for j in drops:
        print(f"  （#{j['turn']} 上下文 {j['delta']:,}，可能是 /compact 壓縮）")
    games = [g for g, _ in s["games"].most_common(1)]
    if games:
        past = [r for r in read_csv(spath)
                if games[0] in r.get("games", "") and r.get("session_id") != s["id"]]
        past.sort(key=lambda r: r.get("start", ""), reverse=True)
        if past:
            print(f"\n{games[0]} 之前的紀錄（最近 5 次）：")
            for r in past[:5]:
                print(f"  {r['start']} ${float(r['cost_usd']):.2f} 呼叫{r['api_calls']} "
                      f"讀圖{r['images_read']} ｜{r['title'][:30]}")


WARN_FROM = 150_000   # first warning at this context size
WARN_STEP = 50_000    # then once more every time it grows this much


def last_context(path):
    """Context size of the latest main-chat API call, reading only the file's tail."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 3_000_000))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        u = (d.get("message") or {}).get("usage")
        if d.get("type") == "assistant" and u and not d.get("isSidechain"):
            return d.get("sessionId"), d["message"].get("model"), sum(u.get(k) or 0 for k in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return None, None, 0


def warn(transcript):
    """Stop hook: tell the user (once per step) when the context is getting big."""
    sid, model, ctx = last_context(transcript)
    if not sid or ctx < WARN_FROM:
        return
    step = (ctx - WARN_FROM) // WARN_STEP
    state_path = os.path.join(OUT_DIR, "warn_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if state.get(sid, -1) >= step:
        return
    state[sid] = step
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    per_call = ctx / 1e6 * price_of(model)[2]
    print(json.dumps({"systemMessage":
        f"⚠ 這個聊天的上下文已到 {ctx // 1000}k tokens，每次呼叫光重送就約 ${per_call:.3f}。"
        f"換主題請開新聊天；要繼續的話可以輸入 /compact 壓縮。"}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook", action="store_true")
    ap.add_argument("--warn", action="store_true",
                    help="Stop hook: warn when this chat's context gets big")
    ap.add_argument("--transcript")
    ap.add_argument("--days", type=float)
    ap.add_argument("--summary", action="store_true",
                    help="print a breakdown of the current chat (or --transcript)")
    args = ap.parse_args()

    spath = os.path.join(OUT_DIR, "sessions.csv")
    tpath = os.path.join(OUT_DIR, "turns.csv")

    if args.summary:
        path = args.transcript or latest_transcript()
        if not path:
            print("找不到對話紀錄")
            return
        sess, turns = parse_session(session_files(path))
        if not sess["id"] or not sess["calls"]:
            print("這個聊天還沒有用量紀錄")
            return
        srow, trows = rows_for(sess, turns)
        upsert(spath, tpath, srow, trows)
        print_summary(sess, turns, spath)
        return

    if args.warn:
        try:
            path = args.transcript or json.load(sys.stdin).get("transcript_path")
        except ValueError:
            return
        if path and os.path.exists(path):
            warn(path)
        return

    transcript = args.transcript
    if args.hook:
        try:
            transcript = json.load(sys.stdin).get("transcript_path")
        except ValueError:
            return
        if not transcript or not os.path.exists(transcript):
            return

    if transcript:
        sess, turns = parse_session(session_files(transcript))
        if not sess["id"] or not sess["calls"]:
            return
        srow, trows = rows_for(sess, turns)
        upsert(spath, tpath, srow, trows)
        return

    cutoff = time.time() - args.days * 86400 if args.days else 0
    srows, trows = [], []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        if os.path.getmtime(path) < cutoff:
            continue
        sess, turns = parse_session(session_files(path))
        if not sess["id"] or not sess["calls"]:
            continue
        s, t = rows_for(sess, turns)
        srows.append(s)
        trows.extend(t)
    if cutoff:  # partial rebuild: keep older chats already in the tables
        ids = {r["session_id"] for r in srows}
        srows += [r for r in read_csv(spath) if r.get("session_id") not in ids]
        trows += [r for r in read_csv(tpath) if r.get("session_id") not in ids]
    srows.sort(key=lambda r: r["start"], reverse=True)
    trows.sort(key=lambda r: (r["time"], int(r["turn"])), reverse=True)
    write_csv(spath, SESSION_COLS, srows)
    write_csv(tpath, TURN_COLS, trows)
    total = sum(float(r["cost_usd"]) for r in srows)
    print(f"{len(srows)} chats, {len(trows)} turns, est. ${total:.2f} -> {OUT_DIR}")


if __name__ == "__main__":
    main()
