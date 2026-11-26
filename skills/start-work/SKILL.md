---
name: start-work
description: Start or resume implementation of an issue, fix, or requested repository change in the right working copy. Use before the first edit. Reviews and read-only investigation can use their existing checkout.
---

Identify the repository, its default branch, your current working directory and local changes. When resuming, find the existing linked worktree for this task and verify its branch and edits. Continue there.

For a new task, use the full task-start command named in the repository instructions or its operations guide. If neither names it, use the following lookup for the host’s private operations repository.

- Read the first `local-context.toml` that sets `[docs].local_infra`. Check `$CODE_HOME` and `$CODEX_HOME` when set, then `~/.code`.
- In that repository, open the environment guide named by `docs.environment` in `.github/github.json`, or follow the development environment link in its docs index. Worktree Placement names the approved command and its arguments. Keep private values local.

Run that command from the source checkout with a meaningful task name and the requested starting revision, normally the remote default branch. It handles storage placement and guarded cleanup. A similarly named creator on PATH or a harness shortcut can skip those steps.

Use ordinary start by default. When the request explicitly requires preserving other tasks' worktrees or evidence, use the documented scoped mode (`--task-only` on the current coordinator). If the coordinator refuses, follow its reason. On a name collision, check ownership before resuming or choose a fresh name.

For a new task, verify the branch and starting commit in the directory the coordinator returns. Make edits only in the verified task worktree. If you can neither verify an existing task worktree nor create one through the approved procedure, stop and report what is missing.
