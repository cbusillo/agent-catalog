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

None yet. The first is the PyCharm inspection wrapper, moving here from `launchplane-next`.
