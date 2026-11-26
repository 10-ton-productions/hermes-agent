# Live-delivery journal gap: the fix (not merged, not deployed)

The delivery journal on this box records every send twice — a `spawned` row when the wrapper hands
the message to a process, a terminal row (`delivered` / `delivery_failed` / `target_busy` / …) when
that process finishes. A spawn row with no terminal row is what the ops settle pass
(`/opt/data/profiles/ops/scripts/delivery-spawn-settle.py`) reports as `unsettled`.

**A delivery admitted to a live Bot Chat owner could never be paired.** Two holes, both on that one
path, both in the deployed 90 KB wrapper generation (`/opt/hermes/tools/bot_mode_dm.py`,
sha256 `78b0506fc2f350e3841e008a4ef159d2692f91a285cb7e1b9d4030eb193a6bf6`, mtime 2026-11-15 08:18):

1. **The spawn row carried no identity.** `_start_delivery`'s live branch called
   `_spawn_delivery(command, label, task_id=…, agent=…)` — no `dm_file`, no `delivery_id` — so
   `_journal_spawn(None, delivery_id="")` wrote `payload_id: null`, no `body_sha16`, `delivery_id:
   null`. The caller held `record["delivery_id"]` on the line above and the payload path two lines
   above that.
2. **The runner wrote no terminal row.** The live branch returns out of `_wait_live_dm`, while
   `_journal_delivered` (line 1339) and `_journal_delivery_failure` (line 1149) live in the CLI-turn
   lane, which this path never enters. So even a settled delivery left the spawn row unpaired.

Neither hole is by design: the wrapper's own docstrings say the spawn row exists so "a settlement
pass can mark an unpaired row `unsettled` with its elapsed time", and that the body identity is
computed at spawn "because this is the last moment the file is guaranteed to exist".

## Evidence (2026-11-26, `proc_f53f15286575`)

| fact | value |
|---|---|
| ack returned to the sender | `delivery_id 20c130b6…`, `process_id proc_f53f15286575` |
| spawn row (journal line 5288) | `delivery_id: null`, `payload_id: null`, no `body_sha16` |
| runner exit | `completed normally (exit code 0)` |
| arrival | chief-of-staff store, 03:23:31Z, body tail equals the sent body exactly (`sha16 60080e76360a99ef`, `body_len 4649`) |
| settle verdict | `unsettled`, `elapsed_seconds: 469.9` |

The message arrived. The journal could not see it — a missing instrument, not a lost delivery.

Fleet blast radius, spawn rows after the wrapper generation: **80 identity-less of 2,112**
(chief-of-staff 61, builder 9, ops 8, researcher 2). **65 of 96 `unsettled` verdicts** point at those
rows.

### The other 31 — traced to the body, 2026-11-26

