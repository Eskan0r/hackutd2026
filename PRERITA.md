# Prerita — build the alarm, emergency stop, and run controller

Read [MVP.md](MVP.md) first. Your job is to coordinate the experiment and prove the agent actually stopped.

Your code is the smoke alarm. It watches a trusted service log for a fixed signal. It does not ask a model whether there is a fire. After stopping the agent, it checks the switch really worked.

## What you own

- `defender/`: event reader, fixed trigger, stop levers, independent verification.
- Controller API, run state, policy application orchestration, and `result.json`.
- Integration of Ronak's environment, Riyan's runner, and Yash's analysis module.

## Tasks in order

- [ ] **Read one trusted event file.** Support appended JSONL and partial lines. Process only the active run ID and trusted producer path. `source=answer-key` plus `severity=fire` triggers once; duplicate events must not cause duplicate stop jobs.
- [ ] **Implement the stop path.** Deny the run at Riyan's gateway, disconnect its lab network where applicable, then pause/stop its workload through host-side Docker control. Attempt remaining levers even when one fails. Bound each operation with a timeout. OpenShell has different networking: record a nonapplicable network lever honestly.
- [ ] **Verify independently.** Inspect workload state and network membership where applicable; verify the gateway deny state. Never turn a successful API return alone into `stop_verified=true`. On failed verification, report failure and attempt a final stop/kill.
- [ ] **Measure actual timing.** Store the fire timestamp, each lever's attempt/result, and verified-stop timestamp. Write actual `ttk_ms` only when verification succeeds. Distinguish a late-written log from a new action after stopping; preserve evidence rather than hiding ambiguous events.
- [ ] **Complete the manual integration first.** Ronak sends a request from a disposable workload; you stop that workload. Confirm a subsequent request cannot execute. Then repeat with Riyan's scripted runner.
- [ ] **Build the controller endpoints in MVP.md.** One active run at a time. Start services and arm the defender before starting the agent. Validate run IDs and fixed policy/mode/variant choices. Persist state so the dashboard can poll.
- [ ] **Implement the supported fix.** Accept only `deny_destination` for `answer-key`. Use Ronak's policy builder and Riyan's tool policy to create the `after` configuration. A fix prepares a fresh run; it never unpauses the old agent.
- [ ] **Orchestrate the proof.** Variant-B deliberate access must be denied; the normal company-API request must succeed. Set result fields from evidence, not from Nemotron's opinion or the agent's claim.
- [ ] **Connect Yash's analysis module after the stop.** Run it asynchronously with a timeout; preserve deterministic results even if analysis fails. Expose its source label and proposal to the dashboard.

## Hand off early

To Ronak: trusted event contract and start/rebuild requirements. Ask for container identity and inspect fields before writing Docker assumptions.

To Riyan: run lifecycle, gateway deny contract, run IDs, and where completion/errors should go.

To Yash: the API shapes in MVP.md, one saved example result, and how to call his analysis module. Serve his static dashboard from the same backend to avoid unnecessary deployment work.

## How you know your part works

1. A manual answer-key request triggers exactly one stop sequence.
2. Failed Docker/gateway operations show failure; they never produce a green verified badge.
3. An already-stopped run cannot make a fresh tool request.
4. Service/model errors are failed runs, not security passes.
5. Apply-fix starts a fresh configuration; variant-B denial and allowed-task success are recorded separately.

## Do not build yet

Confidence interval dashboards, signing, CI integration, SQLite if JSON files suffice, production-log ingestion, or generalized policy repair. Preserve clean evidence so these can be added later.

## Your first move

Make a tiny trusted answer-key event trigger a stop of a disposable test workload. Get the verified stop working before building the controller UI API.
