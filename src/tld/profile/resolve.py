"""The profile resolver (plan 90, section 3.1): one loader that every reader calls.

    resolve(raw, ...)        pure: the repository profile, a base and the trusted profile in; a Resolved out
    load(path, ref=...)      reads the file (or `git show REF:path`), gets the base, the trusted copy and the Env
    for_hook(raw, project)   what a hook may do: the base from the cache only, never a fetch, never raises

Load order: parse `tld.extends`, shape check of the raw profile (no required keys), refuse `tld.allow_override`,
merge with the base, built-in defaults, guarded keys against the guard floor, clamp to the trusted profile, the
strict schema check, semantic checks. Errors and warnings are plain messages: the caller adds `toolkit.yaml: `.
Python 3.11+, stdlib and PyYAML. `tld.guard.trust` is imported inside the functions that need it.
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tld.profile import base as base_mod
from tld.profile import defaults, merge as merge_mod
from tld.profile import validate as pv
from tld.profile.base import BaseError, BaseRef, check_base_text, parse_extends
from tld.profile.defaults import Env

PREFIX = "toolkit.yaml: "
MAIN_BRANCH_MISSING = ("missing required key 'git.main_branch' (it could not be detected: no origin/HEAD and no "
                       "remote default branch)")
_WEAKER = re.compile(r"'([^']+)' is weaker here")


@dataclass
class Resolved:
    profile: dict = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # dotted key -> where the value came from
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    base: BaseRef | None = None
    base_missing: bool = False  # the profile extends a base that is not cached (and was not fetched)
    trusted_base_missing: BaseRef | None = None  # the default branch's base, when it is not cached
    trusted_branch: str | None = None


def _plain(message: str) -> str:
    for pre in (PREFIX + "warning: ", PREFIX):
        if message.startswith(pre):
            return message[len(pre):]
    return message


def parse_pin(value: object) -> BaseRef:
    """`parse_extends`, and the pin must be written in lower-case hex (one spelling per commit)."""
    ref = parse_extends(value)
    if value.rpartition("@")[2] != ref.sha:
        raise BaseError(f"{PREFIX}'tld.extends': the pin must be written in lower-case hex "
                        f"(<owner>/<repo>/<path>@<40-hex commit SHA>)")
    return ref


def _extends(raw: dict) -> object:
    tld = raw.get("tld")
    return tld.get("extends") if isinstance(tld, dict) else None


# ---------------------------------------------------------------------------------------------- the base

def base_for(raw: dict, project: str | Path | None, fetch: bool, *, trusted_copy: bool = False):
    """(BaseRef | None, base dict | None, errors, warnings) for the `tld.extends` of `raw`."""
    value = _extends(raw)
    if value is None:
        return None, None, [], []
    try:
        ref = parse_pin(value)
    except BaseError as exc:
        return None, None, [_plain(str(exc))], []
    project = Path(project) if project is not None else Path.cwd()
    git_dir = base_mod.common_dir(project)
    text = base_mod.cached(git_dir, ref) if git_dir is not None else None
    if text is None and fetch:
        try:
            text = base_mod.fetch(project, ref)
        except BaseError as exc:
            return ref, None, [_plain(str(exc))], []
    if text is None:
        what = "the base" if not trusted_copy else "the default branch's base"
        extra = "its values are not applied" if not trusted_copy else (
            "its values and its tld.allow_override are not applied")
        return ref, None, [], [f"{what} {ref.label} is not cached; {extra}"]
    data, errors = check_base_text(text, ref.label)
    return ref, data, [_plain(e) for e in errors], []


# ------------------------------------------------------------------------------------------------- Env

def _git(root: Path | str, *args: str):
    from tld.guard import trust
    return trust._git(str(root), *args)


def _owner_of(url: str | None) -> str | None:
    """The owner in an https, ssh or scp-like remote URL; None for a local path."""
    if not url or url.startswith(("file:", "/", ".")):
        return None
    m = re.match(r"^(?:[a-z][a-z0-9+.-]*://[^/]+/|[^/@\s]+@[^:/\s]+:)(.+?)/?$", url)
    parts = m.group(1).split("/") if m else []
    return parts[-2] if len(parts) >= 2 else None


def origin_url(root: Path | str) -> str | None:
    r = _git(root, "config", "--no-includes", "--get", "remote.origin.url")
    return r.stdout.strip() if r is not None and r.returncode == 0 and r.stdout.strip() else None


def _head_branch(root: Path | str) -> str | None:
    r = _git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    out = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    return out[len("refs/remotes/origin/"):] if out.startswith("refs/remotes/origin/") else None


def fs_env(root: Path | str, owner: str | None = None, branch: str | None = None) -> Env:
    root = Path(root)

    def read(path: str) -> str | None:
        try:
            return (root / path).read_text()
        except (OSError, UnicodeDecodeError):
            return None

    return Env(exists=lambda p: (root / p).exists(), read=read, origin_owner=owner, main_branch=branch)


def tree_env(project: Path | str, rev: str, owner: str | None = None, branch: str | None = None) -> Env:
    """An Env that reads the files of commit `rev` (one `git ls-tree` call for the few paths the file-checked
    defaults ask about, not the whole tree), never the working tree."""
    wanted = ["docs/plans", *(path for _, _, path in defaults.FILE_CHECKED)]
    r = _git(project, "ls-tree", "--name-only", rev, "--", *wanted)
    files = set(r.stdout.splitlines()) if r is not None and r.returncode == 0 else set()

    def read(path: str) -> str | None:
        out = _git(project, "show", f"{rev}:{path}")
        return out.stdout if out is not None and out.returncode == 0 else None

    return Env(exists=lambda p: p in files, read=read, origin_owner=owner, main_branch=branch)


# ----------------------------------------------------------------------------------------------- resolve

def _leaves(node: object, path: str = ""):
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    else:
        yield path, node


def explain_lines(r: Resolved) -> list[str]:
    """`<dotted key> = <json value>  # <source>` for every value of the resolved profile, sorted."""
    label = r.base.label if r.base else ""
    out = []
    for key, value in _leaves(r.profile):
        src = r.sources.get(key)
        parent = key
        while src is None and "." in parent:
            parent = parent.rpartition(".")[0]
            src = r.sources.get(parent)
        src = src or "repo"
        src = src.replace("base", f"base {label}", 1) if src.startswith("base") else src
        out.append(f"{key} = {json.dumps(value)}  # {src}")
    return sorted(out)


def note_line(r: Resolved) -> str:
    values = [s for k, _ in _leaves(r.profile) if (s := _source_of(r, k)) is not None]
    from_base = sum(1 for s in values if s.startswith("base"))
    built_in = sum(1 for s in values if s.startswith(("default", "detected")))
    parts = ([f"{from_base} values from the base {r.base.label}"] if r.base else []) + [f"{built_in} built-in defaults"]
    return f"{PREFIX}note: {', '.join(parts)} (--explain lists them)"


def _source_of(r: Resolved, key: str) -> str | None:
    while key:
        if key in r.sources:
            return r.sources[key]
        key = key.rpartition(".")[0]
    return None


def check_raw(raw, base_ref: BaseRef | None = None):
    """The checks that need only the repository's own profile (run before any base is read or fetched): the removed
    sections, the pin, the shape without required keys, and no `tld.allow_override`.
    Returns (normalised raw, the pin, errors)."""
    if not isinstance(raw, dict):
        return raw, base_ref, ["the profile must be a YAML mapping"]
    if "toolkit" in raw:
        return raw, base_ref, ["'toolkit' was removed: the toolkit is delivered only as plugins "
                               "(docs/guides/delivery.md); delete the 'toolkit' section"]
    if "agents" in raw:
        return raw, base_ref, ["'agents' was renamed to 'roles' (and each entry's 'agent' to 'role'): "
                               "rename the section"]
    raw = pv.normalise(raw)
    if _extends(raw) is not None:
        try:
            base_ref = base_ref or parse_pin(_extends(raw))
        except BaseError as exc:
            return raw, base_ref, [_plain(str(exc))]
    schema = json.loads(pv.SCHEMA.read_text())
    errors: list[str] = []
    pv.check(raw, schema, schema, "", errors, required=False)
    if isinstance(raw.get("tld"), dict) and "allow_override" in raw["tld"]:
        errors.append("'tld.allow_override': only a base profile may set it")
    return raw, base_ref, errors


def resolve(raw, *, base: dict | None = None, base_ref: BaseRef | None = None, trusted: dict | None = None,
            trusted_branch: str | None = None, env: Env | None = None, root_dir: Path | None = None) -> Resolved:
    """The pure resolver. `trusted` is the default branch's already resolved profile, or None."""
    raw, base_ref, errors = check_raw(raw, base_ref)
    if errors:
        return Resolved(errors=errors, base=base_ref)
    schema = json.loads(pv.SCHEMA.read_text())

    allow = list(((base or {}).get("tld") or {}).get("allow_override") or [])
    merged, sources, warnings = merge_mod.merge_with_warnings(base or {}, raw, allow)
    warnings = [_plain(w) for w in warnings]
    env = env or Env()
    if env.origin_owner is not None and not base_mod.OWNER_RE.match(env.origin_owner):
        warnings.append("the origin owner is not a valid GitHub owner name; 'git_ops.repo' has no default")
        env = dataclasses.replace(env, origin_owner=None)
    resolved, dsrc = defaults.apply(merged, env)
    for key, src in dsrc.items():
        if not (src == "repo" and key in sources):  # a base value stays `base`, not `repo`
            sources[key] = src

    if base is not None and base_ref is not None:
        errors += [_plain(e) for e in merge_mod.guarded_errors(base, resolved, allow, base_ref.label)]
    if errors:
        return Resolved(errors=errors, warnings=warnings, base=base_ref)
    if trusted is not None and trusted_branch:
        resolved, clamped = merge_mod.clamp(trusted, resolved, trusted_branch)
        for w in clamped:
            warnings.append(_plain(w))
            m = _WEAKER.search(w)
            if m:
                src = f"{trusted_branch} (the remote default branch; this branch's value is weaker)"
                sources[m.group(1)] = src
                if m.group(1).startswith("roles.required."):
                    sources["roles.required"] = src

    pv.check(resolved, schema, schema, "", errors)
    if errors:
        errors = [MAIN_BRANCH_MISSING if e == "missing required key 'git.main_branch'" else e for e in errors]
        return Resolved(errors=errors, warnings=warnings, base=base_ref)
    resolved["docs"]["plan_dir"] = resolved["docs"]["plan_dir"].rstrip("/")
    sem_errors, sem_warnings = pv.semantic_checks(resolved, root_dir)
    warnings += sem_warnings
    if sem_errors:
        return Resolved(errors=sem_errors, warnings=warnings, base=base_ref)
    return Resolved(resolved, sources, [], warnings, base_ref)


