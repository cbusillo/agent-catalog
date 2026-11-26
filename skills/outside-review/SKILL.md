---
name: outside-review
description: Get a read-only second opinion on a local change when someone asks for an outside, independent or named-model review, and check the findings before advising them.
---

Use a provider different from the one that wrote the change. Honor a named reviewer and the user's existing provider order, models and signed-in accounts. Check the selected login if a metered API credential might take precedence. When no reviewer is named, Codex can ask Claude and Claude Code can ask Codex. If authorship is unknown, say what independence you can verify. Report an unavailable or non-independent choice to the requester.

1. Identify the local change and the question. Inspect the diff and choose enough surrounding source for a reviewer to challenge the change. Send only material authorized for that provider. Keep secrets, unrelated files, transcripts and account details out. For a historical change, take context from the reviewed revision.
2. Pipe the Git diff into this skill's `scripts/review` and pass the selected context files as paths relative to your current directory. The launcher gives the reviewer a private temporary directory with those inputs. Context files get a `.txt` suffix so project configuration is read as data. For example, from a checkout of the target revision:

   ```sh
   set -o pipefail
   git diff --no-ext-diff --no-textconv "$base" "$tip" -- "$file" |
     bash "$skill_dir/scripts/review" claude "$file"
   ```

   For staged and unstaged changes together, use `git diff HEAD`. Git omits new untracked files; for one new file, capture `git diff --no-index -- /dev/null "$file"` and use its patch (exit 1 means differences). Set `REVIEW_QUESTION` for a specific question and `REVIEW_MODEL` for the requested CLI model ID. The reviewer choices are `claude`, `codex` and `gemini` (Antigravity). Use the local provider's existing model list when a name needs resolving.

3. Capture stdout **and stderr** in a private log (`> "$log" 2>&1`). Let long runs finish using the harness's background command support. Inspect the final result and read evidence in that log. A source-specific observation can establish a read when the CLI omits tool events. Report the model the CLI confirms, or label it requested if unconfirmed. Report any missing context, blocked required read, model substitution or incomplete answer.
4. Weigh the report. Verify each material claim in the actual checkout with the smallest relevant read or test. Tell the requester what reproduced, what you disagree with and why, and what remains uncertain. Keep the report in the session. Changes, posts and merge decisions require their own authority.

For Gemini, the reviewer tool restrictions apply to model actions. Antigravity's trusted lifecycle hooks still run. Use a login whose active host integrations are appropriate for the review. Normal account-usage reporting may continue; flag a hook or integration that could modify the project or send review material elsewhere before launching.
