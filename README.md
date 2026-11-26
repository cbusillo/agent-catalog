# agent-catalog

Tools and instructions that Chris's coding agents share across repositories.

It is built for Chris's own system. It may assume that system, including Launchplane. It does not try to work the same for someone who runs a different one.

## What gets in

A piece enters only after a real repository has used it for real work. Nothing is added because it might be useful.

Every piece follows the same four rules as Launchplane:

1. Guard only what cannot be undone. Everything else may fail, says why, and is safe to run again.
2. Look, don't remember.
3. Every piece points to a real use or a named protection.
4. Plain steps that are safe to run twice.

## What stays out

- Anything a harness already does by itself.
- Records kept on GitHub for agents to read back. What needs remembering lives in Launchplane.
- Private details: host names, addresses, keys, people. This repository is public.

## Pieces

- **Python inspection** (`inspect-python`): runs PyCharm's inspector on a repository and answers `clean`, the findings, or `UNKNOWN`. It proves each of its checks on planted mistakes before it may say `clean`. First used by `launchplane-next`. See [docs/python-inspection.md](docs/python-inspection.md).
- **[Outside review](skills/outside-review/SKILL.md)**: ask a different provider to read a local change, then check its findings in the requesting session. First used to weigh an independent review of this catalog's Python inspector.

To add the review skill to a project, run the following from that project's root with `catalog` set to the path of this checkout. Choose the agent you use, or install for both.

```sh
gh skill install "$catalog" outside-review --from-local --scope project --agent codex
gh skill install "$catalog" outside-review --from-local --scope project --agent claude-code
```
