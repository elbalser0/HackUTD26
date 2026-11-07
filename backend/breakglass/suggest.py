"""Suggest (never apply) a one-literal Terraform edit that would make config
match a kept emergency change.

Deliberately narrow and read-only:
  - only MODIFIED records where nothing but port_range changed;
  - only root-module addresses `digitalocean_firewall.<name>` (no modules,
    no count/for_each indexes);
  - only *.tf files directly inside tf_dir (no recursion, files <= 1 MB,
    symlinks resolving outside tf_dir are ignored);
  - only a literal `port_range = "<baseline>"` line inside a static
    `inbound_rule { ... }` block of that resource, and only if exactly one
    such line exists across all files.
The HCL scan is a brace-counting line scanner, not a parser: heredocs and
block comments are not understood, which can only cause a None result or a
skipped match, never a write.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import FirewallRule

MAX_FILE_BYTES = 1_000_000
_ADDRESS_RE = re.compile(r"^digitalocean_firewall\.([A-Za-z_][A-Za-z0-9_-]*)$")
_INBOUND_RE = re.compile(r"^\s*inbound_rule\s*\{")
_PROTO_RE = re.compile(r'^\s*protocol\s*=\s*"([^"]*)"')


def _brace_delta(line: str) -> int:
    """Net { minus } outside string literals and line comments."""
    delta = 0
    in_str = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "#" or line.startswith("//", i):
                break
            elif c == "{":
                delta += 1
            elif c == "}":
                delta -= 1
        i += 1
    return delta


def _candidate_files(tf_dir: Path) -> list[Path]:
    try:
        root = tf_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    if not root.is_dir():
        return []
    files: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    for p in children:
        if p.suffix != ".tf":
            continue
        try:
            real = p.resolve(strict=True)
            if real.parent != root or not real.is_file():
                continue  # symlink pointing elsewhere, or not a regular file
            if real.stat().st_size > MAX_FILE_BYTES:
                continue
        except (OSError, RuntimeError):
            continue
        files.append(p)
    return files


def _find_in_text(lines: list[str], name: str, baseline: FirewallRule) -> list[int]:
    """0-based line indexes of matching port_range literals."""
    header = re.compile(r'^\s*resource\s+"digitalocean_firewall"\s+"' + re.escape(name) + r'"\s*\{')
    port_re = re.compile(
        r'^\s*port_range\s*=\s*"' + re.escape(baseline.port_range or "") + r'"\s*(?:(?:#|//).*)?$'
    )
    hits: list[int] = []
    i = 0
    n = len(lines)
    while i < n:
        if not header.match(lines[i]):
            i += 1
            continue
        depth = _brace_delta(lines[i])
        i += 1
        block_start_depth = None
        block_hits: list[int] = []
        block_proto: str | None = None
        while i < n and depth > 0:
            line = lines[i]
            if block_start_depth is None and depth == 1 and _INBOUND_RE.match(line):
                block_start_depth = depth
                block_hits, block_proto = [], None
            elif block_start_depth is not None and depth == block_start_depth + 1:
                if port_re.match(line):
                    block_hits.append(i)
                m = _PROTO_RE.match(line)
                if m:
                    block_proto = m.group(1).strip().lower()
            depth += _brace_delta(line)
            if block_start_depth is not None and depth <= block_start_depth:
                if block_proto is None or block_proto == baseline.protocol:
                    hits.extend(block_hits)
                block_start_depth = None
            i += 1
    return hits


def suggest_literal_edit(
    tf_dir: Path,
    resource_address: str,
    baseline: FirewallRule | None,
    observed: FirewallRule | None,
) -> str | None:
    if baseline is None or observed is None:
        return None
    if not isinstance(resource_address, str):
        return None
    m = _ADDRESS_RE.match(resource_address)
    if not m:
        return None
    name = m.group(1)
    if (
        baseline.protocol != observed.protocol
        or baseline.sources_key() != observed.sources_key()
        or not baseline.port_range
        or not observed.port_range
        or baseline.port_range == observed.port_range
        or '"' in observed.port_range
        or "\n" in observed.port_range
    ):
        return None

    found: list[tuple[Path, int, str]] = []
    for path in _candidate_files(Path(tf_dir)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        for idx in _find_in_text(lines, name, baseline):
            found.append((path, idx, lines[idx]))
            if len(found) > 1:
                return None
    if len(found) != 1:
        return None

    path, idx, old_line = found[0]
    old_lit = f'"{baseline.port_range}"'
    new_line = old_line.replace(old_lit, f'"{observed.port_range}"', 1)
    lineno = idx + 1
    return (
        f"Suggested edit (not applied): {path.name} line {lineno} - keep "
        f"{observed.protocol} {observed.port_range} in Terraform for {resource_address}\n"
        f"--- a/{path.name}\n"
        f"+++ b/{path.name}\n"
        f"@@ line {lineno} @@\n"
        f"-{old_line}\n"
        f"+{new_line}"
    )
