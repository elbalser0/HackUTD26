"""Shared test helpers: fixture loaders, crafted plan variants, a fake
Terraform runner and scripted prompt/output capture. No subprocess, no network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable, Iterable

from breakglass.db import Database
from breakglass.tfrunner import APPLY_PLAN, SCAN_PLAN, RunResult, Terraform

FIX = Path(__file__).parent / "fixtures" / "authored"
ENV = "demo"
TF_BIN = "terraform-test-bin"


def load(name: str) -> dict:
    if not name.endswith(".json"):
        name += ".json"
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    if not name.endswith(".json"):
        name += ".json"
    return (FIX / name).read_text(encoding="utf-8")


def memdb() -> Database:
    """Fresh database. BG_TEST_BACKEND=postgres (with BG_TEST_DATABASE_URL) runs the suite on TimescaleDB."""
    import os
    if os.environ.get("BG_TEST_BACKEND") == "postgres":
        from breakglass.postgres import PostgresDatabase
        from pg_helpers import migrate_test_schema
        url = os.environ["BG_TEST_DATABASE_URL"]
        return PostgresDatabase(url, schema=migrate_test_schema(url))
    return Database(":memory:")


# ---------------------------------------------------------------------------
# Crafted plan variants (derived in-code from authored fixtures)
# ---------------------------------------------------------------------------

def _set_port(rules: list, old: str, new: str) -> None:
    for r in rules:
        if r.get("port_range") == old:
            r["port_range"] = new


def refresh_variant_9443() -> dict:
    """CRAFTED: refresh_drift_8443 with the live (after) port changed 8443 -> 9443.
    Same declared rule (8080) changed to different evidence => supersede."""
    p = copy.deepcopy(load("refresh_drift_8443"))
    _set_port(p["resource_drift"][0]["change"]["after"]["inbound_rule"], "8443", "9443")
    for rc in p.get("resource_changes", []):
        for side in ("before", "after"):
            _set_port(rc["change"][side]["inbound_rule"], "8443", "9443")
    return p


def refresh_other_address() -> dict:
    """CRAFTED: refresh_drift_8443 with the drift entry moved to a different
    firewall address (digitalocean_firewall.api). Produces a distinct record."""
    p = copy.deepcopy(load("refresh_drift_8443"))
    e = p["resource_drift"][0]
    e["address"] = "digitalocean_firewall.api"
    e["name"] = "api"
    p["resource_changes"] = []
    return p


def plan_noop_with_firewall(port: str = "8443") -> dict:
    """CRAFTED: a normal plan whose only entry is digitalocean_firewall.web with
    actions ["no-op"] and identical before/after (rule set with `port` + ssh 22)."""
    p = copy.deepcopy(load("plan_no_changes"))
    p["resource_changes"] = [rc for rc in p["resource_changes"] if rc["address"] == "digitalocean_firewall.web"]
    rc = p["resource_changes"][0]
    _set_port(rc["change"]["before"]["inbound_rule"], "8443", port)
    rc["change"]["after"] = copy.deepcopy(rc["change"]["before"])
    return p


def plan_without_firewall() -> dict:
    """CRAFTED: a normal plan with only a droplet no-op entry (firewall absent)."""
    p = copy.deepcopy(load("plan_no_changes"))
    p["resource_changes"] = [rc for rc in p["resource_changes"] if rc["address"] != "digitalocean_firewall.web"]
    assert p["resource_changes"], "fixture changed: expected a droplet entry"
    return p


# ---------------------------------------------------------------------------
# Fake terraform runner
# ---------------------------------------------------------------------------

class FakeRunner:
    """Callable matching tfrunner.Runner. Records every call.

    scan_exit / apply_plan_exit: exit codes for refresh-only / normal plan.
    scan_json / apply_json: stdout text for `show -json` of each plan.
    workspaces: successive values for `workspace show` (last one repeats).
    """

    def __init__(self, *, scan_exit: int = 2, apply_plan_exit: int = 2,
                 scan_json: str | None = None, apply_json: str | None = None,
                 workspaces: Iterable[str] = ("default",), apply_exit: int = 0):
        self.scan_exit = scan_exit
        self.apply_plan_exit = apply_plan_exit
        self.scan_json = scan_json if scan_json is not None else load_text("refresh_drift_8443")
        self.apply_json = apply_json if apply_json is not None else load_text("plan_reverts_8443")
        self.workspaces = list(workspaces)
        self.apply_exit = apply_exit
        self.calls: list[tuple[list[str], Path, int, bool]] = []
        self.plan_files_seen: list[Path] = []

    @property
    def apply_calls(self) -> list[list[str]]:
        return [c[0] for c in self.calls if len(c[0]) > 1 and c[0][1] == "apply"]

    def __call__(self, args, cwd, timeout, stream):
        assert isinstance(args, list), "runner must receive an argument list"
        self.calls.append((list(args), Path(cwd), timeout, stream))
        sub = args[1:]
        if sub[:2] == ["workspace", "show"]:
            ws = self.workspaces.pop(0) if len(self.workspaces) > 1 else self.workspaces[0]
            return RunResult(0, ws + "\n", "")
        if sub[0] == "plan":
            out = next(a for a in sub if a.startswith("-out="))[len("-out="):]
            refresh = "-refresh-only" in sub
            code = self.scan_exit if refresh else self.apply_plan_exit
            if code in (0, 2):
                path = Path(cwd) / out
                path.write_bytes(b"FAKE-PLAN:" + out.encode())
                self.plan_files_seen.append(path)
                return RunResult(code, "planned", "")
            return RunResult(code, "", "Error: simulated plan failure")
        if sub[:2] == ["show", "-json"]:
            name = sub[2]
            text = self.scan_json if name == SCAN_PLAN else self.apply_json
            return RunResult(0, text, "")
        if sub[0] == "apply":
            return RunResult(self.apply_exit, "", "")
        raise AssertionError(f"unexpected terraform call: {args}")


def make_tf(tmp_path: Path, runner: FakeRunner) -> Terraform:
    (tmp_path / "main.tf").write_text('resource "digitalocean_firewall" "web" {}\n', encoding="utf-8")
    return Terraform(tmp_path, runner=runner, binary=TF_BIN)


# ---------------------------------------------------------------------------
# Scripted prompt / captured output
# ---------------------------------------------------------------------------

class Script:
    """prompt(): returns answers in order; raises EOFError when exhausted.
    An answer may be a callable (side effect, e.g. mutate a file) returning the text."""

    def __init__(self, *answers: str | Callable[[], str]):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.lines: list[str] = []

    def prompt(self, text: str) -> str:
        self.prompts.append(text)
        if not self.answers:
            raise EOFError
        a = self.answers.pop(0)
        return a() if callable(a) else a

    def out(self, line: str) -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines + self.prompts)

    @property
    def output(self) -> str:
        return "\n".join(self.lines)
