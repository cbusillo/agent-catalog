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
- Use **[Start work](skills/start-work/SKILL.md)** to prepare or resume a repository change in the working copy provided by the host's approved procedure. A read-only reviewer can use the checkout it receives.

Set `catalog` to this checkout and `skill` to `outside-review` or `start-work`.

For a seat that works across checkouts, set `seat_config` to its configured profile directory (`CLAUDE_CONFIG_DIR` for Claude Code or `CODEX_HOME` for Codex). Check where the profile’s `skills` directory resolves. Every seat sharing that directory gets the installation. In Codex, `skills.include_instructions` controls whether the skill description appears in the prompt.

```sh
gh skill install "$catalog" "$skill" --from-local --dir "${seat_config:?set the intended profile directory}/skills"
```

For a single checkout, run the command for your harness from that checkout. A project install writes local files there. A fresh linked checkout only inherits tracked files, and a local skill install records its source path.

```sh
gh skill install "$catalog" "$skill" --from-local --scope project --agent codex
gh skill install "$catalog" "$skill" --from-local --scope project --agent claude-code
```

Installing `start-work` makes the guidance available to the agent. Command blocking requires a separately configured harness rule.
