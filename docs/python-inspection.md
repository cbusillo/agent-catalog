# Python inspection

`inspect-python` runs PyCharm's command-line inspector on the repository in the current folder. It prints `clean`, the findings, or `UNKNOWN` with the reason. Exit codes: 0 clean, 1 findings, 2 unknown.

Set `CATALOG_COMMIT` to the full catalog commit qualified for the repository, then run:

```sh
uvx --from "git+https://github.com/cbusillo/agent-catalog@${CATALOG_COMMIT:?set the catalog commit}" inspect-python
```

## Settings

- On a Mac with `jq` available, the first run downloads the pinned build from JetBrains, verifies its SHA-256 and installs it under `ides/<build>/PyCharm.app` in the inspection home. An update keeps the previous IDE until the new one inspects the project and catches the planted mistakes. Then the inspector removes the other managed builds, even when it found a problem in the project. A failed proof keeps the previous IDE for retry or rollback. Use separate homes if you regularly switch between two pins.
- Set `INSPECT_PYTHON_PYCHARM` to test a specific application. This leaves the managed IDEs in place.
- `INSPECT_PYTHON_HOME`: the folder PyCharm uses as its home while inspecting. Default `~/.cache/inspect-python`. It must not be inside the repository or contain it; the tool refuses with `UNKNOWN`.

The repository must have its interpreter at `.venv/bin/python`, as `uv sync` leaves it. The inspection home needs space for a copy of this environment.

Renovate checks JetBrains' stable builds weekly. On a pull request, a GitHub-hosted Mac inspects a project with a declared dependency, then removes the declaration and checks that the same import produces a dependency warning while the package is still installed.

## What a run does

- When the home has no `plugins` folder, it downloads the adopted plugins from the JetBrains Marketplace at their pinned versions and unpacks them there. The folder appears only once every plugin is unpacked. To reinstall the plugin files, remove only `plugins` from the inspection home.
- It copies tracked and unignored project files into `project` in the home, alongside the planted mistakes in `inspect-python-planted-mistakes`. A repository with a folder of that name answers `UNKNOWN`. The tool copies the existing virtual environment separately. If Git tracks a file inside `.venv/`, the command names the conflict and returns `UNKNOWN` before launching PyCharm. For a locked uv project, PyCharm discovers the private environment through its native uv integration. For a plain Python project the tool passes the private interpreter through `PYCHARM_PYTHON_PATH`. The source checkout and environment stay untouched.
- If a package is installed in editable mode from the repository, uv reinstalls it offline from its private copy without changing dependencies. A build that requires missing Git history or an uncached backend returns `UNKNOWN` with uv’s error. PyCharm imports a uv project from its own metadata. A plain directory without module settings gets a private Python module so its interpreter is ready on first inspection. The inspection scope excludes the private `.venv` from source analysis.
- For a locked uv project, PyCharm's native warmup opens the private copy first. The inspector checks that PyCharm registered its private uv environment before starting analysis. Otherwise a source file can be checked before its interpreter is ready, or a generic Python SDK can miss an undeclared dependency.
- PyCharm inspects the source and planted mistakes together in one launch. Each adopted plugin and built-in check must report its planted mistake at the exact file, line and inspection inside the planted folder, or the answer is `UNKNOWN` naming it. A plugin that is missing or disabled fails its proof on the next run.
- The tool copies and lists shared module descriptors (`.iml`, including in nested modules), JetBrains component XML under `.idea`, and the store's `.gitignore` as project settings. PyCharm uses `modules.xml` to select the modules. Any findings it emits on supplied settings are included. A copy without SQL dialect settings gets PostgreSQL.
- Every other Git-listed project file and every planted proof file must appear in PyCharm's analysis log, and its results index must list the inspections it ran. A missed source file or a finding outside the supplied inputs makes the answer `UNKNOWN`. Findings in the planted folder and the catalog's own proofs are omitted from repository findings.
- It prints what it is doing on stderr. PyCharm gets no input, and a launch that takes longer than 15 minutes answers `UNKNOWN`, so a run never needs a wrapper to stop it.

## How PyCharm behaves headless

The original headless measurements used PyCharm build PY-263.7307.206. The tracked-module and dependency checks also ran on the pinned 2026.3.1 release candidate.

- It opens an untrusted project in safe mode and then ignores its interpreter, so type checks go silent while a run still looks clean. The tool writes trust for the project it inspects into the home before every launch.
- Cached interpreter records and indexes can survive a change of project in the inspection home. Each run clears them before opening the new private copy.
- A plugin can make the inspector analyse nothing and still exit successfully. The check that every file was analysed, and the proofs, are what reveal it.
- The standard-library proof calls a method `pathlib.Path` does not have. PyCharm can report that call only when it resolves the standard library. An unresolved import is reported on a different line and does not count.
- ShellCheck runs only when the `shellcheck` program is on the PATH. Without it, its proof fails.
- The GitHub workflow, compose, Markdown and `.env` checks also report files in a subfolder, such as `inspect-python-planted-mistakes/.github/workflows/proof.yml`.
- PyCharm's own command-line plugin installer cannot install a plugin that has no version for this build, so the tool unpacks Marketplace zips itself.
- The GitHub workflow check downloads an action's description from GitHub the first time. It has not been tested offline.

## Known and not fixed

- **The proofs do not prove every check finished every file.** The planted mistakes prove each check is installed, switched on and fires in this launch. An inspection that fails on one real file gives no finding for it, and the run can still answer `clean`. Comes back if a clean answer is ever traced to that.
- **A separately installed copy shows this catalog's planted files as findings.** Findings in this checkout's `src/python_inspection/proofs` are dropped only when the running package is that same checkout. Inspecting the catalog through another installed copy reports them. Comes back when the catalog is inspected that way for real work.
- **A repository can weaken the standard-library proof.** A repository file named like a standard-library module could resolve the canary's import in its place. This is inference, not seen. Comes back if a repository with such a file answers `clean` while the canary passes.
- **Duplicate analysis can report repository code that matches planted code.** The planted duplicate files sit in the same project as the repository, so a repository file that matches them could be reported as a duplicate. This is inference, not seen. Comes back if such a finding appears.
- **A results index holding a null group gives a traceback.** PyCharm has not been seen writing one, so the run fails loudly rather than answering `clean`. Comes back if PyCharm is ever seen writing one.