def resolve_dict(raw, root_dir: Path | None = None, *, fetch: bool = True) -> Resolved:
    """A profile that is already parsed (what `validate()` takes): the base from the cache (and a fetch), no
    trusted copy. Without a root there are no existence defaults."""
    ref, base, errors, warnings = base_for(raw, root_dir, fetch) if isinstance(raw, dict) else (None, None, [], [])
    if errors:
        return Resolved(errors=errors, base=ref)
    env = fs_env(root_dir) if root_dir is not None else Env()
    out = resolve(raw, base=base, base_ref=ref, env=env, root_dir=root_dir)
    out.warnings = warnings + out.warnings
    out.base_missing = ref is not None and base is None
    return out


# -------------------------------------------------------------------------------------------------- load

def resolve_ref(root: Path, ref: str) -> tuple[str | None, str | None]:
    """(full commit SHA, error). Only the SHA ever reaches git as a revision: a ref is never an option."""
    from tld.guard.trust import SHA_RE
    if not ref or ref.startswith("-") or "\x00" in ref:
        return None, f"'{ref[:80]}' is not a git ref"
    r = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    sha = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    if not SHA_RE.match(sha):
        return None, f"no profile at '{ref[:80]}': it is not a commit of this repository"
    return sha, None


def _rel_path(path: Path, root: Path) -> tuple[str | None, str | None]:
    """The repository-relative path of the profile for `git show`, or an error."""
    if path.is_absolute():
        top = _git(root, "rev-parse", "--show-toplevel")
        base = Path(top.stdout.strip()) if top is not None and top.returncode == 0 and top.stdout.strip() else root
        try:
            path = path.resolve().relative_to(base.resolve())
        except ValueError:
            return None, f"'{path}' is outside the repository; give a path inside it"
    if ".." in path.parts or not path.parts:
        return None, f"'{path}' must be a path inside the repository"
    return path.as_posix(), None


