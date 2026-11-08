"""The CLI is called `argus` (the product was renamed), with NO breaking changes: the old `breakglass`
command, `python -m breakglass.cli`, the `breakglass` Python package, BG_* settings and
`uvicorn breakglass.api:app` all keep working. Offline."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from breakglass import cli

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def test_the_parser_is_named_argus(capsys):
    assert cli.build_parser().prog == "argus"
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("usage: argus")


def test_both_console_scripts_exist_and_run_the_same_entry_point():
    scripts = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["argus"] == "breakglass.cli:main"
    assert scripts["breakglass"] == "breakglass.cli:main"  # old name kept: not a breaking change


def test_the_python_package_and_module_entry_point_are_unchanged():
    out = subprocess.run([sys.executable, "-m", "breakglass.cli", "--help"], capture_output=True, text=True,
                         env={**os.environ, "BG_NO_DOTENV": "1"})
    assert out.returncode == 0 and out.stdout.startswith("usage: argus")


def test_repo_launcher_runs_the_cli_without_installing_anything():
    launcher = REPO / "argus"
    assert launcher.is_file() and os.access(launcher, os.X_OK)
    out = subprocess.run([str(launcher), "--help"], capture_output=True, text=True,
                         env={**os.environ, "BG_NO_DOTENV": "1", "ARGUS_PYTHON": sys.executable})
    assert out.returncode == 0 and out.stdout.startswith("usage: argus")


def test_user_facing_command_hints_say_argus_not_breakglass():
    """Commands shown to people ("run `argus scan`") use the new name. Module paths such as
    `breakglass.api:app` or `-m breakglass.cli` are code, not command hints, and stay."""
    offenders = []
    for f in sorted((BACKEND / "breakglass").glob("*.py")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"`breakglass [a-z]|[\"']breakglass [a-z-]+ |breakglass report \{", line):
                offenders.append(f"{f.name}:{n}: {line.strip()[:90]}")
    assert not offenders, "\n".join(offenders)


def test_other_settings_and_names_are_untouched():
    from breakglass import config
    assert config.Settings  # settings still load from BG_* variables
    assert "BG_DATABASE_URL" in (BACKEND / "breakglass" / "config.py").read_text()


def test_launcher_keeps_the_callers_directory_so_relative_paths_work(tmp_path):
    (tmp_path / "plan.json").write_text('{"resource_drift": []}')
    out = subprocess.run([str(REPO / "argus"), "scan", "--from-json", "plan.json", "--label", "authored-fixture",
                          "--no-prompt"], capture_output=True, text=True, cwd=tmp_path,
                         env={**os.environ, "BG_NO_DOTENV": "1", "ARGUS_PYTHON": sys.executable,
                              "BG_DB_PATH": str(tmp_path / "x.db")})
    assert out.returncode == 0 and "Scan ok: 0 new" in out.stdout, out.stdout + out.stderr