Those 31 had identity, so each one can be followed to its sender's `message_agent` call and its exact
body. All 31 were recovered that way (the delivery body equals `"Message from <name> (@<handle>): "`
plus the call's message). Looking each body up in the target's own `state.db`:

| verdict | count | how it was decided |
|---|---:|---|
| arrived, settle missed it | 5 | a `role='user'` row in the target store holds the body |
| no copy in any user row of the target store | 26 | neither the first nor the last 150 chars of the body appear |
| of those, sender told it failed | 2 | sender store holds the run's failure notification |
| **of those, nothing on either side** | **24** | no copy in the target, no failure notice to the sender |

(An earlier pass reported 18/13; that test counted matches in any role, so an assistant row quoting
the message read as an arrival. `role='user'` is the only row a delivery writes.)

**Twenty-four sends have no arrival and no failure record: 19 to ops, 1 to chief-of-staff, 4 to
builder (2026-11-26, 02:53–03:25).** Of the 5 that arrived, 2 were judged before the owner wrote its
row and 3 were judged after the row existed and still missed — a matcher false negative, separate
from both defects here. The builder four are the strongest case because the sender said so in
writing — chief-of-staff's next message to builder (04:11:16Z) opens *"Fresh order, re-issued because
the original never landed."*

**That reverses the earlier verdict.** The journal cannot report a delivery it made (the defect this
patch fixes), **and the live lane can also lose one silently** — the ack says `queued`, the target
store never gets the row, and no terminal journal row exists to contradict it. The sender's only
signal is that nothing came back.

This patch does not stop that loss. It makes it visible and traceable: with `delivery_id`, payload id,
body digest and **sender** on the spawn row, a missing arrival is one query per row instead of a
7,105-call sweep across 33 stores.

## The patch

`bot_mode_dm.py.78b0506f.patch` (138 lines) against the deployed blob:

- `_journal_live_terminal(...)` — one new writer. `settled` → `delivered`; `failed` / `cancelled` →
  `delivery_failed` with the owner's reason. `queued` / `claimed` / `ambiguous` write **nothing**:
  "still in flight" and "cannot tell" are the settle pass's verdicts, and a row claiming either would
  close the spawn silently — the same defect one layer up.
- `_wait_live_dm` — calls it with the receipt's status, the payload name and the elapsed wait, before
  the settled branch unlinks the payload.
- `_spawn_delivery(journal_dm_file=…)` — names the payload for the journal **only**. File ownership
  is deliberately not transferred on the live branch: the mailbox already holds the message, so
  unlinking there on a spawn failure would destroy the last local copy of a delivery the mailbox says
  is queued.
- `_start_delivery` live branch — passes `delivery_id=record["delivery_id"]` and
  `journal_dm_file=dm_file`.
- **`sender` on the spawn row.** `_journal_spawn` grows an optional `sender`, `_spawn_delivery`
  passes it through, and both lanes hand it `(author or {}).get("id")`. Without it a lost row cannot
  be traced to its sender without sweeping every profile store — which is how the 31 above were
  traced, at 7,105 candidate calls.

## Proof (re-run against a throwaway target, real processes)

`probe-dl-journal.py` builds a throwaway profile home (never under `/opt/data/profiles`, so it cannot
join the fleet) holding a pinned intent and one mailbox receipt, then runs the real
`--run-delivery` entry and prints what the journal got.

```
base   (settled): rc 0, journal rows []
patched(settled): rc 0, journal rows [{outcome: delivered, delivery_id: abab…, payload_id: dm-probe.txt, waited_seconds: 0}]
patched(failed) : rc 1, journal rows [{outcome: delivery_failed, detail: "live owner reported failed"}]
```

`probe-spawn-identity.py` calls the real `_spawn_delivery` and prints the spawn row:

```
old call: payload_id null           body_sha16 null               body_len null  sender null
new call: payload_id dm-spawn-…txt  body_sha16 c0735c27577c33a4   body_len 61    sender bot:builder
```

Statuses `queued` / `claimed` / `ambiguous` were driven through the new writer directly: 3 rows for
6 statuses (settled, failed, cancelled), none for the pending three.

## Activation

- **Runner half (terminal row)** takes effect the moment the file is patched: every delivery spawns a
  fresh interpreter executing `/opt/hermes/tools/bot_mode_dm.py`.
- **Sender half (spawn identity)** runs inside long-lived processes. Every process that calls
  `message_agent` must cycle: the gateway, and each seat's own Bot Chat process. Patching the file
  does not reach a module already imported.

Nothing here has been applied to `/opt/hermes` and nothing has been merged.

## Applying / reverting

```sh
cd /opt/hermes/tools
sha256sum bot_mode_dm.py     # must be 78b0506fc2f350e3841e008a4ef159d2692f91a285cb7e1b9d4030eb193a6bf6
patch --dry-run -p0 < bot_mode_dm.py.78b0506f.patch
cp -p bot_mode_dm.py bot_mode_dm.py.bak-$(date -u +%Y%m%dT%H%M%SZ)
patch -p0 < bot_mode_dm.py.78b0506f.patch
# revert: restore the .bak file; the patched file is also recoverable from this directory
```

`bot_mode_dm.patched.py.txt` is the same result for reading; its sha256 is the one in `SHA256SUMS`
(currently `78adf6b09a0a30c947e8b824b71b15d5f63e1bc74a159dfcd1b5315d54e56ee0`).

## Still open

- **The loss itself is on the consumer side, not here.** A mailbox receipt can settle without the
  target turn ever writing its user row, and the receipt is deleted at settlement, so nothing survives
  that could say "taken, never written". The instrument that closes this: the consumer records the
  arrival row id on the receipt, and a receipt that settles with no arrival id is itself the alarm.
  Until that exists, a lost send is detectable only because the sender notices the silence.
- A live **admission** failure (the `except` in `_start_delivery`, and `_run_delivery` printing
  `ambiguous`) returns a typed ack but writes no journal row at all — no process, so no spawn row and
  nothing to pair. The sender is told; the journal is silent.
- The deployed 90 KB generation exists in **no** git history on this box (upstream `origin/main` has
  none of the journal code; the fork's file is 59,464 B). Provenance is unresolved, and this patch is
  the only versioned record of a change to it.
- Upstreaming the journal lane itself is a separate, much larger piece of work.
