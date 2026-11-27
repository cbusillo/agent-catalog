---
name: harness-test
description: Test whether a fresh Claude Code or Codex session discovers a skill, follows an instruction, or takes the intended action. Use for behavioral trials and controls when changing catalog skills or harness configuration.
---

Start with one concrete claim from real work. Write down the observation that would prove it and what should happen without the change. Keep that answer and the evidence outside the test workspace. Give both sessions the same ordinary task.

**Choose the least costly proof.** For discovery, first inspect the native skill list or rendered prompt in the intended profile and checkout. Codex provides `codex debug prompt-input`; For Claude, submit only the SDK control request below and inspect the names in `response.response.commands`. Repeat with the skill absent. Neither check requires an inference call. For a behavior trial, start with a low-cost model at low effort on the actual harness. Use the same model and effort in both arms. Step up only when the task needs a capability the cheaper model lacks or the claim is about a particular production model. Record why. An unavailable model, unexpected substitution, or failed control leaves the claim unproven.

```sh
printf '%s\n' '{"type":"control_request","request_id":"discovery","request":{"subtype":"initialize"}}' |
  claude -p --no-session-persistence --strict-mcp-config --verbose --input-format stream-json --output-format stream-json
```

**Compare two fresh responses.** Use the runner for a decision expressed in the answer from workspace instructions. It restricts integrations and overrides user settings. Test installed skills, hooks and profile configuration through their normal native entry points. Prepare two trusted, disposable case directories outside other repositories with the relevant files in the layout the harness actually loads. Name ordinary input files the subject should read unless finding them is the behavior under test. Change only the behavior under test. Use the intended signed-in test account and keep credentials, unrelated files and previous answers outside both cases. From this skill's directory, run:

```sh
scripts/compare claude "$control" "$candidate" "$evidence_parent" < "$task"
scripts/compare codex  "$control" "$candidate" "$evidence_parent" < "$task"
```

For a publishing handoff, use real disposable Git checkouts with a prepared, uncommitted edit. Check the returned owner, branch and path against Git. Prove a real push separately from an answer about who should push.

Choose just the harnesses the claim covers. The runner starts a fresh native process per directory with inexpensive defaults. It saves the exact task, requested model and effort, answer, native output and errors in a new private evidence directory. Use `HARNESS_TEST_MODEL` (an exact model ID) or `HARNESS_TEST_EFFORT` to override the defaults for a justified trial. Claude checks the model reported in native usage. Codex JSONL and stderr contain turn usage and available routing evidence. Report a Codex model as requested if the backend identity is unavailable. A zero exit means the sessions answered. Judge each answer against the observation chosen before the run. Record mixed results across fresh repetitions rather than retrying until one passes.

**Test actions where they run.** The response comparison restricts tools and integrations. For actual Claude plugin selection or tool calls, prefer `claude plugin eval` with a trusted fixture, a deterministic grader, `--model MODEL_ID`, `--runs 1` and `--no-publish`. For a native hook or command block, exercise the normal tool with the same harmless operation and permissions in disposable enabled and disabled cases. Check the resulting file, hook event or tool trace. A refusal in prose, or a tool removed by the test runner, cannot prove the installed guard fired. Use the normal profile when that profile's configuration is what the test must exercise.

Report the task, harness and model, control and candidate observations, and which conclusion they support. Keep the raw evidence local.
