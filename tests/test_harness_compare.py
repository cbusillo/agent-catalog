import os
import subprocess
from pathlib import Path


def test_stalled_control_keeps_evidence_and_skips_candidate(tmp_path: Path) -> None:
    control, candidate, evidence = (tmp_path / name for name in ("control", "candidate", "evidence"))
    for directory in (control, candidate, evidence):
        directory.mkdir()
    cli = tmp_path / "claude"
    cli.write_text(
        '#!/bin/sh\nif [ "$1" = --version ]; then echo fixture; exit 0; fi\n'
        'pwd >> "$CALLS"\necho "partial output" >&2\nexec sleep 30\n'
    )
    cli.chmod(0o700)
    calls = tmp_path / "calls"
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "CALLS": str(calls), "HARNESS_TEST_TIMEOUT_SECONDS": "1"}
    runner = Path(__file__).resolve().parents[1] / "skills" / "harness-test" / "scripts" / "compare"

    result = subprocess.run(  # noqa: S603 executes the tracked runner against a disposable CLI
        [runner, "claude", control, candidate, evidence],
        input="Read the fixture.",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert calls.read_text().splitlines() == [str(control.resolve())]
    (trial,) = evidence.iterdir()
    assert (trial / "control.stderr").read_text().strip() == "partial output"
    assert not (trial / "candidate.cwd").exists()
