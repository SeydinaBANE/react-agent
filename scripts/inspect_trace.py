#!/usr/bin/env python3
"""CLI: fetch and display a task trace in a readable format."""
from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a completed agent task trace.")
    parser.add_argument("--id", required=True, help="Task ID to inspect.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Agent API base URL.")
    parser.add_argument("--token", default="", help="JWT bearer token.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted.")
    args = parser.parse_args()

    headers: dict[str, str] = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    with httpx.Client(base_url=args.api_url, headers=headers, timeout=30) as client:
        resp = client.get(f"/api/v1/tasks/{args.id}/trace")
        if resp.status_code == 404:
            print(f"Task '{args.id}' not found.", file=sys.stderr)
            sys.exit(1)
        if resp.status_code != 200:
            print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)

    trace = resp.json()

    if args.json:
        print(json.dumps(trace, indent=2))
        return

    _pretty_print(trace)


def _pretty_print(trace: dict[str, object]) -> None:
    print("=" * 60)
    print(f"Task ID : {trace.get('task_id')}")
    print(f"Goal    : {trace.get('goal')}")
    print(f"Status  : {trace.get('status')}")
    print(f"Created : {trace.get('created_at')}")
    print(f"Done    : {trace.get('completed_at', 'N/A')}")
    print("=" * 60)

    steps = trace.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            i = step.get("iteration", "?")
            thought = step.get("thought", "")[:200]
            action = step.get("action", {})
            tool = action.get("tool", "?") if isinstance(action, dict) else "?"
            obs = str(step.get("observation", ""))[:300]
            ms = step.get("latency_ms", 0)
            print(f"\n[Step {i}] ({ms}ms)")
            print(f"  Thought    : {thought}")
            print(f"  Tool       : {tool}")
            print(f"  Observation: {obs}")

    print("\n" + "=" * 60)
    print(f"Final answer: {trace.get('final_answer', 'N/A')}")


if __name__ == "__main__":
    main()
