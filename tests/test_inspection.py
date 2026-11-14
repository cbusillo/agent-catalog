import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from python_inspection import inspection
from python_inspection.inspection import (
    PROOF_SOURCES,
    PROOFS,
    Finding,
    InspectionUnknownError,
    read_findings,
    require_proofs_caught,
    unanalyzed_files,
)

ONE_INSPECTION_INDEX = json.dumps({"groups": [{"name": "Python", "inspections": [{"shortName": "PyTypeChecker"}]}]})
FAKE_INSPECTOR = """#!{python}
import json, pathlib, sys, time
project, output = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[3])
with pathlib.Path({calls!r}).open("a") as calls:
    calls.write(project.name + "\\n")
time.sleep({seconds})
files = [file.relative_to(project).as_posix() for file in project.rglob("*") if file.is_file() and ".idea" not in file.parts]
print("".join(f"Analyzing code in …/{{file}}\\n" for file in files))
proofs = {proofs!r} if (project / "canary.py").exists() else []
problems = [dict(file="file://$PROJECT_DIR$/" + file, line=line, problem_class=dict(id=check), description="planted")
            for file, line, check in proofs]
(output / ".descriptions.json").write_text({index!r})
(output / "Planted.json").write_text(json.dumps(dict(problems=problems)))
"""


def pycharm_problem(file: str, line: int, inspection_id: str) -> dict[str, Any]:
    return {
        "file": f"file://$PROJECT_DIR$/{file}",
        "line": line,
        "problem_class": {"name": "", "id": inspection_id, "severity": "WARNING"},
        "description": "a problem",
    }


