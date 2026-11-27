import json
import shutil
import subprocess
import sys
import sysconfig
import venv
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from python_inspection import inspection
from python_inspection.inspection import (
    PLANTED_FOLDER,
    PROOF_SOURCES,
    PROOFS,
    Finding,
    InspectionUnknownError,
    read_findings,
    require_proofs_caught,
    unanalyzed_files,
)

MAPPER_GUARD = "io.github.mwassong.mapper-guard"
ONE_INSPECTION_INDEX = json.dumps({"groups": [{"name": "Python", "inspections": [{"shortName": "PyTypeChecker"}]}]})
FAKE_INSPECTOR = """#!{python}
import json, os, pathlib, subprocess, sys, time
project, output = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[3])
settings = dict(line.split("=", 1) for line in pathlib.Path(os.environ["PYCHARM_PROPERTIES"]).read_text().splitlines())
disabled_list = pathlib.Path(settings["idea.config.path"]) / "disabled_plugins.txt"
disabled = disabled_list.read_text().split() if disabled_list.exists() else []
loaded = {{plugin.name for plugin in pathlib.Path(settings["idea.plugins.path"]).iterdir()}} - set(disabled)
with pathlib.Path({calls!r}).open("a") as calls:
    calls.write(project.name + "\\n")
time.sleep({seconds})
if (project / "verify_environment.py").exists():
    subprocess.run([os.environ["PYCHARM_PYTHON_PATH"], "-I", "-B", project / "verify_environment.py"], check=True)
files = [file.relative_to(project).as_posix() for file in project.rglob("*")
         if file.is_file() and ".venv" not in file.parts and ".idea" not in file.parts and file.suffix != ".iml"]
print("".join(f"Analyzing code in …/{{file}}\\n" for file in files))
problems = [
    dict(file=path if path.startswith("/") else "file://$PROJECT_DIR$/" + path, line=line,
         problem_class=dict(id=check), description=check)
    for path, line, check, plugin in json.loads(pathlib.Path({reports!r}).read_text())
    if (path.startswith("/") or (project / path).is_file()) and (plugin is None or plugin in loaded)
]
(output / ".descriptions.json").write_text({index!r})
(output / "Reported.json").write_text(json.dumps(dict(problems=problems)))
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
    return [Finding(f"{PLANTED_FOLDER}/{file}", line, check, "caught") for file, line, check in PROOFS.values()]


def planted_reports() -> list[tuple[str, int, str, str | None]]:
    return [
        (f"{PLANTED_FOLDER}/{file}", line, check, MAPPER_GUARD if check == "SqlaReference" else None)
        for file, line, check in PROOFS.values()
    ]


def set_reports(home: Path, reports: list[tuple[str, int, str, str | None]]) -> None:
    (home / "reports.json").write_text(json.dumps(reports))


def write_build(app: Path, build: str) -> None:
    metadata = app / "Contents" / "Resources" / "product-info.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps({"productCode": "PY", "buildNumber": build}))


def install_fake_pycharm(home: Path, monkeypatch: pytest.MonkeyPatch, seconds: int = 0, *, pinned: bool = False) -> Path:
    inspector_home = home / "inspector-home"
    if pinned:
        app = inspector_home / "ides" / inspection.PYCHARM_BUILD / "PyCharm.app"
        write_build(app, inspection.PYCHARM_BUILD)
        monkeypatch.delenv("INSPECT_PYTHON_PYCHARM", raising=False)
    else:
        app = home / "PyCharm.app"
        monkeypatch.setenv("INSPECT_PYTHON_PYCHARM", str(app))
    pycharm, calls = app / "Contents", home / "inspector-calls"
    (pycharm / "bin").mkdir(parents=True)
    script = FAKE_INSPECTOR.format(
        python=sys.executable, calls=str(calls), seconds=seconds, reports=str(home / "reports.json"), index=ONE_INSPECTION_INDEX
    )
    (pycharm / "bin" / "inspect.sh").write_text(script)
    (pycharm / "bin" / "inspect.sh").chmod(0o755)
    set_reports(home, planted_reports())
    (inspector_home / "plugins" / MAPPER_GUARD).mkdir(parents=True)
    paths = {
        "PYCHARM": app,
        "INSPECTOR": pycharm / "bin" / "inspect.sh",
        "INSPECTOR_HOME": inspector_home,
        "INSPECTOR_PLUGINS": inspector_home / "plugins",
        "INSPECTOR_OPTIONS": inspector_home / "config" / "options",
        "INSPECTOR_CACHES": inspector_home / "system",
        "INSPECTED_PROJECT": inspector_home / "project",
    }
    for name, path in paths.items():
        monkeypatch.setattr(inspection, name, path)
    return calls


def make_repository(path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    venv.EnvBuilder(symlinks=True).create(path / ".venv")
    (path / ".gitignore").write_text(".venv/\n")
    assert inspection.run_quietly(["git", "init", "-q"], path).returncode == 0
    return path


def tree(path: Path) -> dict[str, float]:
    return {file.relative_to(path).as_posix(): file.lstat().st_mtime for file in path.rglob("*") if ".git" not in file.parts}


def answer_unknown() -> str:
    errors = StringIO()
    with redirect_stderr(errors):
        exit_code = inspection.main()
    assert exit_code == 2
    assert any(line.startswith("UNKNOWN:") for line in errors.getvalue().splitlines())
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


def test_an_unignored_environment_is_not_source_but_a_tracked_environment_file_is_reported_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_fake_pycharm(tmp_path, monkeypatch)
    repo = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    (repo / ".gitignore").unlink()
    assert inspection.inspect_repository(repo) == []
    calls.unlink()
    (repo / ".venv" / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    assert inspection.run_quietly(["git", "add", "-f", ".venv/pyvenv.cfg"], repo).returncode == 0

    with pytest.raises(InspectionUnknownError, match=r"\.venv/pyvenv\.cfg"):
        inspection.inspect_repository(repo)
    assert not calls.exists()


def test_shared_module_settings_reach_the_ide_and_keep_their_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    module = "packages/store/store.iml"
    content = '<module type="PYTHON_MODULE" version="4" />'
    repo = make_repository(
        tmp_path / "repo",
        {
            module: content,
            ".idea/modules.xml": '<project><component name="ProjectModuleManager" /></project>',
            ".idea/inspectionProfiles/shared.xml": '<component name="InspectionProjectProfileManager" />',
            "app.py": "x = 1\n",
        },
    )
    assert (
        inspection.run_quietly(
            ["git", "add", "-f", module, ".idea/modules.xml", ".idea/inspectionProfiles/shared.xml"], repo
        ).returncode
        == 0
    )
    set_reports(tmp_path, [*planted_reports(), (module, 1, "ExampleInspection", None)])

    assert inspection.inspect_repository(repo) == [Finding(module, 1, "ExampleInspection", "ExampleInspection")]
    assert (inspection.INSPECTED_PROJECT / module).read_text() == content
    (repo / ".idea" / "data.xml").write_text("<application-data />")
    assert inspection.run_quietly(["git", "add", "-f", ".idea/data.xml"], repo).returncode == 0
    with pytest.raises(InspectionUnknownError, match=r"\.idea/data\.xml"):
        inspection.inspect_repository(repo)


def test_one_launch_inspects_the_repository_and_the_planted_mistakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})

    assert inspection.inspect_repository(repository) == []
    assert inspection.inspect_repository(repository) == []
    assert calls.read_text().split() == ["project", "project"]


def test_a_removed_plugin_answers_unknown_naming_its_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    (inspection.INSPECTOR_PLUGINS / MAPPER_GUARD).rmdir()

    with pytest.raises(InspectionUnknownError, match="Mapper Guard"):
        inspection.inspect_repository(repository)


def test_a_plugin_disabled_after_a_clean_run_answers_unknown_on_every_later_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    assert inspection.inspect_repository(repository) == []
    (inspection.INSPECTOR_HOME / "config").mkdir(exist_ok=True)
    (inspection.INSPECTOR_HOME / "config" / "disabled_plugins.txt").write_text(f"{MAPPER_GUARD}\n")

    for _ in range(2):
        with pytest.raises(InspectionUnknownError, match="Mapper Guard"):
            inspection.inspect_repository(repository)


def test_a_repository_finding_cannot_satisfy_a_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    look_alike = ("shellcheck.sh", 2, "ShellCheck", None)
    set_reports(tmp_path, [report for report in planted_reports() if report[2] != "ShellCheck"] + [look_alike])
    repository = make_repository(tmp_path / "repo", {"shellcheck.sh": "#!/bin/sh\necho $1\n"})

    with pytest.raises(InspectionUnknownError, match="ShellCheck"):
        inspection.inspect_repository(repository)


def test_a_repository_with_a_folder_named_like_the_planted_one_answers_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {f"{PLANTED_FOLDER}/shellcheck.sh": "#!/bin/sh\n"})

    with pytest.raises(InspectionUnknownError, match=PLANTED_FOLDER):
        inspection.inspect_repository(repository)


def test_a_report_at_a_path_the_tool_did_not_ask_about_answers_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    set_reports(tmp_path, [*planted_reports(), ("/elsewhere/app.py", 1, "Stray", None)])
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})

    with pytest.raises(InspectionUnknownError, match="did not ask about"):
        inspection.inspect_repository(repository)


@pytest.mark.parametrize("linked_venv", [False, True])
def test_the_inspector_uses_a_private_copy_of_the_installed_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked_venv: bool
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    receipt = tmp_path / "dependency-path"
    settings = '<project version="4"><component name="Black"><option name="enabled" value="true" /></component></project>'
    repository = make_repository(
        tmp_path / "repo",
        {
            ".idea/misc.xml": settings,
            "verify_environment.py": (
                "import subprocess, sys\n"
                "from pathlib import Path\n"
                "import catalog_fixture_dependency as dep\n"
                "subprocess.run([Path(sys.executable).with_name('fixture-command')], check=True)\n"
                "assert dep.answer == 42\n"
                "package = Path(dep.__file__)\n"
                "package.write_text('answer = 7\\n')\n"
                f"Path({str(receipt)!r}).write_text(str(package))\n"
            ),
        },
    )
    assert inspection.run_quietly(["git", "add", "--force", ".idea/misc.xml"], repository).returncode == 0
    env = repository / ".venv"
    if linked_venv:
        env = env.rename(tmp_path / "linked-env")
        (repository / ".venv").symlink_to(env, target_is_directory=True)
    packages = Path(sysconfig.get_path("purelib", vars={"base": str(env), "platbase": str(env)}))
    package = packages / "catalog_fixture_dependency.py"
    if linked_venv:
        package.symlink_to(repository / "editable_source.py")
    package.write_text("answer = 42\n")
    (packages / "load_dependency.pth").write_text("import catalog_fixture_dependency\n")
    command = env / "bin" / "fixture-command"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o555)
    data = packages / "fixture-data"
    data.mkdir()
    (data / "input").touch(mode=0o444)
    data.chmod(0o555)
    before = tree(repository)
    environment_before = tree(env)
    inspection.INSPECTED_PROJECT.symlink_to(repository, target_is_directory=True)

    for _ in range(2):
        inspection.inspect_repository(repository)

    inspected = Path(receipt.read_text())
    assert inspected.is_relative_to(inspection.INSPECTOR_HOME)
    assert inspected.read_text() == "answer = 7\n"
    assert package.read_text() == "answer = 42\n"
    assert data.stat().st_mode & 0o200 == 0
    assert (data / "input").stat().st_mode & 0o200 == 0
    assert tree(env) == environment_before
    assert tree(repository) == before
    assert (inspection.INSPECTED_PROJECT / ".idea" / "misc.xml").read_text() == settings


@pytest.mark.parametrize("disposable", ["project", "system"])
def test_a_linked_source_environment_inside_the_inspection_home_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disposable: str
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    env = repository / ".venv"
    parent = inspection.INSPECTOR_HOME / disposable
    parent.mkdir()
    stored = env.rename(parent / "source-venv")
    env.symlink_to(stored, target_is_directory=True)
    before = tree(stored)

    with pytest.raises(InspectionUnknownError):
        inspection.inspect_repository(repository)

    assert tree(stored) == before


def test_an_inspector_that_never_finishes_answers_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, seconds=30)
    monkeypatch.setattr(inspection, "INSPECTOR_TIMEOUT_SECONDS", 1)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})

    with pytest.raises(InspectionUnknownError, match="did not finish"):
        inspection.inspect_repository(repository)


def test_a_repository_inside_the_tool_home_is_refused_and_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(inspection.INSPECTOR_HOME / "project", {"uncommitted.py": "x = 1\n"})
    monkeypatch.setattr(inspection, "INSPECTED_PROJECT", repository)

    with pytest.raises(InspectionUnknownError, match="inside one another"):
        inspection.inspect_repository(repository)
    assert (repository / "uncommitted.py").read_text() == "x = 1\n"


def test_a_tool_home_inside_the_repository_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    monkeypatch.setattr(inspection, "INSPECTOR_HOME", repository / "home")

    with pytest.raises(InspectionUnknownError, match="inside one another"):
        inspection.inspect_repository(repository)
    assert not (repository / "home").exists()


def test_a_report_that_is_not_json_answers_unknown_naming_it(tmp_path: Path) -> None:
    write_pycharm_results(tmp_path, [])
    (tmp_path / "Broken.json").write_text("{ not json")

    with pytest.raises(InspectionUnknownError, match=r"Broken\.json"):
        read_findings(tmp_path)


def test_module_annotations_prove_only_unambiguous_files(tmp_path: Path) -> None:
    files = ["seen.py", "name [literal]", "both", "both [module]", "skipped.py"]
    for name in files:
        (tmp_path / name).touch()
    log = "\n".join(f"Analyzing code in …/{name}" for name in ("seen.py [nested [module]]", "name [literal]", "both [module]"))

    assert unanalyzed_files(files, log, tmp_path) == ["both", "both [module]", "skipped.py"]


def test_every_proof_names_a_planted_file_and_line() -> None:
    for file, line, _ in PROOFS.values():
        assert len((PROOF_SOURCES / file).read_text().splitlines()) >= line


def test_every_proof_caught_as_pycharm_reports_it_passes(tmp_path: Path) -> None:
    problems = [pycharm_problem(f"{PLANTED_FOLDER}/{file}", line, check) for file, line, check in PROOFS.values()]

    require_proofs_caught(read_findings(write_pycharm_results(tmp_path, problems)))


def test_an_unresolved_standard_library_import_does_not_pass_as_the_canary() -> None:
    canary = f"{PLANTED_FOLDER}/canary.py"
    stdlib_missing = Finding(canary, 1, "PyUnresolvedReferencesInspection", "Unresolved reference 'pathlib'")
    findings = [finding for finding in every_proof_caught() if finding.file != canary] + [stdlib_missing]

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
    install_fake_pycharm(tmp_path, monkeypatch)
    monkeypatch.setattr(inspection, "INSPECTOR", tmp_path / "inspect.sh")
    monkeypatch.chdir(make_repository(tmp_path / "repo", {"app.py": "x = 1\n"}))

    assert "INSPECT_PYTHON_PYCHARM" in answer_unknown()


def test_a_repository_without_an_interpreter_answers_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    (repository / ".venv" / "bin" / "python").unlink()
    monkeypatch.chdir(repository)

    answer_unknown()


def test_warmup_requires_the_project_to_select_the_registered_uv_sdk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspection, "INSPECTOR_OPTIONS", tmp_path)
    monkeypatch.setattr(inspection, "run_quietly", Mock(return_value=subprocess.CompletedProcess([], 0)))
    environment = tmp_path / ".venv"
    (tmp_path / "jdk.table.xml").write_text(
        f'<application><component name="ProjectJdkTable"><jdk><name value="{environment}"/><type value="Python SDK"/>'
        '<additional IS_UV="true" UV_VENV_PATH="$PROJECT_DIR$/.venv"/></jdk></component></application>'
    )
    settings = tmp_path / ".idea/misc.xml"
    settings.parent.mkdir()
    for selection in (
        'project-jdk-type="Python SDK"',
        'project-jdk-name="$PROJECT_DIR$/.venv"',
        'project-jdk-type="JavaSDK" project-jdk-name="$PROJECT_DIR$/.venv"',
        'project-jdk-type="Python SDK" project-jdk-name="another interpreter"',
    ):
        settings.write_text(f'<project><component name="ProjectRootManager" {selection}/></project>')
        with pytest.raises(InspectionUnknownError):
            inspection.warm_uv_project(tmp_path, {}, 0)

    settings.write_text(
        '<project><component name="ProjectRootManager" project-jdk-type="Python SDK" '
        'project-jdk-name="$PROJECT_DIR$/.venv"/></project>'
    )
    inspection.warm_uv_project(tmp_path, {}, 0)


def test_caches_that_cannot_be_cleared_answer_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    caches = tmp_path / "system"
    (caches / "index").mkdir(parents=True)
    (caches / "index" / "stale").touch()
    monkeypatch.setattr(inspection, "INSPECTOR_CACHES", caches)
    monkeypatch.setattr(inspection, "INSPECTOR_OPTIONS", tmp_path / "options")
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


def test_a_checked_in_sql_dialect_is_kept(tmp_path: Path) -> None:
    dialects = tmp_path / ".idea" / "sqldialects.xml"
    dialects.parent.mkdir()
    dialects.write_text("<project />")

    inspection.set_sql_dialect_if_unset(tmp_path)

    assert dialects.read_text() == "<project />"


def test_a_different_build_in_the_pinned_cache_cannot_inspect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, pinned=True)
    write_build(inspection.PYCHARM, "0.0")

    with pytest.raises(InspectionUnknownError, match="build"):
        inspection.inspect_repository(make_repository(tmp_path / "repo", {"app.py": "x = 1\n"}))


def copy_build(ides: Path, build: str) -> Path:
    app = ides / build / "PyCharm.app"
    shutil.copytree(inspection.PYCHARM, app)
    write_build(app, build)
    return app


def test_an_update_keeps_the_previous_build_until_the_new_one_catches_the_proofs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, pinned=True)
    previous = copy_build(inspection.INSPECTOR_HOME / "ides", "1.0")
    repository = make_repository(tmp_path / "repo", {"app.py": "x = 1\n"})
    set_reports(tmp_path, [report for report in planted_reports() if report[2] != "ShellCheck"])

    with pytest.raises(InspectionUnknownError, match="ShellCheck"):
        inspection.inspect_repository(repository)
    assert previous.is_dir()
    assert inspection.PYCHARM.is_dir()

    set_reports(tmp_path, [*planted_reports(), ("app.py", 1, "PyTypeChecker", None)])
    for _ in range(2):
        assert inspection.inspect_repository(repository) == [Finding("app.py", 1, "PyTypeChecker", "PyTypeChecker")]
        assert not previous.exists()
        assert inspection.PYCHARM.is_dir()


def test_retiring_cached_builds_preserves_unrelated_files_and_linked_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, pinned=True)
    ides = inspection.INSPECTOR_HOME / "ides"
    previous = copy_build(ides, "1.0")
    sibling = previous.parent / "keep.txt"
    sibling.touch()
    mismatch = copy_build(ides, "1.1")
    write_build(mismatch, "20.0")
    outside = copy_build(tmp_path / "elsewhere", "1.2")
    (ides / "1.2").symlink_to(outside.parent, target_is_directory=True)
    foreign = copy_build(tmp_path / "elsewhere", "1.3")
    (ides / "1.3").mkdir()
    (ides / "1.3" / "PyCharm.app").symlink_to(foreign, target_is_directory=True)

    inspection.inspect_repository(make_repository(tmp_path / "repo", {"app.py": "x = 1\n"}))

    assert not previous.exists()
    assert sibling.is_file()
    assert mismatch.is_dir()
    assert (ides / "1.2" / "PyCharm.app").is_dir()
    assert (ides / "1.3" / "PyCharm.app").is_dir()


def test_an_explicit_application_leaves_cached_builds_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch)
    previous = copy_build(inspection.INSPECTOR_HOME / "ides", "1.0")

    inspection.inspect_repository(make_repository(tmp_path / "repo", {"app.py": "x = 1\n"}))

    assert previous.is_dir()


def test_a_linked_ide_cache_does_not_retire_an_external_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pycharm(tmp_path, monkeypatch, pinned=True)
    ides = inspection.INSPECTOR_HOME / "ides"
    external = ides.rename(tmp_path / "elsewhere")
    ides.symlink_to(external, target_is_directory=True)

    previous = copy_build(external, "1.0")
    inspection.inspect_repository(make_repository(tmp_path / "repo", {"app.py": "x = 1\n"}))

    assert previous.is_dir()
