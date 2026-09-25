"""Runner - spawns ActorAgents to execute tasks concurrently.

This is the main entry point. It creates one ActorAgent per task and runs
them, all sharing the same CSV data context.

Usage:
    python -m challenge.runner                     # run all tasks
    python -m challenge.runner --task billing_summary  # run one task
    python -m challenge.runner --list              # list available tasks
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from smolagents import OpenAIServerModel

from challenge.agent import ActorAgent
from challenge.tasks import TASKS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_model() -> object:
    """Create the LLM model via any OpenAI-compatible API.

    Required env vars:
        MODEL_ID      — model name (e.g. "gpt-4o", "qwen3.5-35b")

    Optional:
        API_KEY       — API key for the provider (not needed for local servers)
        API_BASE      — base URL (e.g. "https://api.fireworks.ai/inference/v1",
                         "http://localhost:8080/v1" for llama.cpp).
                         Omit to use OpenAI's default endpoint.
    """
    import os

    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        raise EnvironmentError(
            "MODEL_ID must be set. "
            "Optionally set API_KEY and API_BASE. "
            "See .env.example for details."
        )

    api_key = os.environ.get("API_KEY") or "not-needed"
    api_base = os.environ.get("API_BASE") or None

    return OpenAIServerModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
    )


def run_task(task_def: dict) -> dict:
    """Run a single task and return the result."""
    model = create_model()
    agent = ActorAgent(
        name=task_def["agent_name"],
        role=task_def["role"],
        model=model,
        max_steps=task_def.get("max_steps", 15),
    )

    try:
        result = agent.run(task_def["prompt"])
        return {
            "task": task_def["name"],
            "agent": task_def["agent_name"],
            "status": "success",
            "result": str(result),
        }
    except Exception as exc:
        logger.exception("Task '%s' failed", task_def["name"])
        return {
            "task": task_def["name"],
            "agent": task_def["agent_name"],
            "status": "error",
            "result": str(exc),
        }


def main():
    parser = argparse.ArgumentParser(description="Run ActorAgent tasks")
    parser.add_argument("--task", help="Run a specific task by name")
    parser.add_argument("--list", action="store_true", help="List available tasks")
    parser.add_argument("--parallel", action="store_true", help="Run tasks in parallel threads")
    args = parser.parse_args()

    if args.list:
        print("Available tasks:")
        for t in TASKS:
            print(f"  - {t['name']:30s} ({t['agent_name']})")
        return

    # Select tasks
    if args.task:
        selected = [t for t in TASKS if t["name"] == args.task]
        if not selected:
            print(f"Unknown task: {args.task}")
            print(f"Available: {[t['name'] for t in TASKS]}")
            sys.exit(1)
    else:
        selected = TASKS

    print(f"Running {len(selected)} task(s)...\n")

    if args.parallel and len(selected) > 1:
        # Run agents concurrently
        results = []
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {pool.submit(run_task, t): t["name"] for t in selected}
            for future in as_completed(futures):
                results.append(future.result())
    else:
        # Run sequentially
        results = [run_task(t) for t in selected]

    # Print summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for r in results:
        status_icon = "OK" if r["status"] == "success" else "FAIL"
        print(f"  [{status_icon}] {r['task']} ({r['agent']})")
        if r["status"] == "success":
            # Print first 200 chars of result
            summary = r["result"][:200].replace("\n", " ")
            print(f"       {summary}")
        else:
            print(f"       Error: {r['result'][:200]}")
    print()


if __name__ == "__main__":
    main()