def _read_profile(path: Path, root: Path, sha: str | None, ref: str | None = None):
    """(parsed YAML, error). `sha` is the resolved commit of --ref, or None for the working tree."""
    if sha:
        rel, err = _rel_path(path, root)
        if err:
            return None, err
        r = _git(root, "show", f"{sha}:{rel}")
        if r is None or r.returncode != 0:
            return None, f"no profile at '{ref}:{rel}'. Check the ref and that it has {rel} ({pv.HELP})."
        text = r.stdout
    elif not path.is_file():
        return None, (f"no profile at '{path}'. Create one from the starter in "
                      f"src/tld/templates/toolkit.yaml ({pv.HELP}).")
    else:
        text = path.read_text()
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        return None, f"not valid YAML: {exc}"


def _trusted_profile(root: Path, owner: str | None, warnings: list[str]):
    """(resolved trusted profile | None, its branch | None, its uncached base | None); appends the warnings."""
    from tld.guard import trust
    t = trust.trusted(str(root))
    if not t.available or t.profile is None:
        why = t.problem or "the default branch has no profile"
        warnings.append(f"no trusted copy of the profile ({why}); guarded keys are taken from this working tree")
        return None, t.branch, None
    ref, tbase, errors, tw = base_for(t.profile, root, False, trusted_copy=True)
    warnings += tw
    missing = ref if (ref is not None and tbase is None and not errors) else None
    out = resolve(t.profile, base=None if errors else tbase, base_ref=None if errors else ref,
                  env=tree_env(root, t.sha, owner, t.branch))
    if out.errors:
        warnings.append(f"no trusted copy of the profile (the profile on {t.branch} does not resolve: "
                        f"{(errors or out.errors)[0][:200]}); guarded keys are taken from this working tree")
        return None, t.branch, missing
    return out.profile, t.branch, missing


