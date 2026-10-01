"""
Scrape Terminal-Bench trajectories of the top leaderboard entries from Harbor Hub.

Flow:
  tbench.ai leaderboard     -> ranked rows (agent / model / accuracy)
  row page (?page=N)        -> paginated trials (trial id, job id, task, reward)
  /api/trials/{id}/files/agent/trajectory.json?jobId=...  -> ATIF trajectory

Rows and trials are server-rendered in Next.js RSC payloads inside <script> tags.
"""

import argparse
import json
import re
import time
from pathlib import Path

import requests

LEADERBOARD_URL = "https://www.tbench.ai/leaderboard/terminal-bench/2.0"  # serves the current leaderboard
HUB = "https://hub.harborframework.com"
DATASET = f"{HUB}/datasets/terminal-bench/terminal-bench/4"
HEADERS = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 404:
                return resp
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            print(f"    retry {attempt + 1}/{retries}: {e}")
            time.sleep(5 * (attempt + 1))


def next_data(html: str) -> str:
    """Concatenate all self.__next_f.push([1, "..."]) chunks of a Next.js page."""
    chunks = re.findall(r"self\.__next_f\.push\((\[1,.*?\])\)</script>", html, re.DOTALL)
    return "".join(json.loads(c)[1] for c in chunks)


def json_after(payload: str, key: str):
    """Decode the JSON value following the first `"key":` in the payload."""
    marker = f'"{key}":'
    i = payload.index(marker) + len(marker)
    return json.JSONDecoder().raw_decode(payload, i)[0]


def slug(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("_")


def get_rows(top: int) -> tuple[str, list[dict]]:
    payload = next_data(get(LEADERBOARD_URL).text)
    leaderboard = json_after(payload, "leaderboard")["name"]
    rows = sorted(json_after(payload, "rows"), key=lambda r: r["rank"])
    return leaderboard, rows[:top]


def get_trials(leaderboard: str, row_id: str) -> list[dict]:
    url = f"{DATASET}/leaderboards/{leaderboard}/rows/{row_id}"
    trials, page, total_pages = [], 1, 1
    while page <= total_pages:
        html = get(url, {"tab": "results", "page": page}).text
        data = json_after(next_data(html), "initialTrials")
        trials += data["items"]
        total_pages = data["total_pages"]
        page += 1
    return trials


def scrape(top: int, out: Path, delay: float):
    leaderboard, rows = get_rows(top)
    print(f"Top {len(rows)} entries of leaderboard {leaderboard}")

    for row in rows:
        meta = row["metadata"]
        agent, model = meta["agent_display"]["label"], meta["model_display"]["label"]
        effort = meta.get("reasoning_effort")
        name = slug(f"{row['rank']:02d}_{agent}__{model}" + (f"_{effort}" if effort else ""))
        print(f"\n#{row['rank']} {agent} / {model} ({row['metrics']['accuracy']}%)")

        trials = get_trials(leaderboard, row["id"])
        saved = skipped = missing = 0
        for t in trials:
            path = out / name / slug(t["task_name"].split("/")[-1]) / f"{t['id']}.json"
            if path.exists():
                skipped += 1
                continue
            resp = get(
                f"{HUB}/api/trials/{t['id']}/files/agent/trajectory.json",
                {"jobId": t["job_id"]},
            )
            time.sleep(delay)
            if resp.status_code == 404:
                missing += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "rank": row["rank"],
                "agent": agent,
                "model": model,
                "reasoning_effort": effort,
                "task_name": t["task_name"],
                "trial_id": t["id"],
                "job_id": t["job_id"],
                "reward": t["reward"],
                "cost_usd": t.get("cost_usd"),
                "trajectory": resp.json(),
            }
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            saved += 1
        print(f"  {len(trials)} trials: {saved} saved, {skipped} already there, {missing} without trajectory")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Download trajectories of the top Terminal-Bench entries")
    p.add_argument("-n", "--top", type=int, default=3, help="Number of top-ranked entries (default: 3)")
    p.add_argument("-o", "--output", default="trajectories", help="Output directory")
    p.add_argument("--delay", type=float, default=0.2, help="Delay between downloads in seconds")
    args = p.parse_args()
    scrape(args.top, Path(args.output), args.delay)
