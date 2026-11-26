#!/usr/bin/env python3
"""Proves the SENDER half: a live-owner spawn row now carries the payload's identity.

Loads a bot_mode_dm.py as a module (the real functions, unmodified), spawns a real background
process through the real `_spawn_delivery`, and prints the spawn row the delivery journal got.

Usage: spawn-identity-probe.py <bot_mode_dm.py> <old|new>
   old -> call as the live branch did before the fix (no payload named)
   new -> call as the live branch does now (journal_dm_file=payload)
"""
import importlib.util
import json
import os
import pathlib
import shutil
import sys

BASE = pathlib.Path("/opt/data/profiles/builder/cache/scratch/dl-fix/probe")


def main() -> int:
    script, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
    journal = BASE / f"spawn-{mode}" / "journal"
    if journal.parent.exists():
        shutil.rmtree(journal.parent)
    journal.mkdir(parents=True)
    payload = BASE / f"spawn-{mode}" / "dm-spawn-probe.txt"
    payload.write_text("probe body: " + "the spawn row must name the payload it handed off", encoding="utf-8")
    os.environ["HERMES_DELIVERY_OUTCOME_DIR"] = str(journal)

    spec = importlib.util.spec_from_file_location("bot_mode_dm_probe", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._DELIVERY_OUTCOME_DIR = journal

    delivery_id = "cd" * 32
    if mode == "old":
        ack = module._spawn_delivery("sleep 1", "dlprobe", delivery_id=delivery_id, task_id=None, agent=None)
    else:
        ack = module._spawn_delivery("sleep 1", "dlprobe", delivery_id=delivery_id,
                                     journal_dm_file=str(payload), task_id=None, agent=None,
                                     sender="bot:builder")
    rows = [json.loads(line) for line in (journal / "outcomes.jsonl").read_text().splitlines() if line.strip()] \
        if (journal / "outcomes.jsonl").exists() else []
    print(json.dumps({"ack": json.loads(ack), "spawn_rows": [{k: r.get(k) for k in
           ("outcome", "delivery_id", "payload_id", "body_sha16", "body_len", "target", "proc")} for r in rows]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
