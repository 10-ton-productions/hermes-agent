#!/usr/bin/env python3
"""Throwaway-target proof for the live-delivery journal fix.

Runs the REAL `--run-delivery` entry of a given bot_mode_dm.py against a THROWAWAY profile home
(never under /opt/data/profiles, so it can never join the fleet) and checks what the delivery
journal received.

Input state is fabricated (a pinned intent beside the payload + a mailbox receipt with a chosen
status); every line of delivery code executed is the real one, from the real runner process.

Usage: dl-journal-probe.py <bot_mode_dm.py> <settled|failed|queued>
Prints one JSON object: {"rc":…, "journal_rows":[…], "mailbox_status":…}
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

BASE = pathlib.Path("/opt/data/profiles/builder/cache/scratch/dl-fix/probe")
DELIVERY_ID = "ab" * 32  # 64 lowercase hex chars


def build(home: pathlib.Path, status: str) -> pathlib.Path:
    if home.exists():
        shutil.rmtree(home)  # our own throwaway dir, created by this script
    (home / "runtime" / "bot_live_delivery").mkdir(parents=True)
    (home / "journal").mkdir()
    dm = home / "dm-probe.txt"
    body = "probe body: the fix writes a terminal row where the live path used to write none"
    dm.write_text(body, encoding="utf-8")
    owner = {"profile_home": str(home), "session_id": "probe-session",
             "lease_id": "probe-lease", "live_session_id": "probe-live"}
    (pathlib.Path(str(dm) + ".live.json")).write_text(
        json.dumps({"owner": owner, "message": body, "delivery_id": DELIVERY_ID}), encoding="utf-8")
    receipt = {"delivery_id": DELIVERY_ID, "id": DELIVERY_ID, "owner": owner, **owner,
               "message": body, "status": status, "created_at": time.time_ns(), "sequence": 1}
    if status == "settled":
        receipt.update(reply="receipt from the throwaway owner", completed_at=time.time_ns())
    (home / "runtime" / "bot_live_delivery" / f"{DELIVERY_ID}.json").write_text(
        json.dumps(receipt), encoding="utf-8")
    return dm


def main() -> int:
    script, status = sys.argv[1], sys.argv[2]
    home = BASE / f"home-{status}"
    dm = build(home, status)
    env = dict(os.environ, HERMES_DELIVERY_OUTCOME_DIR=str(home / "journal"),
               HERMES_HOME=str(home), PYTHONPATH="/opt/hermes")
    proc = subprocess.run([os.environ.get("DL_PROBE_PY", sys.executable), script, "--run-delivery", "query-file", str(dm),
                           "--profile-home", str(home), "-p", "dlprobe", "hermes", "chat", "-q"],
                          capture_output=True, text=True, timeout=120, env=env)
    journal = home / "journal" / "outcomes.jsonl"
    rows = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()] \
        if journal.exists() else []
    print(json.dumps({"rc": proc.returncode, "journal_rows": rows,
                      "stdout_tail": proc.stdout.strip().splitlines()[-2:],
                      "stderr_tail": proc.stderr.strip().splitlines()[-2:],
                      "payload_kept": dm.exists()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