def write_pycharm_results(output: Path, problems: list[dict[str, Any]]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    (output / ".descriptions.json").write_text(ONE_INSPECTION_INDEX)
    for index, problem in enumerate(problems):
        (output / f"{problem['problem_class']['id']}-{index}.json").write_text(json.dumps({"problems": [problem]}))
    return output


def every_proof_caught() -> list[Finding]:
    return [Finding(file, line, inspection_id, "caught") for file, line, inspection_id in PROOFS.values()]


def install_fake_pycharm(home: Path, monkeypatch: pytest.MonkeyPatch, seconds: int = 0) -> Path:
    pycharm, calls = home / "PyCharm.app" / "Contents", home / "inspector-calls"
    (pycharm / "plugins" / "python-ce" / "helpers" / "typeshed" / "stdlib").mkdir(parents=True)
    (pycharm / "Resources").mkdir()
    (pycharm / "Resources" / "product-info.json").write_text("{}")
    (pycharm / "bin").mkdir()
    script = FAKE_INSPECTOR.format(
        python=sys.executable,
        calls=str(calls),
        seconds=seconds,
        proofs=list(PROOFS.values()),
        index=ONE_INSPECTION_INDEX,
    )
    (pycharm / "bin" / "inspect.sh").write_text(script)
    (pycharm / "bin" / "inspect.sh").chmod(0o755)
    inspector_home = home / "inspector-home"
    (inspector_home / "plugins" / "a-plugin").mkdir(parents=True)
    paths = {
        "INSPECTOR": pycharm / "bin" / "inspect.sh",
        "TYPESHED_STDLIB": pycharm / "plugins" / "python-ce" / "helpers" / "typeshed" / "stdlib",
        "PRODUCT_INFO": pycharm / "Resources" / "product-info.json",
        "INSPECTOR_HOME": inspector_home,
        "INSPECTOR_PLUGINS": inspector_home / "plugins",
        "INSPECTOR_OPTIONS": inspector_home / "config" / "options",
        "INSPECTOR_CACHES": inspector_home / "system",
        "PROOF_PROJECT": inspector_home / "proofs",
        "REPOSITORY_PROJECT": inspector_home / "repository",
        "SETUP_RECORD": inspector_home / "proven.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(inspection, name, path)
    return calls


def make_repository(path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    (path / ".venv" / "bin").mkdir(parents=True)
    (path / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (path / ".gitignore").write_text(".venv/\n")
    assert inspection.run_quietly(["git", "init", "-q"], path).returncode == 0
    return path


def tree(path: Path) -> dict[str, float]:
    return {file.relative_to(path).as_posix(): file.lstat().st_mtime for file in path.rglob("*") if ".git" not in file.parts}


def shellcheck_found(_program: str) -> str:
    return "/bin/shellcheck"


def shellcheck_missing(_program: str) -> None:
    return None


def answer_unknown() -> str:
    errors = StringIO()
    with redirect_stderr(errors):
        exit_code = inspection.main()
    assert exit_code == 2
    assert errors.getvalue().startswith("UNKNOWN:")
    return errors.getvalue()


def test_results_without_the_index_are_unknown_not_clean(tmp_path: Path) -> None:
    with pytest.raises(InspectionUnknownError):
        read_findings(tmp_path)


def test_a_results_index_listing_no_inspections_is_unknown_not_clean(tmp_path: Path) -> None:
    (tmp_path / ".descriptions.json").write_text("{}")

    with pytest.raises(InspectionUnknownError, match="lists no inspections"):
        read_findings(tmp_path)


def test_a_file_name_git_quotes_is_still_checked_for_coverage(tmp_path: Path) -> None:
    repository = make_repository(tmp_path, {"src/café.py": "x = 1\n"})

    assert "src/café.py" in inspection.repository_files(repository)


def test_the_proofs_run_once_at_setup_not_on_every_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})

    assert inspection.inspect_repository(repository) == []
    assert inspection.inspect_repository(repository) == []
    assert calls.read_text().split() == ["proofs", "repository", "repository"]


def test_shellcheck_leaving_the_path_proves_the_checks_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    monkeypatch.setattr(inspection.shutil, "which", shellcheck_found)
    inspection.inspect_repository(repository)
    monkeypatch.setattr(inspection.shutil, "which", shellcheck_missing)

    inspection.inspect_repository(repository)

    assert calls.read_text().split() == ["proofs", "repository", "proofs", "repository"]


def test_a_run_writes_nothing_into_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n", "queries.py": "SQL = 'select 1'\n"})
    before = tree(repository)

    inspection.inspect_repository(repository)

    assert tree(repository) == before


def test_an_inspector_that_never_finishes_answers_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, seconds=30)
    monkeypatch.setattr(inspection, "INSPECTOR_TIMEOUT_SECONDS", 1)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})

    with pytest.raises(InspectionUnknownError, match="did not finish"):
        inspection.inspect_repository(repository)


def test_a_file_the_inspector_skipped_is_reported() -> None:
    inspector_log = "Analyzing code in …/src/seen.py\n"

    assert unanalyzed_files(["src/seen.py", "deploy/compose.yaml"], inspector_log) == ["deploy/compose.yaml"]


def test_every_proof_names_a_planted_file_and_line() -> None:
    for file, line, _ in PROOFS.values():
        assert len((PROOF_SOURCES / file).read_text().splitlines()) >= line


def test_every_proof_caught_as_pycharm_reports_it_passes(tmp_path: Path) -> None:
    problems = [pycharm_problem(file, line, inspection_id) for file, line, inspection_id in PROOFS.values()]

    require_proofs_caught(read_findings(write_pycharm_results(tmp_path, problems)))


def test_a_missing_plugin_answers_unknown_naming_its_proof() -> None:
    without_mapper_guard = [finding for finding in every_proof_caught() if finding.inspection != "SqlaReference"]

    with pytest.raises(InspectionUnknownError, match="Mapper Guard"):
        require_proofs_caught(without_mapper_guard)


def test_an_unresolved_standard_library_import_does_not_pass_as_the_canary() -> None:
    stdlib_missing = Finding("canary.py", 1, "PyUnresolvedReferencesInspection", "Unresolved reference 'pathlib'")
    findings = [finding for finding in every_proof_caught() if finding.file != "canary.py"] + [stdlib_missing]

    with pytest.raises(InspectionUnknownError, match="standard library"):
        require_proofs_caught(findings)


