import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

PACKAGE = Path(__file__).resolve().parent
PYCHARM = Path(os.environ.get("INSPECT_PYTHON_PYCHARM", Path.home() / "Applications" / "PyCharm.app"))
INSPECTOR_HOME = Path(os.environ.get("INSPECT_PYTHON_HOME", Path.home() / ".cache" / "inspect-python"))
INSPECTOR = PYCHARM / "Contents" / "bin" / "inspect.sh"
TYPESHED_STDLIB = PYCHARM / "Contents" / "plugins" / "python-ce" / "helpers" / "typeshed" / "stdlib"
INSPECTOR_PLUGINS = INSPECTOR_HOME / "plugins"
INSPECTOR_OPTIONS = INSPECTOR_HOME / "config" / "options"
INSPECTOR_CACHES = INSPECTOR_HOME / "system"
PROOF_PROJECT = INSPECTOR_HOME / "proofs"
PROFILE_TEMPLATE = PACKAGE / "profile.xml"
ANALYZED_LINE_PREFIX = "Analyzing code in …/"
RESULTS_INDEX = ".descriptions.json"
DEFAULT_INTERPRETER_NAME = "inspect-python"
MARKETPLACE_DOWNLOAD = "https://plugins.jetbrains.com/plugin/download"
PLUGINS = {
    "io.github.mwassong.mapper-guard": "0.1.7",
    "com.github.chbndrhnns.betterpy": "2026.11.2+263",
    "ru.meanmail.plugin.pyannotations": "2026.1",
    "org.tonybaloney.security.pycharm-security": "1.29.0",
    "net.sjrx.intellij.plugins.systemdunitfiles": "242.261111.978",
    "dev.protsenko.security-linter": "2.0.21",
}
INTERPRETER_FACTS = (
    "import json, sys, sysconfig; print(json.dumps({'version': f'{sys.version_info[0]}.{sys.version_info[1]}', "
    "'roots': [sysconfig.get_path('stdlib'), sysconfig.get_path('stdlib') + '/lib-dynload', sysconfig.get_path('purelib')]}))"
)


class InspectionUnknownError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    inspection: str
    description: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.description} [{self.inspection}]"


@dataclass(frozen=True)
class Interpreter:
    executable: Path
    version: str
    roots: list[Path]


PROOFS = {
    "the standard library resolves": ("canary.py", 5, "PyUnresolvedReferencesInspection"),
    "Mapper Guard": ("mapper_guard.py", 12, "SqlaReference"),
    "BetterPy": ("test_betterpy.py", 1, "PytestFixtureUninjectedReferenceInspection"),
    "pyannotations": ("pyannotations.py", 1, "PipeSyntaxWithObjectInspection"),
    "pycharm-security": ("pycharm_security.py", 2, "TimingAttackInspection"),
    "systemd unit files": ("systemd.service", 6, "InvalidValue"),
    "security-linter": ("Dockerfile", 2, "DockerfileRun"),
    "duplicate code": ("duplicate_a.py", 1, "DuplicatedCode"),
    "SQL in Python": ("sql.py", 3, "Annotator"),
    "compose files": ("compose.yaml", 4, "ComposeUnknownKeys"),
    "GitHub workflows": (".github/workflows/proof.yml", 8, "IllegalJobDependency"),
    "Markdown": ("README.md", 3, "MarkdownUnresolvedFileReference"),
    ".env files": (".env.example", 2, "DotEnvDuplicateKeyInspection"),
    "ShellCheck": ("shellcheck.sh", 2, "ShellCheck"),
}


def read_findings(output: Path) -> list[Finding]:
    if not (output / RESULTS_INDEX).is_file():
        raise InspectionUnknownError(f"PyCharm wrote no results index to {output}, so the inspection did not finish.")
    findings: list[Finding] = []
    for report in sorted(output.glob("*.json")):
        if report.name == RESULTS_INDEX or report.name.endswith("_aggregate.json"):
            continue
        findings.extend(
            Finding(
                file=problem["file"].removeprefix("file://$PROJECT_DIR$/"),
                line=problem.get("line", 0),
                inspection=problem["problem_class"]["id"],
                description=problem["description"],
            )
            for problem in json.loads(report.read_text())["problems"]
        )
    return findings


def unanalyzed_files(expected: list[str], inspector_log: str) -> list[str]:
    analyzed = {
        line.removeprefix(ANALYZED_LINE_PREFIX) for line in inspector_log.splitlines() if line.startswith(ANALYZED_LINE_PREFIX)
    }
    return [file for file in expected if file not in analyzed]


def run_quietly(command: list[str | Path], cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ | (extra_env or {})
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)  # noqa: S603 commands are this tool's own


