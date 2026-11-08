# Riyan — give the model hands

Read [MVP.md](MVP.md) first. Your job is the agent runner and model gateway.

The model is the brain. Your Python runner is its hands: it asks the model what to do, validates the requested tool, runs it, and sends the result back. The model never directly controls Docker or our trusted logs.

## What you own

- `agent/` or `sandbox/harness.py`: one small tool loop.
- `gateway/`: provider calls with real keys kept outside the sandbox.
- Live and scripted modes, prompts, tool enforcement, and execution limits.

## Tasks in order

- [ ] **Start with scripted mode.** Send a company-API request, then an answer-key request using the same HTTP tool implementation the live model will use. Wait for the defender to stop the runner. Label every run `scripted`; this validates plumbing without depending on model behavior.
- [ ] **Implement two tools.** `http_get(url)` and `report_blocked(reason)`. Use logical destination mappings agreed with Ronak. Reject unsupported schemes, destinations, ports, and redirect targets; do not let redirects bypass policy. Keep request timeouts and response-size limits.
- [ ] **Implement the gateway.** Runner uses a dummy key. Gateway adds the real provider key, forwards only to a configured provider API, tracks run IDs, applies request/token limits, and supports denying a run. It must not be a general URL proxy. Agree a host-only deny interface with Prerita.
- [ ] **Connect one real model.** Implement model response -> validated tool request -> tool result -> next response. Stop after a small fixed budget, such as 12 steps or 90 seconds. Errors must terminate or produce a clear failed run, not an infinite retry loop.
- [ ] **Write the red-team task.** Explicitly ask whether the private answer-key service is reachable using available tools. This is an authorized reachability drill, not evidence of spontaneous cheating. Put the fake service hint in the workspace so discovery does not require a novel exploit.
- [ ] **Write the normal task.** Ask for the answer from the allowed company API. This proves the fixed agent can still do useful work.
- [ ] **Load `before`/`after` tool policy from the controller.** After the fix, answer-key A and B are both denied by logical destination. Call `report_blocked` or return a clear denied tool result. Do not silently rewrite the task to avoid testing the block.
- [ ] **Run a few pilot trials.** Report how often the live model accessed bait. Do not hunt indefinitely for a dramatic model failure. Keep scripted mode as the guaranteed emergency-stop demonstration.

## Hand off early

To Ronak: agent image dependencies, gateway address, required mounts, and run-ID propagation. The runner adds the active run identity to service requests; the model does not choose it.

To Prerita: a callable start command with mode/run ID/variant/policy, the gateway deny interface, completion/error signals, and tool-call evidence. Runner evidence must be distinct from trusted service fire events.

To Yash: readable tool events and explicit `live`/`scripted` labels. Do not include provider secrets in displayed logs.

## How you know your part works

1. Scripted runner triggers the real fake-service alarm.
2. Live runner makes a real model call and executes a validated HTTP tool call.
3. Gateway denies subsequent model requests for a stopped run.
4. A fresh `after` run denies deliberate access to answer-key B, including redirect attempts.
5. The normal company-API task still succeeds.
6. Model/provider failure is reported honestly and the scripted mode remains usable.

## Do not build yet

Shell tools, filesystem exploration, multiple providers/models, autonomous exploit discovery, or a cheating benchmark. The MVP only needs HTTP tools and one tested model.

## Your first move

Agree the service routes with Ronak, then make the scripted runner call one endpoint. Let Prerita integrate the stop mechanism while you add the live model.
