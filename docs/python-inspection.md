# Python inspection

`inspect-python` runs PyCharm 2026.3's command-line inspector on the repository in the current folder. It prints `clean`, the findings, or `UNKNOWN` with the reason. Exit codes: 0 clean, 1 findings, 2 unknown.

A repository calls it pinned to a release:

```sh
uvx --from git+https://github.com/<owner>/agent-catalog@v0.1.0 inspect-python
```

## Settings

- `INSPECT_PYTHON_PYCHARM`: the PyCharm application. Default `~/Applications/PyCharm.app`.
- `INSPECT_PYTHON_HOME`: the folder PyCharm uses as its home while inspecting. Default `~/.cache/inspect-python`.

The repository must have its interpreter at `.venv/bin/python`, as `uv sync` leaves it.

## What a run does

- When the home has no `plugins` folder, it downloads the adopted plugins from the JetBrains Marketplace at their pinned versions and unpacks them there. The folder appears only once every plugin is unpacked. A home that has one is never changed. To reinstall plugins, delete the home.
- It copies the files `git ls-files -z --cached --others --exclude-standard` lists into `project` in the home, and the planted mistakes from `src/python_inspection/proofs` into `inspect-python-planted-mistakes` inside that copy. A repository that has a folder of that name answers `UNKNOWN`. Neither the tool nor PyCharm writes into the repository. A repository's own `.idea/misc.xml` and `.idea/sqldialects.xml` are used when the repository tracks them. Otherwise the copy gets an interpreter name and the PostgreSQL SQL dialect.
- PyCharm inspects the copy in one launch. Each adopted plugin and built-in check must report its planted mistake at the exact file, line and inspection inside the planted folder, or the answer is `UNKNOWN` naming it. Nothing is remembered between runs: a plugin that is missing or disabled fails its proof on the next run, and on every run after.
- Every copied file must appear in PyCharm's log as analysed, and PyCharm's results index must list the inspections it ran. A finding at any other path makes the answer `UNKNOWN`. Findings in the planted folder, and in this catalog's own proofs, are never shown as the repository's.
- It prints what it is doing on stderr. PyCharm gets no input, and a launch that takes longer than 15 minutes answers `UNKNOWN`, so a run never needs a wrapper to stop it.

## How PyCharm behaves headless

Measured on PyCharm 2026.3, build PY-263.7307.206:

- It opens an untrusted project in safe mode and then ignores its interpreter, so type checks go silent while a run still looks clean. The tool writes trust for the project it inspects into the home before every launch.
- A fresh home never sets up an interpreter by itself. The tool registers the repository's interpreter, with its library roots, under the name each project's `misc.xml` names.
- Caches in the home's `system` folder can keep a project broken after its interpreter is fixed. The tool clears them before every run.
- A plugin can make the inspector analyse nothing and still exit successfully. The check that every file was analysed, and the proofs, are what reveal it.
- The standard-library proof calls a method `pathlib.Path` does not have. PyCharm can report that call only when it resolves the standard library. An unresolved import is reported on a different line and does not count.
- ShellCheck runs only when the `shellcheck` program is on the PATH. Without it, its proof fails.
- The GitHub workflow, compose, Markdown and `.env` checks also report files in a subfolder, such as `inspect-python-planted-mistakes/.github/workflows/proof.yml`.
- PyCharm's own command-line plugin installer cannot install a plugin that has no version for this build, so the tool unpacks Marketplace zips itself.
- The GitHub workflow check downloads an action's description from GitHub the first time. It has not been tested offline.
