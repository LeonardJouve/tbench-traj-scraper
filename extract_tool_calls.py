"""
One common trace of tool calls for Claude Code, Codex and Grok Build, built from their native session logs.

  python fetch_trial_files.py trajectories -i 'agent/sessions/*.jsonl'
  python extract_tool_calls.py trial_files -o tool_calls.csv

One CSV row per tool call, ordered by start within each trial:
  tool                   the tool name as the agent invoked it
  start, end, blocked_s  the agent issued the call / got the result back: how long the agent waited on the tool.
                         A command that outlives its call (background, or still running when the tool yields) only
                         counts until the call returns
  gap_before_s           time between the previous result (or the session start) and this call: model and harness time.
                         0 when the call overlaps an earlier one (parallel calls)

Native sources:
  Claude  agent/sessions/projects/*/<session>.jsonl  timestamps of tool_use / tool_result
  Codex   agent/sessions/YYYY/MM/DD/rollout-*.jsonl  timestamps of function_call / function_call_output
  Grok    agent/sessions/*/<session>/events.jsonl    tool_completed (ts, duration_ms); arguments in updates.jsonl
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from fetch_trial_files import long_path

FIELDS = ["agent", "entry", "task", "trial", "seq", "call_id", "tool", "command", "start", "end", "blocked_s",
          "gap_before_s"]


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t: float | None) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds") if t else ""


def jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def claude(path: Path):
    start, calls = None, {}
    for e in jsonl(path):
        if not e.get("timestamp"):
            continue
        t = ts(e["timestamp"])
        start = start or t
        content = (e.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if b.get("type") == "tool_use":
                inp = b.get("input") or {}
                calls[b["id"]] = {"call_id": b["id"], "tool": b["name"], "command": inp.get("command", ""), "start": t}
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                calls[b["tool_use_id"]]["end"] = t
    return start, calls.values()


def codex(path: Path):
    start, calls = None, {}
    for e in jsonl(path):
        t = ts(e["timestamp"])
        start = start or t
        p = e.get("payload") or {}
        if p.get("type") in ("function_call", "custom_tool_call"):
            args = json.loads(p["arguments"]) if "arguments" in p else {}
            cmd = args.get("cmd", "")
            calls[p["call_id"]] = {"call_id": p["call_id"], "tool": p["name"],
                                   "command": " ".join(cmd) if isinstance(cmd, list) else cmd, "start": t}
        elif p.get("type") in ("function_call_output", "custom_tool_call_output") and p.get("call_id") in calls:
            calls[p["call_id"]]["end"] = t
    return start, calls.values()


def grok(events: Path):
    args = {}  # from updates.jsonl: chat_history.jsonl loses the calls before a compaction
    for e in jsonl(events.with_name("updates.jsonl")):
        u = (e.get("params") or {}).get("update") or {}
        if u.get("sessionUpdate") == "tool_call":
            args.setdefault(u["toolCallId"], u.get("rawInput") or {})
    start, calls = None, {}
    for e in jsonl(events):
        t = ts(e["ts"])
        start = start or t
        if e["type"] == "tool_completed":
            cid = e["tool_call_id"]
            calls[cid] = {"call_id": cid, "tool": e["tool_name"], "command": args.get(cid, {}).get("command", ""),
                          "start": t - e["duration_ms"] / 1000, "end": t}
    return start, calls.values()


SOURCES = [  # glob from the output root of fetch_trial_files.py: {entry}/{task}/{trial}/agent/sessions/...
    ("claude-code", "*/*/*/agent/sessions/projects/*/*.jsonl", claude),
    ("codex", "*/*/*/agent/sessions/**/rollout-*.jsonl", codex),
    ("grok-build", "*/*/*/agent/sessions/*/*/events.jsonl", grok),
]


def rows(root: Path):
    for agent, pattern, parse in SOURCES:
        for path in sorted(root.glob(pattern)):
            entry, task, trial = path.relative_to(root).parts[:3]
            start, calls = parse(path)
            last_end = start
            for seq, c in enumerate(sorted(calls, key=lambda c: c["start"]), 1):
                end = c.get("end")
                yield {
                    **c, "agent": agent, "entry": entry, "task": task, "trial": trial, "seq": seq,
                    "start": iso(c["start"]), "end": iso(end),
                    "blocked_s": round(end - c["start"], 3) if end else "",
                    "gap_before_s": round(max(0.0, c["start"] - last_end), 3),
                }
                last_end = max(last_end, end or c["start"])


def main():
    p = argparse.ArgumentParser(description="Common tool-call trace (CSV) of Claude Code, Codex and Grok Build sessions")
    p.add_argument("source", type=Path, help="output directory of fetch_trial_files.py")
    p.add_argument("-o", "--output", type=Path, default=Path("tool_calls.csv"))
    args = p.parse_args()
    n = 0
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for n, row in enumerate(rows(long_path(args.source)), 1):
            w.writerow(row)
    print(f"{n} tool calls -> {args.output}")


if __name__ == "__main__":
    main()
