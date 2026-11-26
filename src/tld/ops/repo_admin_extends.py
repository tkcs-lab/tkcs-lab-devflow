"""Resolve `extends` of a repo-admin policy through the GitHub API: parse, fetch, check, merge, and the latest pin.

Every extended file is text from a repository somebody else may control, so it is data: bounded in size, read with
safe_load only, checked for credentials, anchors and shape before anything looks at its keys, and refused (never
guessed) on any doubt. The pin must be a full commit that is an ancestor of the base repository's default branch.

`ApiError` and `validate_policy` are imported from tld.ops.repo_admin inside the functions that use them: repo_admin
imports its helper modules at the top, so a module-level import here would be a cycle.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from tld.ops import repo_admin_policy as policy_mod
from tld.profile import base as base_mod

MAX_EXTENDS = 4
READ_HINT = "a private file needs a token that can read it (GH_TOKEN, GITHUB_TOKEN or gh auth login)"


@dataclass(frozen=True)
class Layer:
    label: str  # `<owner>/<repo>/<path>@<sha7>`
    doc: dict
    public: bool


@dataclass
class Resolved:
    policy: dict | None
    sources: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def shape_errors(text, label: str) -> tuple[dict | None, list[str]]:
    """The one shape check of every extended file and override: (the mapping, []) or (None, the refusals)."""
    return base_mod.check_base_shape(text, f"{label}: ")


def parse_list(value) -> tuple[list[base_mod.BaseRef], list[str]]:
    """The `extends` value as pins. An empty or missing value is an empty result: the policy is not inherited."""
    if value is None or value == [] or value == "":
        return [], []
    entries = [value] if isinstance(value, str) else value
    if not isinstance(entries, list):
        return [], ["'extends': must be a string or a list of one to four strings"]
    if len(entries) > MAX_EXTENDS:
        return [], [f"'extends': at most {MAX_EXTENDS} entries (got {len(entries)})"]
    refs: list[base_mod.BaseRef] = []
    errors: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        try:
            ref = base_mod.parse_extends(entry, label=f"'extends[{i}]'", hint="tld ops repo-admin latest-pin {source}")
        except base_mod.BaseError as exc:
            errors.append(str(exc))
            continue
        if ref.source in seen:
            errors.append(f"'extends': {ref.source} is listed twice")
            continue
        seen.add(ref.source)
        refs.append(ref)
    return refs, errors


def _quote(text: str) -> str:
    return urllib.parse.quote(text, safe="/")


def _cannot_read(index: int, label: str, exc) -> str:
    return (f"'extends[{index}]': cannot read {label} (HTTP {exc.status}: {base_mod._show(exc.message)}); {READ_HINT}")


def fetch_layer(client, ref: base_mod.BaseRef, index: int) -> tuple[Layer | None, list[str]]:
    """Read one pinned file through the API and check it. Returns (the layer, []) or (None, the errors)."""
    from tld.ops.repo_admin import ApiError, validate_policy
    label = ref.label
    where = f"base {label}"
    repo_path = f"/repos/{ref.owner}/{ref.repo}"
    try:
        info = client.get(repo_path)
        default = info.get("default_branch") if isinstance(info, dict) else None
        if not isinstance(default, str) or not default:
            return None, [f"'extends[{index}]': cannot read {label} (the repository answered without a default branch); {READ_HINT}"]
        compare = client.get(f"{repo_path}/compare/{_quote(default)}...{ref.sha}")
        status = compare.get("status") if isinstance(compare, dict) else None
        if status not in ("behind", "identical"):
            return None, [f"'extends[{index}]': {ref.sha[:7]} is not on the default branch of {ref.owner}/{ref.repo}; "
                          "pin a commit that was merged there"]
        text = client.get_text(f"{repo_path}/contents/{_quote(ref.path)}", {"ref": ref.sha})
    except ApiError as exc:
        return None, [_cannot_read(index, label, exc)]
    if not isinstance(text, str):
        return None, [f"'extends[{index}]': cannot read {label} (the answer is not text); {READ_HINT}"]
    # Anything but an explicit private repository counts as public: the stricter rule applies when in doubt.
    private = info.get("private") is True and info.get("visibility") not in ("public", "internal")
    doc, errors = shape_errors(text, where)
    if doc is None:
        return None, errors
    public = None if private else f"{ref.owner}/{ref.repo}"
    problems = validate_policy(doc, kind="base", where=where, public=public)
    if problems:
        return None, [e if e.startswith(f"{where}: ") else f"{where}: {e}" for e in problems]
    return Layer(label, doc, not private), []


def resolve(client, run_doc: dict) -> Resolved:
    """The organisation policy: the extended files in order, then the run document. Without `extends` the run
    document comes back unchanged. On any error `policy` is None (all errors are collected, none stops the rest)."""
    from tld.ops.repo_admin import validate_policy
    refs, errors = parse_list(run_doc.get("extends"))
    if not refs and not errors:
        return Resolved(run_doc)
    layers: list[Layer] = []
    if not errors:
        for i, ref in enumerate(refs):
            layer, layer_errors = fetch_layer(client, ref, i)
            errors += layer_errors
            if layer is not None:
                layers.append(layer)
    if errors:
        return Resolved(None, errors=errors, labels=[ref.label for ref in refs])
    own = {k: v for k, v in run_doc.items() if k != "extends"}
    merged, sources = policy_mod.merge_layers([(f"base {layer.label}", layer.doc) for layer in layers] + [("run", own)])
    merged = policy_mod.clamp_irreversible(merged, own)
    problems = validate_policy(merged, kind="run", inherited=True)
    labels = [layer.label for layer in layers]
    if problems:
        return Resolved(None, errors=problems, labels=labels)
    bases, _ = policy_mod.merge_layers([(f"base {layer.label}", layer.doc) for layer in layers])
    merged["_inherited"] = True
    merged["_extends"] = labels
    merged["_sources"] = sources
    merged["_run_loosenings"] = [(item.key, item.org_value, item.value) for item in policy_mod.loosened(bases, merged)]
    return Resolved(merged, sources, [], labels)


def latest_pin(client, source: str) -> tuple[str, str | None]:
    """(commit, tag): the newest version tag whose commit has the file (at most 20 tried), else the default branch
    head with tag None. Raises ValueError for a malformed source and LookupError when no commit has the file."""
    from tld.ops.repo_admin import ApiError
    parts = base_mod._split_source(source)
    if parts is None:
        raise ValueError(f"latest-pin: '{base_mod._show(source)}' must be <owner>/<repo>/<path>")
    owner, repo, path = parts
    repo_path = f"/repos/{owner}/{repo}"
    contents = f"{repo_path}/contents/{_quote(path)}"

    def has_file(sha: str) -> bool:
        try:
            client.get(contents, {"ref": sha})
        except ApiError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    tags = client.paginate(f"{repo_path}/tags") or []
    commits = {}
    for tag in tags:
        name = tag.get("name") if isinstance(tag, dict) else None
        sha = (tag.get("commit") or {}).get("sha") if isinstance(tag, dict) and isinstance(tag.get("commit"), dict) else None
        if isinstance(name, str) and base_mod.TAG_RE.match(name) and isinstance(sha, str) and base_mod.SHA40_RE.fullmatch(sha):
            commits[name] = sha.lower()
    for name in sorted(commits, key=base_mod._tag_key, reverse=True)[:base_mod.MAX_TAGS_TRIED]:
        if has_file(commits[name]):
            return commits[name], name
    info = client.get(repo_path)
    default = info.get("default_branch") if isinstance(info, dict) else None
    if not isinstance(default, str) or not default:
        raise LookupError(f"latest-pin: {path} does not exist in {owner}/{repo}")
    head = client.get(f"{repo_path}/branches/{_quote(default)}")
    sha = ((head or {}).get("commit") or {}).get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not base_mod.SHA40_RE.fullmatch(sha) or not has_file(sha.lower()):
        raise LookupError(f"latest-pin: {path} does not exist in {owner}/{repo}")
    return sha.lower(), None
