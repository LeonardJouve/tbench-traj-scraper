# Terminal-Bench Trajectory Scraper

Download agent trajectories from the [Terminal-Bench 2.0](https://www.tbench.ai/) leaderboard.

Terminal-Bench is a benchmark for evaluating AI agents on complex terminal tasks. Each leaderboard entry includes full agent trajectories (step-by-step tool calls, observations, and reasoning) in [ATIF v1.6](https://www.tbench.ai/docs) format.

## Pre-scraped Data

Download pre-scraped trajectories from [Releases](https://github.com/Jiacheng-Zhu-AIML/terminal_bench_trajectories/releases):

| Agent | Model | Trajectories |
|-------|-------|-------------|
| terminus-2 | Claude Opus 4.6 | 445 |
| terminus-2 | Claude Opus 4.5 | 445 |
| terminus-2 | GPT-5.2 | 443 |
| claude-code | Claude Opus 4.6 | 435 |
| claude-code | Claude Opus 4.5 | 436 |
| **Total** | | **2,204** |

```bash
# Download and extract
wget https://github.com/Jiacheng-Zhu-AIML/terminal_bench_trajectories/releases/download/v0.1/trajectories.tar.gz
tar xzf trajectories.tar.gz
```

> **Note:** Not all agents publish trajectory data. OpenAI Codex CLI and some other agents only have summary statistics on the leaderboard, not full trajectories.

## Scrape More Data

```bash
pip install requests

# Download trajectories for one model (89 tasks × 5 trials = 445 trajectories)
python scrape_trajectories.py -a terminus-2 -m claude-opus-4-6@anthropic

# Download all trajectories for one agent
python scrape_trajectories.py -a terminus-2

# Download everything (only agents that publish trajectories)
python scrape_trajectories.py
```

## How It Works

The scraper navigates a 3-level URL hierarchy on tbench.ai:

1. **Leaderboard page** → discovers all agent/model entries
2. **Model page** (`/{agent}/{version}/{model}`) → 89 tasks with checksums
3. **Task page** (`/.../{taskChecksum}`) → 5 trial UUIDs per task
4. **Trial page** (`/.../{taskChecksum}/{trialId}`) → full trajectory JSON

Data is server-rendered in Next.js RSC payloads embedded in `<script>` tags. The scraper extracts and decodes these payloads using `json.JSONDecoder.raw_decode()`.

## Output Structure

```
trajectories/
  {agent}__{model}/
    _tasks.json                        # Task list with checksums
    {task_name}/
      _trials.json                     # Trial metadata (IDs, rewards, tokens, cost)
      {trial_uuid}.json                # Full trajectory
```

Each trajectory file contains:

```json
{
  "agent_name": "terminus-2",
  "model": "claude-opus-4-6@anthropic",
  "task_name": "break-filter-js-from-html",
  "reward": 1,
  "trajectory": {
    "schema_version": "ATIF-v1.6",
    "session_id": "...",
    "agent": { "name": "terminus-2", "model_name": "anthropic/claude-opus-4-6" },
    "steps": [
      {
        "step_id": 1,
        "source": "agent",
        "tool_calls": [{ "function_name": "bash_command", "arguments": {...} }],
        "observation": { "results": [...] },
        "metrics": { "prompt_tokens": 935, "completion_tokens": 200 }
      }
    ],
    "final_metrics": { "total_cost_usd": 0.359 }
  }
}
```

## Options

| Flag | Description |
|------|-------------|
| `-o, --output` | Output directory (default: `trajectories`) |
| `-a, --agents` | Filter by agent name (e.g. `terminus-2`, `claude-code`) |
| `-m, --models` | Filter by model (e.g. `claude-opus-4-6@anthropic`) |
| `--max-models` | Limit number of models to scrape |
| `--delay` | Delay between requests in seconds (default: 0.5) |
| `--no-resume` | Start fresh instead of resuming |

The scraper is **resume-safe** — re-running skips already downloaded trajectories.

## Acknowledgments

Data sourced from [Terminal-Bench](https://www.tbench.ai/) by the [Laude Institute](https://github.com/laude-institute/terminal-bench).
