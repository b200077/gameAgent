"""Send a gameAgent command, then block until it needs attention.

For AI-driven runs: run this in the background and only look at the screen
when it exits, instead of polling screenshots.

    python ai_run.py "<game folder>" --command daily
    python ai_run.py "<game folder>" --step "a,b,c"
    python ai_run.py "<game folder>" --stop
    python ai_run.py "<game folder>" --continue   # resume after an AI() step

Prints a final "RESULT: <reason>" line followed by the latest core messages.
Reasons: done, ai_handoff, timeout, paused, stopped, error, needs_input,
silence, max_run.
ai_handoff: the script reached an AI(說明) step; the core took a screenshot and
stopped there. Handle it with temporary steps, then --continue.
Depends on agent_core writing _core_messages.log.
"""
import argparse
import datetime
import json
import os
import re
import socket
import sys
import time
from collections import deque

ROOT = os.path.dirname(os.path.abspath(__file__))
TIMEOUT_PATTERN = re.compile(r"超時\s*([\d.]+)\s*秒")
START_PATTERN = re.compile(r"開始執行 '(.+)'")
POLL_SECONDS = 1
STOP_COMMAND = "stopCommand"
CONTINUE_COMMAND = "aiContinue"
STOP_SILENCE_SECONDS = 5
STOP_SETTLE_SECONDS = 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="game folder name or full path")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--command")
    target.add_argument("--step")
    target.add_argument("--stop", action="store_true", help="end every running or paused command")
    target.add_argument("--continue", dest="resume", action="store_true",
                        help="resume the command that stopped at an AI() step")
    parser.add_argument("--start-index", type=int, default=0,
                        help="with --command: 0-based position in the command's own step list; a :module counts as one")
    parser.add_argument("--timeout-threshold", type=float, default=8,
                        help="image timeouts shorter than this are normal (? and ↑ steps)")
    parser.add_argument("--silence", type=float, default=180,
                        help="seconds without a core message before waking (waitImg never times out)")
    parser.add_argument("--max-run", type=float, default=600,
                        help="overall limit in seconds (↑ retries can keep messages flowing)")
    parser.add_argument("--port", type=int, default=5200)
    parser.add_argument("--log", default=os.path.join(ROOT, "_core_messages.log"))
    return parser.parse_args()


def classify(message, command_name, timeout_threshold):
    """Return the reason this core message should end the wait, or None."""
    if f"{command_name}指令已完成" in message:
        return "done"
    if "偵測到 ESC" in message:
        return "stopped"
    if "REQ_INPUT:" in message:
        return "needs_input"
    if "處理完送 aiContinue 接續" in message:
        return "ai_handoff"
    if "❌" in message:
        return "error"
    timeout = TIMEOUT_PATTERN.search(message)
    if timeout and float(timeout.group(1)) >= timeout_threshold:
        return "timeout"
    if "步驟暫停" in message:
        return "paused"
    return None


def log_sent(folder, kind, value):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(folder, "_ai_command_log.txt"), "a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{kind}\t{value}\n")


def read_new_lines(path, offset):
    """Return complete lines after offset and the new offset."""
    try:
        if os.path.getsize(path) < offset:
            offset = 0  # the log was cleared (core restarted or cleanup)
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return [], offset
    end = data.rfind(b"\n") + 1
    text = data[:end].decode("utf-8", errors="replace")
    return text.splitlines(), offset + end


def watch(args, command_name, offset):
    recent = deque(maxlen=10)
    started = last_message = time.monotonic()
    while True:
        lines, offset = read_new_lines(args.log, offset)
        for line in lines:
            recent.append(line)
            last_message = time.monotonic()
            if command_name is None:
                # --continue: the resumed command announces its own name
                started_name = START_PATTERN.search(line)
                if started_name:
                    command_name = started_name.group(1)
            reason = classify(line, command_name, args.timeout_threshold)
            if reason:
                return reason, recent
        now = time.monotonic()
        if now - last_message >= args.silence:
            return "silence", recent
        if now - started >= args.max_run:
            return "max_run", recent
        time.sleep(POLL_SECONDS)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    folder = args.folder if os.path.isabs(args.folder) else os.path.join(ROOT, args.folder)

    # Record the position first so messages from a fast command are not missed.
    offset = os.path.getsize(args.log) if os.path.exists(args.log) else 0

    if args.stop:
        kind, value = "command", STOP_COMMAND
        message = {kind: value}
        args.silence = STOP_SILENCE_SECONDS
    elif args.resume:
        kind, value = "command", CONTINUE_COMMAND
        message = {kind: value}
    else:
        kind, value = ("command", args.command) if args.command else ("step", args.step)
        message = {"folder": folder, kind: value}
    if args.command and args.start_index:
        message["start_index"] = args.start_index
        value = f"{value} (start_index={args.start_index})"
    payload = json.dumps(message).encode("utf-8")
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=5) as client:
            client.sendall(payload)
    except OSError as e:
        print(f"RESULT: core_unreachable ({e})")
        return 1
    log_sent(folder, kind, value)

    # execute_command reports temporary steps under this name.
    command_name = None if args.resume else (args.command or "_interim")
    reason, recent = watch(args, command_name, offset)
    if args.stop:
        # A new command clears the stop flag, so let waiting commands see it first.
        time.sleep(STOP_SETTLE_SECONDS)
    print(f"RESULT: {reason}")
    for line in recent:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
