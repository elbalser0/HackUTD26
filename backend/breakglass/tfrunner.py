"""Terraform subprocess wrapper.

Security:
- Argument arrays only, shell=False. No user-supplied flags or paths.
- cwd is the allowlisted Terraform directory from server config.
- Plan files have fixed names inside that directory and are deleted after use
  (saved plans can contain sensitive values).
- DIGITALOCEAN_TOKEN: if not already in the environment, it is read from a
  token file (default ~/.secrets/digitalocean_token) into the CHILD process
  environment only. It is never logged, printed, or stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import config

SCAN_PLAN = ".breakglass-scan.tfplan"
APPLY_PLAN = ".breakglass-apply.tfplan"

DEFAULT_TOKEN_FILE = Path.home() / ".secrets" / "digitalocean_token"
TOKEN_ENV = "DIGITALOCEAN_TOKEN"


class TerraformError(RuntimeError):
    pass


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], Path, int, bool], RunResult]


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    # Inherited TF_CLI_ARGS* could silently alter plans (e.g. -destroy, -target);
    # TF_LOG* could write request details to disk.
    for k in list(env):
        if k.startswith("TF_CLI_ARGS") or k.startswith("TF_LOG"):
            env.pop(k)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    if not env.get(TOKEN_ENV):
        token_file = Path(config.bg_env("BG_DO_TOKEN_FILE") or DEFAULT_TOKEN_FILE).expanduser()
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token:
            env[TOKEN_ENV] = token
    return env


def subprocess_runner(args: list[str], cwd: Path, timeout: int, stream: bool) -> RunResult:
    if stream:
        # Apply: stream to the terminal, NO timeout, and never kill Terraform mid-apply
        # (that can leave a held lock, lost state writes, or a half-updated firewall).
        proc = subprocess.Popen(args, cwd=cwd, env=child_env(), shell=False)
        interrupted = False
        while True:
            try:
                code = proc.wait()
                break
            except KeyboardInterrupt:
                interrupted = True  # Terraform got the same Ctrl+C and stops gracefully; keep waiting
        if interrupted:
            raise KeyboardInterrupt
        return RunResult(code, "", "")
    try:
        proc = subprocess.run(args, cwd=cwd, env=child_env(), timeout=timeout, shell=False, check=False,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        raise TerraformError(f"terraform {args[1] if len(args) > 1 else ''} timed out after {timeout}s") from e
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def _short(text: str, limit: int = 1500) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[-limit:]


class Terraform:
    def __init__(self, tf_dir: Path, runner: Runner = subprocess_runner, binary: str = "terraform",
                 timeout: int = 900):
        self.tf_dir = Path(tf_dir)
        self.runner = runner
        self.binary = binary
        self.timeout = timeout

    def _run(self, *args: str, stream: bool = False) -> RunResult:
        return self.runner([self.binary, *args], self.tf_dir, self.timeout, stream)

    def workspace(self) -> str:
        r = self._run("workspace", "show")
        if r.returncode != 0:
            raise TerraformError(f"terraform workspace show failed: {_short(r.stderr)}")
        return r.stdout.strip()

    def plan(self, out_name: str, refresh_only: bool = False) -> bool:
        """Create a saved plan. Returns True if changes are present.

        Uses -detailed-exitcode: 0 = no changes, 2 = changes, anything else = error.
        """
        if out_name not in (SCAN_PLAN, APPLY_PLAN):
            raise ValueError("unexpected plan file name")
        args = ["plan", "-input=false", "-lock-timeout=30s", "-detailed-exitcode", f"-out={out_name}"]
        if refresh_only:
            args.insert(1, "-refresh-only")
        r = self._run(*args)
        if r.returncode == 0:
            return False
        if r.returncode == 2:
            return True
        raise TerraformError(f"terraform plan failed (exit {r.returncode}): {_short(r.stderr or r.stdout)}")

    def show_json(self, plan_name: str) -> dict[str, Any]:
        if plan_name not in (SCAN_PLAN, APPLY_PLAN):
            raise ValueError("unexpected plan file name")
        r = self._run("show", "-json", plan_name)
        if r.returncode != 0:
            raise TerraformError(f"terraform show failed: {_short(r.stderr)}")
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise TerraformError(f"terraform show returned invalid JSON: {e}") from e
        if not isinstance(data, dict):
            raise TerraformError("terraform show JSON is not an object")
        return data

    def apply_saved(self, plan_name: str) -> int:
        """Apply EXACTLY the given saved plan. Saved-plan apply has no interactive
        approval of its own: the caller must have already obtained confirmation."""
        if plan_name != APPLY_PLAN:
            raise ValueError("only the wrapper's saved apply plan may be applied")
        r = self._run("apply", "-input=false", "-lock-timeout=30s", plan_name, stream=True)
        return r.returncode

    # ---- integrity -----------------------------------------------------
    def plan_hash(self, plan_name: str) -> str | None:
        p = self.tf_dir / plan_name
        try:
            return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            return None

    def config_hash(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.tf_dir.iterdir(), key=lambda x: x.name):
            if p.is_file() and not p.is_symlink() and (
                p.suffix in (".tf", ".tfvars") or p.name == ".terraform.lock.hcl" or p.name.endswith(".tf.json")
            ):
                h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
        return "sha256:" + h.hexdigest()

    def cleanup(self) -> None:
        for name in (SCAN_PLAN, APPLY_PLAN):
            try:
                (self.tf_dir / name).unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"WARNING: could not delete {name} ({e.__class__.__name__}); it may contain "
                      "sensitive values. Delete it manually.")
