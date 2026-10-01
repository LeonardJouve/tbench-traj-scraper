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
