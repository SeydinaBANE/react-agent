#!/usr/bin/env python3
"""CLI: submit a task to the agent and stream results live."""
from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a goal to the ReAct agent.")
    parser.add_argument("--goal", required=True, help="The goal for the agent.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Agent API base URL.")
    parser.add_argument("--token", default="", help="JWT bearer token (if auth is enabled).")
    args = parser.parse_args()

    headers: dict[str, str] = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    # Submit task
    with httpx.Client(base_url=args.api_url, headers=headers, timeout=30) as client:
        resp = client.post("/api/v1/tasks", json={"goal": args.goal})
        if resp.status_code != 202:
            print(f"Error: {resp.status_code} — {resp.text}", file=sys.stderr)
            sys.exit(1)

        task = resp.json()
        task_id = task["task_id"]
        print(f"\n[Agent] Task submitted: {task_id}")
        print(f"[Agent] Goal: {args.goal}\n")

    # Stream SSE
    with httpx.Client(base_url=args.api_url, headers=headers, timeout=300) as stream_client:
        with stream_client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as response:
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        event = json.loads(data_str)
                        _print_event(event)
                    except json.JSONDecodeError:
                        print(line)

    print(f"\n[Agent] Task trace: GET {args.api_url}/api/v1/tasks/{task_id}/trace")


def _print_event(event: dict[str, object]) -> None:
    kind = event.get("event", "unknown")
    data = event.get("data", {})

    if kind == "step" and isinstance(data, dict):
        iteration = data.get("iteration", "?")
        thought = data.get("thought", "")[:120]
        tool = data.get("action", {}).get("tool", "?") if isinstance(data.get("action"), dict) else "?"
        obs = str(data.get("observation", ""))[:200]
        print(f"  [{iteration}] Thought: {thought}")
        print(f"       Tool:  {tool}")
        print(f"       Obs:   {obs}\n")
    elif kind == "final":
        print(f"\n[ANSWER] {data}\n")
    elif kind == "error":
        print(f"\n[ERROR] {data}\n", file=sys.stderr)
    elif kind == "waiting_approval":
        print(f"\n[APPROVAL NEEDED] {data}")
        print("  → POST /api/v1/tasks/<id>/approve {'approved': true}\n")


if __name__ == "__main__":
    main()