def repository_files(repository: Path) -> list[str]:
    result = run_quietly(["git", "ls-files", "--cached", "--others", "--exclude-standard"], repository)
    if result.returncode != 0:
        raise InspectionUnknownError(f"Could not list the files of {repository} with git: {result.stderr.strip()}")
    return sorted(file for file in result.stdout.splitlines() if (repository / file).is_file())


def proof_project_files() -> list[str]:
    return sorted(
        file.relative_to(PROOF_PROJECT).as_posix()
        for file in PROOF_PROJECT.rglob("*")
        if file.is_file() and ".idea" not in file.relative_to(PROOF_PROJECT).parts
    )


def require_inspector_installed() -> None:
    for required in (INSPECTOR, TYPESHED_STDLIB):
        if not required.exists():
            raise InspectionUnknownError(
                f"PyCharm 2026.3 is not where this tool looks for it: {required} is missing. "
                "Set INSPECT_PYTHON_PYCHARM to the PyCharm application."
            )


def read_interpreter(repository: Path) -> Interpreter:
    interpreter = repository / ".venv" / "bin" / "python"
    if not interpreter.exists():
        raise InspectionUnknownError(f"{repository} has no interpreter at {interpreter}. Run `uv sync` there, then inspect again.")
    result = run_quietly([interpreter, "-c", INTERPRETER_FACTS], repository)
    if result.returncode != 0:
        raise InspectionUnknownError(f"Could not ask {interpreter} for its library folders: {result.stderr.strip()}")
    facts = json.loads(result.stdout)
    return Interpreter(interpreter, facts["version"], [Path(root) for root in facts["roots"]])


@contextmanager
def exclusive_inspector_home() -> Generator[None]:
    try:
        INSPECTOR_HOME.mkdir(parents=True, exist_ok=True)
        lock = (INSPECTOR_HOME / "inspection.lock").open("w")
    except OSError as error:
        raise InspectionUnknownError(f"Could not open PyCharm's inspection home {INSPECTOR_HOME}: {error}") from error
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise InspectionUnknownError(
                f"Another inspection is using {INSPECTOR_HOME}. Wait for it to finish, then run again."
            ) from error
        yield


def install_plugins_into_new_home() -> None:
    if INSPECTOR_PLUGINS.exists():
        return
    partial = INSPECTOR_HOME / "plugins.partial"
    shutil.rmtree(partial, ignore_errors=True)
    for plugin, version in PLUGINS.items():
        url = f"{MARKETPLACE_DOWNLOAD}?{urlencode({'pluginId': plugin, 'version': version})}"
        try:
            with urllib.request.urlopen(url) as response, tempfile.TemporaryFile() as archive:  # noqa: S310 a fixed https URL
                shutil.copyfileobj(response, archive)
                zipfile.ZipFile(archive).extractall(partial)
        except (OSError, zipfile.BadZipFile) as error:
            raise InspectionUnknownError(f"Could not install the PyCharm plugin {plugin} {version} from {url}: {error}") from error
    partial.rename(INSPECTOR_PLUGINS)


def prepare_inspection(repository: Path) -> tuple[Path, Path]:
    forget_earlier_inspections()
    try:
        install_plugins_into_new_home()
        interpreter = read_interpreter(repository)
        shutil.rmtree(PROOF_PROJECT, ignore_errors=True)
        shutil.copytree(PACKAGE / "proofs", PROOF_PROJECT)
        trust_projects((repository, PROOF_PROJECT))
        names = {project_interpreter_name(repository), project_interpreter_name(PROOF_PROJECT)}
        register_interpreter(names, interpreter)
        set_sql_dialect_if_unset(repository)
        return write_run_settings(interpreter.version)
    except (OSError, ElementTree.ParseError) as error:
        raise InspectionUnknownError(f"Could not prepare PyCharm to inspect {repository}: {error}") from error


def write_run_settings(python_version: str) -> tuple[Path, Path]:
    profile, properties = INSPECTOR_HOME / "profile.xml", INSPECTOR_HOME / "idea.properties"
    profile.write_text(PROFILE_TEMPLATE.read_text().replace("PYTHON_VERSION", python_version))
    properties.write_text("".join(f"idea.{kind}.path={INSPECTOR_HOME / kind}\n" for kind in ("config", "system", "plugins", "log")))
    return profile, properties


def forget_earlier_inspections() -> None:
    try:
        shutil.rmtree(INSPECTOR_CACHES)
    except FileNotFoundError:
        return
    except OSError as error:
        raise InspectionUnknownError(
            f"Could not clear PyCharm's caches in {INSPECTOR_CACHES}, so this run could reuse a broken project state: {error}. "
            "Remove that folder by hand, then run again."
        ) from error


