"""Submit and poll the MPT editorial API from an external Python automation.

Provider credentials belong in the MPT server configuration. MPT_API_KEY is only
this client's authentication for MPT's own API. No automatic POST retries.
"""

import argparse
import json
import os
import time
from pathlib import Path
from uuid import UUID

import requests


def run_workflow(base_url, payload, *, api_key="", timeout=900, poll_interval=2):
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("timeout and poll_interval must be positive")
    # Require a durable caller-generated identity so a timeout/restart does not
    # accidentally start a second paid workflow with another generated UUID.
    workflow_id = str(UUID(str(payload["workflow_id"])))
    base = base_url.rstrip("/")
    headers = {"x-api-key": api_key} if api_key else {}
    deadline = time.monotonic() + timeout
    with requests.Session() as session:
        response = session.post(base + "/api/v1/editorial/workflows", json=payload,
                                headers=headers, timeout=min(30, timeout))
        response.raise_for_status()
        if response.json()["data"]["workflow_id"] != workflow_id:
            raise RuntimeError("MPT returned an unexpected workflow ID")
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            response = session.get(base + f"/api/v1/editorial/workflows/{workflow_id}",
                                   headers=headers, timeout=max(0.1, min(30, remaining)))
            response.raise_for_status()
            result = response.json()["data"]
            if result["state"] == 1:
                return result
            if result["state"] == -1:
                raise RuntimeError(f"Workflow {workflow_id} failed at {result.get('failed_stage')}: {result.get('error')}")
            if result.get("interrupted"):
                raise RuntimeError(f"Workflow {workflow_id} was interrupted; resubmit the same input to resume")
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Workflow {workflow_id} is not complete; keep its ID to resume or continue polling")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON request including a stable workflow_id")
    parser.add_argument("--output", required=True, type=Path, help="new file for the full editorial result")
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; choose a new output path")
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = run_workflow(args.api_url, payload, api_key=os.environ.get("MPT_API_KEY", ""), timeout=args.timeout)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"workflow_id": result["workflow_id"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
