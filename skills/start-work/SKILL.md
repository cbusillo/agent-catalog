---
name: start-work
description: Start or resume implementation of an issue, fix, or requested repository change in the right working copy. Use before the first edit. Reviews and read-only investigation can use their existing checkout.
---

Identify the repository, its default branch, your current working directory and local changes. When resuming, find the existing linked worktree for this task and verify its branch and edits. Continue there.

For a new task, look up the full task-start command in the repository instructions or the host's operations documentation. Use that entry point from the source checkout with a meaningful task name and the requested starting revision, normally the remote default branch. It owns the host's storage placement and guarded cleanup. A lower-level creator on PATH or a harness shortcut can omit these steps.

Use ordinary start by default. When the request explicitly requires preserving other tasks' worktrees or evidence, use the documented scoped mode (`--task-only` on the current coordinator). If the coordinator refuses, follow its reason. On a name collision, check ownership before resuming or choose a fresh name.

For a new task, verify the branch and starting commit in the directory the coordinator returns. Make edits only in the verified task worktree. If you can neither verify an existing task worktree nor create one through the approved procedure, stop and report what is missing.