def test_a_finding_reaches_the_output_and_fails_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    mistake = Finding("src/app/mistake.py", 3, "PyTypeCheckerInspection", "Expected type 'int'")

    def inspect_with_one_mistake(_repository: Path) -> list[Finding]:
        return [mistake]

    monkeypatch.setattr(inspection, "inspect_repository", inspect_with_one_mistake)

    output = StringIO()
    with redirect_stdout(output):
        exit_code = inspection.main()

    assert exit_code == 1
    assert "src/app/mistake.py:3: Expected type 'int'" in output.getvalue()


def test_missing_pycharm_answers_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspection, "INSPECTOR", tmp_path / "inspect.sh")

    assert "INSPECT_PYTHON_PYCHARM" in answer_unknown()


def test_a_repository_without_an_interpreter_answers_unknown(tmp_path: Path) -> None:
    with pytest.raises(InspectionUnknownError, match="uv sync"):
        inspection.read_interpreter(tmp_path)


def test_caches_that_cannot_be_cleared_answer_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    caches = tmp_path / "system"
    (caches / "index").mkdir(parents=True)
    (caches / "index" / "stale").touch()
    monkeypatch.setattr(inspection, "INSPECTOR_CACHES", caches)
    (caches / "index").chmod(0o500)
    try:
        with pytest.raises(InspectionUnknownError):
            inspection.forget_earlier_inspections()
    finally:
        (caches / "index").chmod(0o700)


def test_a_home_with_plugins_is_not_reinstalled_or_downloaded_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(inspection, "INSPECTOR_PLUGINS", plugins)
    monkeypatch.setattr(inspection, "MARKETPLACE_DOWNLOAD", "http://127.0.0.1:9/unreachable")

    inspection.install_plugins_into_new_home()

    assert list(plugins.iterdir()) == []


def test_a_failed_plugin_download_leaves_no_plugins_folder_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspection, "INSPECTOR_HOME", tmp_path)
    monkeypatch.setattr(inspection, "INSPECTOR_PLUGINS", tmp_path / "plugins")
    monkeypatch.setattr(inspection, "MARKETPLACE_DOWNLOAD", "http://127.0.0.1:9/unreachable")

    with pytest.raises(InspectionUnknownError, match="Could not install"):
        inspection.install_plugins_into_new_home()

    assert not (tmp_path / "plugins").exists()


def test_planted_proofs_in_this_checkout_stay_out_of_its_own_findings() -> None:
    assert inspection.is_planted(PROOF_SOURCES / "canary.py")
    assert not inspection.is_planted(PROOF_SOURCES.parent / "inspection.py")


def test_existing_project_settings_keep_their_interpreter_and_other_settings(tmp_path: Path) -> None:
    settings = tmp_path / ".idea" / "misc.xml"
    settings.parent.mkdir()
    original = (
        '<project version="4"><component name="Black"><option name="enabled" value="true" /></component>'
        '<component name="ProjectRootManager" version="2" project-jdk-name="uv (app)" project-jdk-type="Python SDK" />'
        "</project>"
    )
    settings.write_text(original)

    assert inspection.project_interpreter_name(tmp_path) == "uv (app)"
    assert settings.read_text() == original


def test_project_settings_without_an_interpreter_gain_one_and_keep_the_rest(tmp_path: Path) -> None:
    settings = tmp_path / ".idea" / "misc.xml"
    settings.parent.mkdir()
    settings.write_text('<project version="4"><component name="Black"><option name="enabled" value="true" /></component></project>')

    name = inspection.project_interpreter_name(tmp_path)

    assert inspection.project_interpreter_name(tmp_path) == name
    assert 'name="Black"' in settings.read_text()


def test_a_checked_in_sql_dialect_is_kept(tmp_path: Path) -> None:
    dialects = tmp_path / ".idea" / "sqldialects.xml"
    dialects.parent.mkdir()
    dialects.write_text("<project />")

    inspection.set_sql_dialect_if_unset(tmp_path)

    assert dialects.read_text() == "<project />"