def _is_repo_profile(path: Path, root: Path) -> bool:
    """True when `path` is the repository's own `.tld/toolkit.yaml` (the file the default branch's copy stands for)."""
    try:
        return path.resolve() == (root / ".tld" / "toolkit.yaml").resolve()
    except OSError:
        return False


def load(path, *, ref: str | None = None, root=None, fetch: bool = True, trusted: bool = True,
         file_checks: bool = True) -> Resolved:
    """Read the profile (or `git show REF:path`), get the base, resolve. With `trusted` and an origin the
    default branch's profile is resolved on its own and clamps the guarded keys. File checks are skipped at a ref."""
    path = Path(path)
    root = Path(root) if root is not None else path.resolve().parent.parent
    sha = None
    if ref is not None:
        sha, problem = resolve_ref(root, ref)
        if problem:
            return Resolved(errors=[problem])
    raw, problem = _read_profile(path, root, sha, ref)
    if problem:
        return Resolved(errors=[problem])
    raw, _, errors = check_raw(raw)  # raw-only checks first: a bad profile never causes a fetch
    if errors:
        return Resolved(errors=errors)
    base_ref, base, errors, warnings = base_for(raw, root, fetch)
    if errors:
        return Resolved(errors=errors, base=base_ref)
    url = origin_url(root)
    owner = _owner_of(url)
    branch = _head_branch(root)
    trusted = trusted and _is_repo_profile(path, root)  # another file (e.g. the starter) is no copy of main's profile
    trusted_profile = trusted_branch = trusted_missing = None
    if trusted and url:
        trusted_profile, trusted_branch, trusted_missing = _trusted_profile(root, owner, warnings)
        branch = branch or trusted_branch
    elif trusted:
        warnings.append("no trusted copy of the profile (no origin remote); guarded keys are taken from this "
                        "working tree")
    env = tree_env(root, sha, owner, branch) if sha else fs_env(root, owner, branch)
    out = resolve(raw, base=base, base_ref=base_ref, trusted=trusted_profile, trusted_branch=trusted_branch, env=env,
                  root_dir=root if file_checks and not sha else None)
    out.warnings = warnings + out.warnings
    out.base_missing = base_ref is not None and base is None
    out.trusted_base_missing, out.trusted_branch = trusted_missing, trusted_branch
    return out


# ------------------------------------------------------------------------------------------------- hooks

def for_hook(raw, project, *, at_sha: str | None = None) -> tuple[dict | None, str | None]:
    """(resolved profile, notice) for a hook: the base from the cache only, no fetch, no schema file, never raises.
    A base that is not cached is left out, which only adds protection. `at_sha` reads files at that commit."""
    try:
        if not isinstance(raw, dict):
            return None, None
        raw = pv.normalise(raw)
        notice = None
        ref, base, errors, warnings = base_for(raw, project, False)
        if errors or warnings:
            notice = (warnings or errors)[0]
            if warnings and ref is not None:
                notice = f"the base {ref.label} is not cached here; run tld profile validate to fetch it"
        allow = list(((base or {}).get("tld") or {}).get("allow_override") or [])
        merged, _, _ = merge_mod.merge_with_warnings(base or {}, raw, allow)
        from tld.guard.trust import SHA_RE
        valid = isinstance(at_sha, str) and SHA_RE.match(at_sha)  # anything else falls back to the working tree
        env = tree_env(project, at_sha) if valid else fs_env(project, None, _head_branch(project))
        resolved, _ = defaults.apply(merged, env)
        if isinstance(resolved.get("docs"), dict) and isinstance(resolved["docs"].get("plan_dir"), str):
            resolved["docs"]["plan_dir"] = resolved["docs"]["plan_dir"].rstrip("/")
        return resolved, notice
    except Exception as exc:  # noqa: BLE001 - a hook must never fail on the profile
        return None, f"the profile could not be resolved ({type(exc).__name__})"
