#!/usr/bin/env python3
"""The architecture model of a repository through four fixed subcommands; no other argument is passed through.

    sysml.py new-change ID [--file R]... [--remove R]...   [--profile .tld/toolkit.yaml] [--root .]
    sysml.py check [--change ID] [--json]                  [--profile .tld/toolkit.yaml] [--root .]
    sysml.py render [--check]                              [--profile .tld/toolkit.yaml] [--root .]
    sysml.py archive ID                                    [--profile .tld/toolkit.yaml] [--root .]

The model is written in a documented subset of the SysML v2 textual notation, intended to parse in SysML v2
tools; tld does not check it against one. It lives in `sysml/model/**.sysml`; a change to it lives in
`sysml/changes/<ID>/` and is applied by `archive`; `render` draws `docs/architecture.svg` and
`docs/architecture.md`. The profile needs `sysml: {subset: 1}`. Pure Python, no network, no other tool. Exit 0
ok, 1 findings or drift, 2 cannot run (usage, bad id or profile, no model, an unsafe path, a file system error).
Model text is untrusted: every name on stderr is escaped, every path goes through `tld.sysml.files`, and only
ModelError, Finding and OSError come up from the modules below; the last two are mapped here to a stderr line.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

from tld.sysml import change, files, layout as layout_mod, markdown, svg
from tld.sysml.diff import diff
from tld.sysml.model import Model, build
from tld.sysml.types import Finding, ModelError

DEFAULT_PROFILE = ".tld/toolkit.yaml"
OUTPUTS = ("docs/architecture.svg", "docs/architecture.md")
COUNTED = frozenset({"package", "part def", "port def", "part", "port"})
# Existing outputs are read for comparison and for undoing an archive; this is far above any real output.
OUTPUT_READ_MAX = 4_000_000
MESSAGE_MAX = 400


def _safe(text: str) -> str:
    """`text` on one line: every non-printable character (ESC, newline, lone surrogate) escaped."""
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in text)


def _line(text: str) -> str:
    """An error message for stderr: escaped and bounded."""
    out = _safe(text)
    return out if len(out) <= MESSAGE_MAX else out[: MESSAGE_MAX - 3] + "..."


class _Parser(argparse.ArgumentParser):
    """A parser whose usage errors echo the offending argument escaped, and exit 2."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {_line(message)}\n")
        raise SystemExit(2)


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _check(ns: argparse.Namespace, root: Path) -> None:
    """Run the checks before anything else, in order; a failure is a ModelError (exit 2)."""
    for ident in (getattr(ns, "id", None), getattr(ns, "change", None)):
        if ident is not None:
            change.valid_id(ident)
    for rel in (*(getattr(ns, "file", None) or []), *(getattr(ns, "remove", None) or [])):
        files.check_relpath(rel)
    profile = Path(ns.profile) if ns.profile else root / DEFAULT_PROFILE
    if "\0" in str(profile) or "\0" in str(root) or not profile.is_file():
        raise ModelError(f"profile not found: {_line(str(profile))}")
    try:
        data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, ValueError, RecursionError):
        data = {}
    block = data.get("sysml") if isinstance(data, dict) else None
    if not isinstance(block, dict) or "subset" not in block:
        raise _Plain("toolkit.yaml: missing required key 'sysml.subset' (add a sysml block; see docs/guides/sysml.md)")
    subset = block["subset"]
    if type(subset) is not int or subset != 1:
        raise ModelError(f"sysml.subset must be 1 (got {_line(repr(subset))})")


class _Plain(ModelError):
    """A ModelError whose message is printed without the `tld ops sysml: ` prefix."""


def _model_files(root: Path) -> dict[str, str]:
    tree = files.load_tree(root)
    if not tree:
        raise ModelError(change.NO_MODEL)
    return tree


def _count(model: Model) -> int:
    return sum(1 for e in model.elements if e.kind in COUNTED)


def _render(model: Model) -> tuple[str, str]:
    """The two outputs of a model that built without findings, in memory."""
    lay = layout_mod.layout(model)
    return svg.to_svg(lay), markdown.to_markdown(model, lay)


def _cmd_new_change(ns: argparse.Namespace, root: Path) -> int:
    state = change.new_change(root, ns.id, ns.file or [], ns.remove or [])
    print(f"{state} {change.CHANGES_DIR}/{ns.id}")
    return 0


def _cmd_check(ns: argparse.Namespace, root: Path) -> int:
    base_files = _model_files(root)
    changes: list = []
    if ns.change:
        _composed, model, findings = change.check_change(root, ns.change, base_files)
        if model is not None:
            changes = diff(build(base_files)[0], model)
    else:
        model, findings = build(base_files)
    if ns.json:
        print(json.dumps({"ok": not findings,
                          "findings": [{"file": f.file, "line": f.line, "message": f.message} for f in findings],
                          "changes": [{"op": c.op, "kind": c.kind, "qname": c.qname} for c in changes]}))
        return 1 if findings else 0
    for f in findings:
        print(_safe(str(f)))
    for c in changes:
        print(_safe(str(c)))
    if findings:
        return 1
    print(f"sysml: ok ({_count(model)} elements)")
    return 0


