# Terminal-Bench Trajectory Scraper

Download agent trajectories of the top entries of the current [Terminal-Bench](https://www.tbench.ai/) leaderboard (hosted on [Harbor Hub](https://hub.harborframework.com)). Trajectories are in ATIF format.

```bash
pip install requests

python scrape_trajectories.py            # top 3 entries (default)
python scrape_trajectories.py -n 10      # top 10
python scrape_trajectories.py -n 1 -o out --delay 0.5
```

| Flag | Description |
|------|-------------|
| `-n, --top` | Number of top-ranked entries to scrape (default: 3) |
| `-o, --output` | Output directory (default: `trajectories`) |
| `--delay` | Delay between downloads in seconds (default: 0.2) |

Re-running skips trajectories that are already downloaded. Each entry has ~330 trials of ~1 MB, so expect several hundred MB per entry. Some trials may have no trajectory file; they are reported and skipped.

## Fetching other trial files (`fetch_trial_files.py`)

ATIF has no tool durations, but the agents' native logs do. `fetch_trial_files.py` reads the trials you already scraped, lists their files on the Hub (`GET /api/trials/{id}/files?jobId=...`) and downloads the ones you pick, for any agent. Files are saved as-is.

```bash
python fetch_trial_files.py trajectories --list-only --limit 2    # what files do the trials have?
python fetch_trial_files.py trajectories                          # default: agent/*.txt and result.json
python fetch_trial_files.py trajectories -i 'agent/sessions/*.jsonl' -x '*.backup*'
```

| Flag | Description |
|------|-------------|
| `-i GLOB` / `-x GLOB` | Files to fetch / to skip, repeatable. `*` also matches `/`. Default: `agent/*.txt`, `result.json` |
| `--max-size MB` | Skip larger files (default: 25; some trials hold 40 MB database dumps) |
| `--limit N`, `--list-only` | Keep the first N trials; show the selected files without downloading |
| `-o`, `--delay`, `--retries` | Output directory (default: `trial_files`), seconds between requests (0.3), attempts per request (5) |

Requests are retried with exponential backoff (connection errors, timeouts, truncated or wrong-size bodies, HTTP 408/425/429/5xx). Re-running the same command resumes: complete files are skipped and failed ones are tried again. Output: `trial_files/{entry}/{task}/{trial_id}/{path on the Hub}`.

Native logs differ per agent. Claude Code writes `agent/claude-code.txt` (stream-json: `init` with the exposed tools, timestamps, final `duration_ms` / `duration_api_ms`) and `agent/sessions/projects/*/*.jsonl`; Codex writes `agent/codex.txt` (no timestamps) and `agent/sessions/YYYY/MM/DD/rollout-*.jsonl` (a timestamp per event). A tool call's duration is the timestamp of its result minus the timestamp of the call.

## How it works

1. `tbench.ai/leaderboard/terminal-bench/2.0` serves the current leaderboard (server-rendered rows: rank, agent, model, accuracy).
2. The Harbor Hub row page `.../leaderboards/{name}/rows/{rowId}?tab=results&page=N` lists the row's trials (trial id, job id, task, reward).
3. `GET /api/trials/{trialId}/files/agent/trajectory.json?jobId={jobId}` returns the trajectory.

Pages 1 and 2 are parsed from Next.js RSC payloads in `<script>` tags; step 3 is a plain JSON API.

## Output

```
trajectories/
  {rank}_{agent}__{model}_{effort}/
    {task_name}/
      {trial_id}.json   # {rank, agent, model, task_name, trial_id, job_id, reward, cost_usd, trajectory}
```

Data sourced from [Terminal-Bench](https://www.tbench.ai/) by the [Laude Institute](https://github.com/laude-institute/terminal-bench).