def trust_projects(projects: tuple[Path, ...]) -> None:
    entries = "".join(f'<entry key={quoteattr(str(project))} value="true" />' for project in projects)
    INSPECTOR_OPTIONS.mkdir(parents=True, exist_ok=True)
    (INSPECTOR_OPTIONS / "trusted-paths.xml").write_text(
        '<application><component name="Trusted.Paths"><option name="TRUSTED_PROJECT_PATHS"><map>'
        f"{entries}</map></option></component></application>\n"
    )


def register_interpreter(names: set[str], interpreter: Interpreter) -> None:
    roots = "".join(f'<root url={quoteattr(root.as_uri())} type="simple" />' for root in [*interpreter.roots, TYPESHED_STDLIB])
    jdks = "".join(
        f'<jdk version="2"><name value={quoteattr(name)} /><type value="Python SDK" />'
        f"<homePath value={quoteattr(str(interpreter.executable))} />"
        f'<roots><classPath><root type="composite">{roots}</root></classPath>'
        '<sourcePath><root type="composite" /></sourcePath></roots></jdk>'
        for name in sorted(names)
    )
    INSPECTOR_OPTIONS.mkdir(parents=True, exist_ok=True)
    (INSPECTOR_OPTIONS / "jdk.table.xml").write_text(
        f'<application><component name="ProjectJdkTable">{jdks}</component></application>\n'
    )


def project_interpreter_name(project: Path) -> str:
    settings_file = project / ".idea" / "misc.xml"
    settings = ElementTree.parse(settings_file).getroot() if settings_file.exists() else ElementTree.Element("project", version="4")  # noqa: S314
    root_manager = settings.find("component[@name='ProjectRootManager']")
    if root_manager is None:
        root_manager = ElementTree.SubElement(settings, "component", name="ProjectRootManager", version="2")
    if (name := root_manager.get("project-jdk-name")) is not None:
        return name
    root_manager.set("project-jdk-name", DEFAULT_INTERPRETER_NAME)
    root_manager.set("project-jdk-type", "Python SDK")
    settings_file.parent.mkdir(exist_ok=True)
    ElementTree.ElementTree(settings).write(settings_file, encoding="UTF-8", xml_declaration=True)
    return DEFAULT_INTERPRETER_NAME


def set_sql_dialect_if_unset(project: Path) -> None:
    dialects = project / ".idea" / "sqldialects.xml"
    if not dialects.exists():
        shutil.copyfile(PACKAGE / "proofs" / ".idea" / "sqldialects.xml", dialects)


def run_inspector(project: Path, expected: list[str], profile: Path, properties: Path) -> list[Finding]:
    with tempfile.TemporaryDirectory() as output:
        command = [INSPECTOR, project, profile, output, "-v2", "-format", "json"]
        result = run_quietly(command, INSPECTOR_HOME, {"PYCHARM_PROPERTIES": str(properties)})
        if result.returncode != 0:
            last_lines = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
            raise InspectionUnknownError(f"PyCharm's inspector exited {result.returncode} on {project}:\n{last_lines}")
        missing = unanalyzed_files(expected, result.stdout)
        if missing:
            raise InspectionUnknownError(f"PyCharm finished {project} without analyzing: {', '.join(missing)}")
        return read_findings(Path(output))


def is_planted(file: Path) -> bool:
    return file.resolve().is_relative_to(PACKAGE / "proofs")


def require_proofs_caught(findings: list[Finding]) -> None:
    caught = {(finding.file, finding.line, finding.inspection) for finding in findings}
    failed = [name for name, planted in PROOFS.items() if planted not in caught]
    if failed:
        raise InspectionUnknownError(
            f"These checks did not catch their planted mistake in {PROOF_PROJECT}, so a clean answer would be false: "
            f"{', '.join(failed)}. Look in {INSPECTOR_HOME / 'log' / 'idea.log'}. A missing plugin comes back if you delete "
            f"{INSPECTOR_HOME} and run again; ShellCheck needs the shellcheck program on the PATH."
        )


def inspect_repository(repository: Path) -> list[Finding]:
    require_inspector_installed()
    with exclusive_inspector_home():
        profile, properties = prepare_inspection(repository)
        require_proofs_caught(run_inspector(PROOF_PROJECT, proof_project_files(), profile, properties))
        files = repository_files(repository)
        findings = run_inspector(repository, files, profile, properties)
        return [finding for finding in findings if finding.file in files and not is_planted(repository / finding.file)]


def main() -> int:
    repository = Path.cwd()
    try:
        findings = inspect_repository(repository)
    except InspectionUnknownError as error:
        sys.stderr.write(f"UNKNOWN: {error}\n")
        return 2
    sys.stdout.writelines(f"{finding}\n" for finding in findings)
    sys.stdout.write(f"{len(findings)} findings\n" if findings else f"clean: {repository.name}\n")
    return 1 if findings else 0
