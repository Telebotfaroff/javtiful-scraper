"""Run the Telegram bot and hand off to a fresh Actions run after a safe interval.

The next run is dispatched before this process exits. The workflow concurrency
group queues that run until the current runner releases the group.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import requests


def dispatch_next_run() -> bool:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    workflow = os.getenv("AUTO_RESTART_WORKFLOW", "start-javdl-telegram-bot.yml").strip()
    ref = os.getenv("AUTO_RESTART_REF", "main").strip()
    if not repository or not token:
        print("AUTO-RESTART: missing GITHUB_REPOSITORY or GH_TOKEN; cannot dispatch.", flush=True)
        return False

    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"
    try:
        response = requests.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "JAVDL-Workflow-Handoff",
            },
            json={"ref": ref},
            timeout=20,
        )
        if response.status_code != 204:
            print(
                f"AUTO-RESTART: dispatch failed ({response.status_code}): "
                f"{response.text[:500]}",
                flush=True,
            )
            return False
        print(f"AUTO-RESTART: queued next workflow run from ref {ref}.", flush=True)
        return True
    except requests.RequestException as exc:
        print(f"AUTO-RESTART: dispatch request failed: {exc}", flush=True)
        return False


def stop_process(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is not None:
        return int(process.returncode or 0)
    print("AUTO-RESTART: stopping bot cleanly for runner handoff.", flush=True)
    process.send_signal(signal.SIGTERM)
    try:
        return process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        print("AUTO-RESTART: bot did not stop in time; sending SIGKILL.", flush=True)
        process.kill()
        return process.wait()


def main() -> int:
    try:
        restart_after = max(60, int(os.getenv("AUTO_RESTART_AFTER_SECONDS", "14400")))
        retry_seconds = max(15, int(os.getenv("AUTO_RESTART_RETRY_SECONDS", "60")))
    except ValueError:
        print("AUTO-RESTART: timer environment values must be integers.", flush=True)
        return 2

    command = [sys.executable, "main.py"]
    print(
        f"AUTO-RESTART: starting bot; handoff target is {restart_after} seconds.",
        flush=True,
    )
    process = subprocess.Popen(command)
    deadline = time.monotonic() + restart_after

    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(5, remaining))

    if process.poll() is not None:
        code = int(process.returncode or 0)
        print(f"AUTO-RESTART: bot exited before handoff (exit={code}); not dispatching.", flush=True)
        return code

    # Keep the current bot alive if dispatch is temporarily unavailable. Retry
    # until the next run is accepted; only then stop this runner.
    while process.poll() is None:
        if dispatch_next_run():
            stop_process(process)
            return 0
        print(f"AUTO-RESTART: will retry dispatch in {retry_seconds} seconds.", flush=True)
        end = time.monotonic() + retry_seconds
        while process.poll() is None and time.monotonic() < end:
            time.sleep(min(5, end - time.monotonic()))

    return int(process.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
