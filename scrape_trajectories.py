"""
Scrape Terminal-Bench 2.0 agent trajectories from tbench.ai

URL hierarchy:
  /leaderboard/terminal-bench/2.0/{agent}/{version}/{model}
    -> list of 89 tasks with taskChecksum
  /.../{taskChecksum}
    -> list of 5 trials with trialId (UUID)
  /.../{taskChecksum}/{trialId}
    -> full trajectory JSON (ATIF-v1.6 schema)

Data is server-rendered in Next.js RSC payloads inside <script> tags.
"""

import json
import re
import time
import argparse
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://www.tbench.ai"
LEADERBOARD_URL = f"{BASE_URL}/leaderboard/terminal-bench/2.0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = 5  # seconds


def fetch(url: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp.text
        except (requests.RequestException, requests.Timeout) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = RETRY_BACKOFF * (attempt + 1)
            print(f"    Retry {attempt+1}/{MAX_RETRIES} after {wait}s: {e}")
            time.sleep(wait)


_JSON_DECODER = json.JSONDecoder()


def decode_nextjs_payloads(html: str) -> str:
    """Extract and decode all self.__next_f.push() payloads into one string."""
    combined = ""
    for s in re.findall(r"<script>(.*?)</script>", html, re.DOTALL):
        m = re.match(r"self\.__next_f\.push\((\[1,.*\])\)", s, re.DOTALL)
        if m:
            try:
                arr = json.loads(m.group(1))
                combined += arr[1] + "\n"
            except (json.JSONDecodeError, IndexError):
                pass
    return combined


def find_json_array(text: str, anchor: str) -> list[dict]:
    """Find a JSON array in text that starts with objects containing `anchor` key."""
    marker = f'"data":[{{"{anchor}"'
    idx = text.find(marker)
    if idx >= 0:
        arr_start = idx + 7  # skip '"data":'
    else:
        marker2 = f'[{{"{anchor}"'
        idx = text.find(marker2)
        if idx < 0:
            return []
        arr_start = idx

    try:
        result, _ = _JSON_DECODER.raw_decode(text, arr_start)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


def extract_trajectory(html: str) -> dict | None:
    """Extract the trajectory JSON object from a trial page."""
    for s in re.findall(r"<script>(.*?)</script>", html, re.DOTALL):
        if "schema_version" not in s:
            continue
        m = re.match(r"self\.__next_f\.push\((\[1,.*\])\)", s, re.DOTALL)
        if not m:
            continue
        try:
            payload = json.loads(m.group(1))[1]
        except (json.JSONDecodeError, IndexError):
            continue

        traj_marker = '"trajectory":{"schema_version"'
        tidx = payload.find(traj_marker)
        if tidx < 0:
            continue

        obj_start = payload.find('{"schema_version"', tidx)
        try:
            traj, _ = _JSON_DECODER.raw_decode(payload, obj_start)
            return traj
        except json.JSONDecodeError:
            return None
    return None


# ─── Leaderboard discovery ───


def get_leaderboard_entries(html: str) -> list[dict]:
    """Get all entries from the main leaderboard page."""
    payload = decode_nextjs_payloads(html)
    idx = payload.find('"agentName"')
    if idx < 0:
        return []
    start = payload.rfind("[{", max(0, idx - 50000), idx)
    if start < 0:
        return []
    try:
        result, _ = _JSON_DECODER.raw_decode(payload, start)
        if isinstance(result, list) and len(result) > 0 and "agentName" in result[0]:
            return result
    except json.JSONDecodeError:
        pass
    return []


def get_task_checksums(html: str) -> list[dict]:
    """Get task list with checksums from a model page."""
    payload = decode_nextjs_payloads(html)
    marker = '"data":[{"taskName"'
    idx = payload.find(marker)
    if idx < 0:
        return []
    arr_start = idx + 7  # skip '"data":'
    try:
        result, _ = _JSON_DECODER.raw_decode(payload, arr_start)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


def get_trial_ids(html: str) -> list[dict]:
    """Get trial list from a task checksum page."""
    payload = decode_nextjs_payloads(html)
    return find_json_array(payload, "trialId")


# ─── Main ───


def scrape_trajectories(
    output_dir: str,
    filter_agents: list[str] | None = None,
    filter_models: list[str] | None = None,
    max_models: int | None = None,
    resume: bool = True,
):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Progress tracking for resume
    progress_file = out / "_progress.json"
    done = set()
    if resume and progress_file.exists():
        done = set(json.loads(progress_file.read_text()))
        print(f"Resuming: {len(done)} trajectories already downloaded")

    def save_progress():
        progress_file.write_text(json.dumps(sorted(done)))

    # Step 1: Get leaderboard
    print("=" * 60)
    print("Step 1: Fetching leaderboard...")
    print("=" * 60)

    lb_cache = out / "_leaderboard.json"
    if resume and lb_cache.exists():
        entries = json.loads(lb_cache.read_text())
    else:
        html = fetch(LEADERBOARD_URL)
        entries = get_leaderboard_entries(html)
        lb_cache.write_text(json.dumps(entries, indent=2))
    print(f"  {len(entries)} entries")

    # Build scrape targets: (agent_name, agent_version, model_key)
    targets = []
    for e in entries:
        agent_name = e.get("agentName", "")
        agent_version = e.get("agentVersion", "unknown")
        model_names = e.get("modelNames", [])
        model_providers = e.get("modelProviders", [])

        if filter_agents and agent_name not in filter_agents:
            continue

        for i, mn in enumerate(model_names):
            provider = model_providers[i] if i < len(model_providers) else "unknown"
            model_key = f"{mn}@{provider}"

            if filter_models and model_key not in filter_models and mn not in filter_models:
                continue

            targets.append((agent_name, agent_version, model_key))

    if max_models:
        targets = targets[:max_models]
    print(f"  {len(targets)} models to scrape")

    # Step 2: For each model, get tasks, then trials, then trajectories
    total_downloaded = 0
    total_skipped = 0
    total_errors = 0

    for mi, (agent, version, model) in enumerate(targets):
        model_encoded = quote(model, safe="")
        model_url = f"{LEADERBOARD_URL}/{agent}/{version}/{model_encoded}"
        model_dir = out / f"{agent}__{model.replace('/', '_')}".replace("@", "_at_")
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 60}")
        print(f"[{mi+1}/{len(targets)}] {agent} / {model}")
        print(f"{'=' * 60}")

        # Get tasks
        tasks_cache = model_dir / "_tasks.json"
        if resume and tasks_cache.exists():
            tasks = json.loads(tasks_cache.read_text())
        else:
            try:
                html = fetch(model_url)
                tasks = get_task_checksums(html)
                tasks_cache.write_text(json.dumps(tasks, indent=2))
            except Exception as e:
                print(f"  ERROR fetching tasks: {e}")
                total_errors += 1
                continue

        if not tasks:
            print(f"  No tasks found, skipping")
            continue

        print(f"  {len(tasks)} tasks")

        for ti, task in enumerate(tasks):
            task_name = task["taskName"]
            task_checksum = task["taskChecksum"]
            task_dir = model_dir / task_name
            task_dir.mkdir(parents=True, exist_ok=True)

            # Get trial IDs
            trials_cache = task_dir / "_trials.json"
            if resume and trials_cache.exists():
                trials = json.loads(trials_cache.read_text())
            else:
                task_url = f"{model_url}/{task_checksum}"
                try:
                    html = fetch(task_url)
                    trials = get_trial_ids(html)
                    trials_cache.write_text(json.dumps(trials, indent=2))
                except Exception as e:
                    print(f"  [{ti+1}/{len(tasks)}] {task_name}: ERROR getting trials: {e}")
                    total_errors += 1
                    continue

            if not trials:
                print(f"  [{ti+1}/{len(tasks)}] {task_name}: no trials found")
                continue

            # Download each trajectory
            for trial in trials:
                trial_id = trial["trialId"]
                progress_key = f"{agent}/{model}/{task_checksum}/{trial_id}"
                traj_file = task_dir / f"{trial_id}.json"

                if progress_key in done or traj_file.exists():
                    done.add(progress_key)
                    total_skipped += 1
                    continue

                trial_url = f"{model_url}/{task_checksum}/{trial_id}"
                try:
                    html = fetch(trial_url)
                    traj = extract_trajectory(html)
                    if traj:
                        output = {
                            "agent_name": agent,
                            "agent_version": version,
                            "model": model,
                            "task_name": task_name,
                            "task_checksum": task_checksum,
                            "trial_id": trial_id,
                            "trial_name": trial.get("trialName", ""),
                            "reward": trial.get("reward"),
                            "trajectory": traj,
                        }
                        traj_file.write_text(json.dumps(output, indent=2))
                        done.add(progress_key)
                        total_downloaded += 1
                    else:
                        print(f"    {trial_id}: no trajectory found in page")
                        total_errors += 1
                except Exception as e:
                    print(f"    {trial_id}: ERROR: {e}")
                    total_errors += 1

            n_done = sum(1 for t in trials if f"{agent}/{model}/{task_checksum}/{t['trialId']}" in done)
            rewards = [t.get("reward", "?") for t in trials]
            print(f"  [{ti+1}/{len(tasks)}] {task_name}: {n_done}/{len(trials)} trajectories | rewards={rewards}")

            # Save progress periodically
            if (ti + 1) % 10 == 0:
                save_progress()

        save_progress()

    save_progress()
    print(f"\n{'=' * 60}")
    print(f"DONE!")
    print(f"  Downloaded: {total_downloaded}")
    print(f"  Skipped (already done): {total_skipped}")
    print(f"  Errors: {total_errors}")
    print(f"  Output: {out.resolve()}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Download Terminal-Bench trajectories")
    p.add_argument("-o", "--output", default="trajectories", help="Output directory")
    p.add_argument("-a", "--agents", nargs="+", help="Filter by agent (e.g. terminus-2)")
    p.add_argument("-m", "--models", nargs="+", help="Filter by model (e.g. claude-opus-4-6@anthropic)")
    p.add_argument("--max-models", type=int, help="Max number of models to scrape")
    p.add_argument("--delay", type=float, default=0.5, help="Delay between requests (default: 0.5s)")
    p.add_argument("--no-resume", action="store_true", help="Don't resume from previous progress")
    args = p.parse_args()

    REQUEST_DELAY = args.delay

    scrape_trajectories(
        output_dir=args.output,
        filter_agents=args.agents,
        filter_models=args.models,
        max_models=args.max_models,
        resume=not args.no_resume,
    )
