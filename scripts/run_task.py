#!/usr/bin/env python3
"""CLI: submit a task to the agent and stream results live."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_env(path: str = ".env") -> dict[str, str]:
    """Parse .env file — strips inline comments, handles quoted values."""
    import re
    env: dict[str, str] = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            raw = raw.strip()
            # Quoted value → strip quotes, no comment stripping
            if (raw.startswith('"') and raw.endswith('"')) or \
               (raw.startswith("'") and raw.endswith("'")):
                value = raw[1:-1]
            else:
                # Unquoted → strip inline comment (space+# or tab+#)
                value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
            env[key.strip()] = value
    except FileNotFoundError:
        pass
    return env


def _make_dev_token(secret: str) -> str:
    from jose import jwt
    return jwt.encode({"sub": "dev-cli"}, secret, algorithm="HS256")


def main() -> None:
    import httpx

    parser = argparse.ArgumentParser(description="Submit a goal to the ReAct agent.")
    parser.add_argument("--goal", required=True, help="The goal for the agent.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Agent API base URL.")
    parser.add_argument("--token", default="", help="JWT bearer token (overrides auto-generated).")
    args = parser.parse_args()

    # Auto-generate dev token from JWT_SECRET_KEY in .env
    token = args.token
    if not token:
        env = _load_env()
        secret = env.get("JWT_SECRET_KEY") or os.environ.get("JWT_SECRET_KEY", "")
        if secret:
            token = _make_dev_token(secret)
        else:
            print("Warning: no JWT_SECRET_KEY found — requests may fail with 401", file=sys.stderr)

    headers: dict[str, str] = {"Authorization": f"Bearer {token}"} if token else {}

    # Submit task
    with httpx.Client(base_url=args.api_url, headers=headers, timeout=30) as client:
        resp = client.post("/api/v1/tasks", json={"goal": args.goal})
        if resp.status_code == 401:
            print("Error 401 — set JWT_SECRET_KEY in .env or pass --token", file=sys.stderr)
            sys.exit(1)
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

    print(f"\n[Agent] Trace: GET {args.api_url}/api/v1/tasks/{task_id}/trace")


def _print_event(event: dict[str, object]) -> None:
    kind = event.get("event", "unknown")
    data = event.get("data", {})

    if kind == "step" and isinstance(data, dict):
        iteration = data.get("iteration", "?")
        thought = str(data.get("thought", ""))[:200]
        action = data.get("action")
        tool = action.get("tool", "?") if isinstance(action, dict) else "?"
        obs = str(data.get("observation", ""))[:300]
        print(f"  [{iteration}] Thought: {thought}")
        print(f"       Tool:   {tool}")
        print(f"       Result: {obs}\n")
    elif kind == "final":
        print(f"\n{'='*60}")
        print(f"[ANSWER]\n{data}")
        print(f"{'='*60}\n")
    elif kind == "error":
        print(f"\n[ERROR] {data}\n", file=sys.stderr)
    elif kind == "waiting_approval":
        print(f"\n[APPROVAL NEEDED] {data}")
        print("  → curl -X POST http://localhost:8000/api/v1/tasks/<id>/approve")
        print("         -H 'Content-Type: application/json'")
        print("         -d '{\"approved\": true}'\n")


if __name__ == "__main__":
    main()
