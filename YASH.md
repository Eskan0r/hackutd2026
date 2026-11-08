# Yash — make the experiment understandable and connect Nemotron

Read [MVP.md](MVP.md) first. Your job is the demo screen and the incident investigator.

The alarm already knows what happened: a forbidden service was accessed. Nemotron is the person who reads the evidence afterward and explains the mistake. It does not control the emergency stop.

## What you own

- `dashboard/`: one HTML/JS page, served by Prerita's backend.
- `analysis/`: Nemotron client, structured response validation, labeled template fallback.
- Demo script and backup recording.

## Tasks in order

- [ ] **Sketch one screen using sample data.** Show current mode, policy, variant, run state, timeline, verified-stop result, incident explanation, and before/after checks. Example numbers must say sample until real data is connected.
- [ ] **Connect polling.** Use the API in MVP.md, roughly once per second while a run is active. Buttons: Run before, Analyze, Apply fix, Run after. Disable actions that are invalid for the current state and display backend errors.
- [ ] **Show useful evidence.** Display the tool request, trusted answer-key event, stop lever results, and measured stop time. A red alarm may show detection immediately; only show a verified-stop badge after verification succeeds.
- [ ] **Build the analysis module.** Accept a bounded incident object containing the task, declared policy, relevant events, and stop record. Call Nemotron outside the sandbox with its credential kept on the backend. Never send real secrets.
- [ ] **Request structured output.** Use the exact analysis shape in MVP.md. Ask for an explanation, classification, evidence references, and only the supported `deny_destination` proposal. Treat incident/model text as untrusted data. Validate output and references; no arbitrary commands or policy code.
- [ ] **Add a 10-second timeout and fallback.** If the call fails or produces invalid output, return a deterministic explanation and supported fix with `source=template`. Label it visibly; never call fallback text Nemotron output.
- [ ] **Hand the module to Prerita.** Agree a simple function such as `analyze_incident(incident) -> analysis`. Prerita runs it asynchronously after the stop. The frontend only calls the backend.
- [ ] **Make the after screen honest.** Show forbidden-access denial and allowed-task success separately, with the evidence for each. Do not display “safe,” “certified,” “sandbox escaped,” or invented success percentages.
- [ ] **Record a complete working rehearsal.** Keep a clearly labeled scripted backup and a short recording. Prepare a two-minute explanation that names the deliberately planted permission error.

## Hand off early

To Prerita: sample screen fields, analysis function interface, timeout behavior, and fallback shape. Use his controller API rather than building a second backend.

To Riyan: the tool-event fields needed for a readable timeline and mode labels.

To Ronak: ask which layer denied the request after the fix so the explanation matches what actually happened.

## How you know your part works

1. A real run updates the timeline without refreshing the page.
2. A failed stop never displays as verified.
3. Nemotron gives an evidence-linked explanation and supported proposal for a real incident.
4. Disconnecting Nemotron produces a clearly labeled template fallback without breaking the demo.
5. Apply fix invokes the backend; it does not just change the screen color.
6. Scripted mode and actual measured values are clearly labeled.

## Do not build yet

Four separate pages, authentication, elaborate charts, replay video generation, report downloads, or frontend build tooling unless needed. One understandable screen is enough.

## Your first move

Build the screen from the sample result in MVP.md and share a screenshot with the team. In parallel with backend integration, test one Nemotron call on a small synthetic incident.