def _print_findings(findings: list[Finding]) -> int:
    for f in findings:
        print(_safe(str(f)))
    return 1


def _cmd_render(ns: argparse.Namespace, root: Path) -> int:
    model, findings = build(_model_files(root))
    if findings:
        return _print_findings(findings)
    expected = dict(zip(OUTPUTS, _render(model)))
    if not ns.check:
        for path in OUTPUTS:
            files.check_writable(root, path)
        for path in OUTPUTS:
            files.write_text(root, path, expected[path])
            print(f"wrote {path}")
        return 0
    numbers = {OUTPUTS[0]: svg.layout_number, OUTPUTS[1]: markdown.layout_number}
    problems: list[str] = []
    for path in OUTPUTS:
        text = files.read_text(root, path, OUTPUT_READ_MAX)
        number = None if text is None else numbers[path](text)
        if text is None:
            problems.append(f"{path} is missing: run tld ops sysml render")
        elif number is not None and number != layout_mod.LAYOUT_VERSION:
            problems.append(f"{path} was rendered by layout {number}, this tld renders layout "
                            f"{layout_mod.LAYOUT_VERSION}: run tld ops sysml render")
        elif text != expected[path]:
            problems.append(f"{path} is out of date: run tld ops sysml render")
    for p in problems:
        print(p)
    if problems:
        return 1
    print("sysml: docs up to date")
    return 0


def _restore(root: Path, path: str, old: str | None) -> None:
    """Put a file back as it was (`old` None: it did not exist)."""
    if old is None:
        files.remove_file(root, path)
    else:
        files.write_text(root, path, old)


def _cmd_archive(ns: argparse.Namespace, root: Path) -> int:
    base_files = _model_files(root)
    composed, model, findings = change.check_change(root, ns.id, base_files)
    if findings or model is None:  # `archive_plan` trusts its caller: nothing below runs with a finding
        return _print_findings(findings)
    plan = change.archive_plan(root, ns.id, _today(), composed, base_files)
    outputs = dict(zip(OUTPUTS, _render(model)))
    before = {path: files.read_text(root, path, OUTPUT_READ_MAX) for path in OUTPUTS}
    source = f"{change.CHANGES_DIR}/{ns.id}"
    model_paths = {rel: f"{files.MODEL_DIR}/{rel}" for rel in (*plan.write, *plan.delete)}
    for path in (*model_paths.values(), *OUTPUTS, plan.dest):
        files.check_writable(root, path)

    undo = []  # what to run, newest first, when a step fails: the model is never left half applied
    try:
        for rel in plan.write:
            undo.append((_restore, root, model_paths[rel], base_files.get(rel)))
            files.write_text(root, model_paths[rel], plan.composed[rel])
        for rel in plan.delete:
            undo.append((_restore, root, model_paths[rel], base_files[rel]))
            files.remove_file(root, model_paths[rel])
        files.move_dir(root, source, plan.dest)
        undo.append((files.move_dir, root, plan.dest, source))
        for path in OUTPUTS:
            undo.append((_restore, root, path, before[path]))
            files.write_text(root, path, outputs[path])
    except (ModelError, OSError):
        for fn, *args in reversed(undo):
            try:
                fn(*args)
            except (ModelError, OSError):
                pass
        raise
    print(f"archived {source} to {plan.dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help=f"profile path (default {DEFAULT_PROFILE} under --root)")
    common.add_argument("--root", default=".", help="repository root (default: .)")
    ap = _Parser(prog="tld ops sysml", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{new-change,check,render,archive}")
    n = sub.add_parser("new-change", parents=[common], help="create or extend a change (copies model files)")
    n.add_argument("id", metavar="ID")
    n.add_argument("--file", action="append", metavar="R", help="a model file the change replaces (repeatable)")
    n.add_argument("--remove", action="append", metavar="R", help="a model file the change deletes (repeatable)")
    c = sub.add_parser("check", parents=[common], help="check the model, or the model with a change applied")
    c.add_argument("--change", metavar="ID")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("render", parents=[common], help="write docs/architecture.svg and docs/architecture.md")
    r.add_argument("--check", action="store_true", help="compare instead of writing")
    sub.add_parser("archive", parents=[common], help="apply a change to the model, archive it, redraw").add_argument(
        "id", metavar="ID")
    ns = ap.parse_args(argv)
    root = Path(ns.root)
    run = {"new-change": _cmd_new_change, "check": _cmd_check, "render": _cmd_render, "archive": _cmd_archive}
    try:
        _check(ns, root)
        return run[ns.cmd](ns, root)
    except _Plain as e:
        print(_line(str(e)), file=sys.stderr)
        return 2
    except ModelError as e:
        print(f"tld ops sysml: {_line(str(e))}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"tld ops sysml: {_line(str(e))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
