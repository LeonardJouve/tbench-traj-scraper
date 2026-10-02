"""
Download any file of Terminal-Bench trials (agent logs, native sessions, results...) from Harbor Hub.

scrape_trajectories.py only fetches agent/trajectory.json (ATIF), which has no tool durations. The agents' native logs do
(e.g. agent/claude-code.txt, agent/sessions/**/*.jsonl). This script reads the trials already scraped (trial id and job id of each
record), lists their files on the Hub and downloads the ones matching --include. Re-running resumes: complete files are skipped.

  python fetch_trial_files.py trajectories --list-only --limit 2    # what files do the trials have?
  python fetch_trial_files.py trajectories                          # agent/*.txt and result.json
  python fetch_trial_files.py trajectories -i 'agent/sessions/*.jsonl' -x '*.backup*'
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://hub.harborframework.com/api/trials"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"


def fetch(url: str, params: dict, retries: int, size: int | None = None) -> bytes | None:
    """Body of a GET, or None on 404. Retries with exponential backoff on connection errors, timeouts, truncated or wrong-size
    bodies and transient HTTP errors."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=(10, 120))
            if resp.status_code == 404:
                return None
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                if size is None or len(resp.content) == size:
                    return resp.content
                error = f"got {len(resp.content)} bytes, expected {size}"
            else:
                error = f"HTTP {resp.status_code}"
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            error = str(e)
        if attempt == retries:
            raise RuntimeError(error)
        print(f"    retry {attempt}/{retries - 1} ({error}), waiting {2**attempt}s")
        time.sleep(2**attempt)


def long_path(path: Path) -> Path:
    """Windows: the \\\\?\\ prefix lifts the 260-character limit, which {entry}/{task}/{trial}/agent/sessions/... can exceed."""
    return Path("\\\\?\\" + str(path.resolve())) if sys.platform == "win32" else path


def trials(root: Path):
    """(entry, task, trial id, job id) of the records written by scrape_trajectories.py: .../{entry}/{task}/{trial id}.json
    (a single entry directory, {task}/{trial id}.json, works too)."""
    for p in sorted(root.rglob("*.json")):
        with p.open(encoding="utf-8", errors="ignore") as f:
            ids = dict(re.findall(r'"(trial_id|job_id)":\s*"([^"]*)"', f.read(4096)))  # both come before the bulky "trajectory"
        if len(ids) == 2:
            yield p.parent.parent.name, p.parent.name, ids["trial_id"], ids["job_id"]


def summary(counts: Counter) -> str:
    return ", ".join(f"{k} {v:.1f}" if k == "MB" else f"{k} {v}" for k, v in counts.items())


def main() -> int:
    p = argparse.ArgumentParser(description="Download any file of Terminal-Bench trials from Harbor Hub")
    p.add_argument("source", type=Path, help="directory written by scrape_trajectories.py")
    p.add_argument("-i", "--include", action="append", help="glob of files to fetch, repeatable; * also matches / "
                   "(default: agent/*.txt and result.json)")
    p.add_argument("-x", "--exclude", action="append", default=[], help="glob of files to skip, repeatable")
    p.add_argument("--max-size", type=float, default=25, metavar="MB", help="skip larger files (default: 25; trials can hold 40 MB dumps)")
    p.add_argument("--limit", type=int, help="only the first N trials")
    p.add_argument("--list-only", action="store_true", help="show the selected files, download nothing")
    p.add_argument("-o", "--output", type=Path, default=Path("trial_files"), help="output directory (default: trial_files)")
    p.add_argument("--delay", type=float, default=0.3, help="seconds between requests (default: 0.3)")
    p.add_argument("--retries", type=int, default=5, help="attempts per request (default: 5)")
    args = p.parse_args()
    include = args.include or ["agent/*.txt", "result.json"]

    selected_trials = list(trials(args.source))[: args.limit]
    if not selected_trials:
        print(f"no trial records (with trial_id and job_id) found under {args.source}")
        return 1
    counts, failed = Counter(), []
    for n, (entry, task, trial, job) in enumerate(selected_trials, 1):
        time.sleep(args.delay)
        try:
            listing = fetch(f"{API}/{trial}/files", {"jobId": job}, args.retries)
        except RuntimeError as e:
            failed.append(f"{trial} listing: {e}")
            continue
        for f in json.loads(listing)["files"] if listing else []:
            path, size = f["path"], f["size"]
            if f["is_dir"] or ".." in Path(path).parts:  # never write outside the trial directory
                continue
            if not any(fnmatchcase(path, g) for g in include) or any(fnmatchcase(path, g) for g in args.exclude):
                continue
            if size > args.max_size * 1e6:
                counts["too large"] += 1
                continue
            if args.list_only:
                print(f"{size:>10}  {trial[:8]}  {path}")
                counts["selected"] += 1
                continue
            dest = long_path(args.output / entry / task / trial / path)
            if dest.exists() and dest.stat().st_size == size:
                counts["skipped"] += 1
                continue
            time.sleep(args.delay)
            try:
                body = fetch(f"{API}/{trial}/files/{quote(path, safe='/')}", {"jobId": job}, args.retries, size)
            except RuntimeError as e:
                failed.append(f"{trial} {path}: {e}")
                print(f"FAILED {trial[:8]} {path}: {e}")
                continue
            if body is None:
                counts["missing"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")  # written whole, then renamed: no half-written file under the final name
            part.write_bytes(body)
            part.replace(dest)
            counts["downloaded"] += 1
            counts["MB"] += size / 1e6
        print(f"[{n}/{len(selected_trials)}] {task} {trial[:8]} (so far: {summary(counts)})")

    print(f"\n{summary(counts)}")
    if failed:
        print(f"{len(failed)} failed; run the same command again to retry them (complete files are skipped)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
