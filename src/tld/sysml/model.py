"""Name resolution and checks of the model of tld's documented subset of the SysML v2 textual notation.

The subset is intended to parse in SysML v2 tools; tld does not check it against one.
`build` parses every file with `tld.sysml.parse`, and when no file has a syntax or character finding it checks
the whole model: limits, duplicate names, name resolution, docs of part defs and connects.
Model text is untrusted: `build` accepts at most the sizes `files.load_tree` enforces and raises nothing but
`ModelError`; every name echoed in a message is bounded and escaped. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass

from tld.sysml.files import MODEL_DIR, check_relpath
from tld.sysml.parse import parse_file
from tld.sysml.types import (
    MAX_ELEMENTS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_RELATIONS,
    MAX_TOTAL_BYTES,
    Element,
    Finding,
    ModelError,
)

_COUNTED = frozenset({"package", "part def", "port def", "part", "port"})
_RELATIONS = frozenset({"connect", "dependency"})
_ECHO_MAX = 200


@dataclass
class Model:
    """The checked model. `types` maps a part or port usage to the qname of its type def; `targets` maps a
    dependency to `(from qname, to qname)` and a connect to `(type qname of a, type qname of b)`."""

    elements: tuple[Element, ...]
    index: dict[str, Element]
    types: dict[str, str]
    targets: dict[str, tuple[str, ...]]


def _show(text: str) -> str:
    """A name or reference for a message: bounded, and every non-printable character escaped."""
    out = "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in text)
    return out if len(out) <= _ECHO_MAX else out[: _ECHO_MAX - 3] + "..."


def _limit_finding(message: str) -> Finding:
    return Finding(MODEL_DIR, 0, message)


def _guard_sizes(files: dict[str, str], names: dict[str, str]) -> None:
    """Refuse input larger than files.load_tree allows, for callers that did not come through it."""
    if len(files) > MAX_FILES:
        raise ModelError(f"more than {MAX_FILES} model files")
    total = 0
    for rel, text in files.items():
        size = len(text.encode("utf-8", "surrogatepass"))
        if size > MAX_FILE_BYTES:
            raise ModelError(f"{_show(names.get(rel, f'{MODEL_DIR}/{rel}'))} is longer than {MAX_FILE_BYTES} bytes")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ModelError(f"the model is larger than {MAX_TOTAL_BYTES} bytes")


def _resolve(ref: str, scope: str, index: dict[str, Element]) -> Element | None:
    """Resolve `ref` written inside the namespace `scope` ("" at the top).

    The first segment is looked up as a member of each enclosing namespace, innermost first, then at the top;
    the remaining segments are looked up as members one by one. Once the first segment is found there is no
    fall-back to an outer namespace."""
    first, _, rest = ref.partition("::")
    ns = scope
    found: str | None = None
    while True:
        cand = f"{ns}::{first}" if ns else first
        if cand in index:
            found = cand
            break
        if not ns:
            return None
        ns = ns.rpartition("::")[0]
    if rest:
        for seg in rest.split("::"):
            found = f"{found}::{seg}"
            if found not in index:
                return None
    return index[found]


def build(files: dict[str, str], names: dict[str, str] | None = None) -> tuple[Model, list[Finding]]:
    """Parse and check a model given as `{relpath: text}`; returns the model and the findings.

    The file name in findings is `names[relpath]` when given, else `sysml/model/<relpath>`. A model with
    findings still carries the elements that were built. Raises ModelError for an invalid relpath or a model
    larger than the limits of `files.load_tree`."""
    names = names or {}
    for rel in files:
        check_relpath(rel)
    _guard_sizes(files, names)

    elements: list[Element] = []
    findings: list[Finding] = []
    for rel in sorted(files):
        els, fs = parse_file(files[rel], names.get(rel, f"{MODEL_DIR}/{rel}"))
        elements.extend(els)
        findings.extend(fs)

    index: dict[str, Element] = {}
    for el in elements:
        index.setdefault(el.qname, el)
    model = Model(tuple(elements), index, {}, {})
    if findings:
        return model, sorted(findings, key=lambda f: (f.file, f.line, f.message))

    if sum(1 for e in elements if e.kind in _COUNTED) > MAX_ELEMENTS:
        return model, [_limit_finding(f"too many elements (limit {MAX_ELEMENTS})")]
    if sum(1 for e in elements if e.kind in _RELATIONS) > MAX_RELATIONS:
        return model, [_limit_finding(f"too many relations (limit {MAX_RELATIONS})")]

    seen: set[str] = set()
    for el in elements:
        if el.qname in seen:
            findings.append(Finding(el.file, el.line, f"duplicate name '{_show(el.qname)}'"))
        seen.add(el.qname)

    for el in elements:
        # A duplicate is checked like any element but only the first one of a qname is recorded in the model.
        recorded = index[el.qname] is el
        if el.kind in ("part", "port"):
            want = "part def" if el.kind == "part" else "port def"
            target = _need(el, el.type_ref or "", el.owner, want, index, findings)
            if target is not None and recorded:
                model.types[el.qname] = target.qname
        elif el.kind == "dependency":
            ends = [_need(el, ref, el.owner, "part def", index, findings) for ref in el.ends]
            if recorded and all(e is not None for e in ends):
                model.targets[el.qname] = (ends[0].qname, ends[1].qname)  # type: ignore[union-attr]
        elif el.kind == "part def":
            if not el.doc:
                findings.append(Finding(el.file, el.line, f"part def '{_show(el.qname)}' needs a doc"))
        elif el.kind == "connect":
            _check_connect(el, index, model, findings, recorded)

    return model, sorted(findings, key=lambda f: (f.file, f.line, f.message))


def _need(el: Element, ref: str, scope: str, want: str, index: dict[str, Element],
          findings: list[Finding]) -> Element | None:
    """Resolve `ref` and require the kind `want`; add the finding and return None when it fails."""
    found = _resolve(ref, scope, index)
    if found is None:
        findings.append(Finding(el.file, el.line, f"unknown name '{_show(ref)}'"))
        return None
    if found.kind != want:
        findings.append(Finding(el.file, el.line, f"'{_show(ref)}' is a {found.kind}; a {want} is needed"))
        return None
    return found


def _check_connect(el: Element, index: dict[str, Element], model: Model, findings: list[Finding],
                   recorded: bool) -> None:
    a, p, b, q = el.ends
    owner = el.owner
    usages: list[Element | None] = []
    for name in (a, b):
        usage = index.get(f"{owner}::{name}")
        if usage is None or usage.kind != "part":
            findings.append(Finding(el.file, el.line, f"connect: '{_show(name)}' is not a part of '{_show(owner)}'"))
            usages.append(None)
        else:
            usages.append(usage)
    types: list[str | None] = []
    for usage, name, port in zip(usages, (a, b), (p, q)):
        if usage is None:
            types.append(None)
            continue
        type_name = model.types.get(usage.qname)
        if type_name is None:
            # The usage's type did not resolve (or the usage is a duplicate): its finding was or will be reported.
            resolved = _resolve(usage.type_ref or "", usage.owner, index)
            type_name = resolved.qname if resolved is not None and resolved.kind == "part def" else None
        types.append(type_name)
        if type_name is None:
            continue
        port_el = index.get(f"{type_name}::{port}")
        if port_el is None or port_el.kind != "port":
            findings.append(Finding(el.file, el.line, f"connect: '{_show(name)}' has no port '{_show(port)}'"))
    if recorded and types[0] is not None and types[1] is not None:
        model.targets[el.qname] = (types[0], types[1])
