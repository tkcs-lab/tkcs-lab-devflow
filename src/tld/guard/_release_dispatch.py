"""Release dispatch checks of the `no-git-tag` hook (plan 46, D13): is a `gh workflow run` / `gh api` / MCP dispatch
of the release workflow allowed? Stdlib only. `no_git_tag` imports from here; behaviour lives here, wiring there."""
from __future__ import annotations

import json
import os
import posixpath
import re

from tld.guard import markers
from tld.guard._common import Ctx
from tld.guard._gitgh import Item
from tld.guard._shell import is_dynamic

NAME = "no-git-tag"

INSTEAD = ("Tags are cut only by the release workflow, which the owner approves in GitHub; there is no other "
           "route (git-ops deletes branches only). A session starts that workflow only through the release skill, "
           "after the owner's yes. Do not create, move, delete or push a tag from a session; say in your report "
           "that a release is due instead. Reading is fine: `git tag -l`, `git describe`, `git fetch --tags`, "
           "`git ls-remote --tags`.")

def normalise_path(url: str) -> str:
    """The path of an endpoint or URL without query or fragment, percent-decoded and `..` / `//` folded."""
    return posixpath.normpath(re.sub(r"%([0-9a-fA-F]{2})", lambda h: chr(int(h[1], 16)), re.split(r"[?#]", url)[0]))


def deny(what: str) -> str:
    return f"blocked: {what}. {INSTEAD}"

RELEASE_WORKFLOW = "tld-release.yml"

RUN_VALUE_OPTS = ("--ref", "-r", "-R", "--repo")
API_VALUE_OPTS = ("-q", "--jq", "-t", "--template", "-H", "--header", "-p", "--preview", "--hostname", "--cache",
                  "-X", "--method", "--input")
UNREADABLE_WORD = re.compile(r"[{}*?\[\]]")   # brace expansion and globbing: the shell decides the real word
RELEASE_KEY = re.compile(r"inputs\[(dry_run|skip_checks)\]")  # the only bracket keys a release dispatch may carry
UNREADABLE_RELEASE = ("this release dispatch has inputs that cannot be read, so dry_run and skip_checks cannot be "
                      "checked; dispatch with plain -f fields or the MCP inputs")


def _profiles(ctx: Ctx) -> list:
    """The working tree's profile and the trusted copy (both: stricter, never looser)."""
    profiles = [ctx.profile]
    try:
        trusted, available = ctx.trusted()
        if available:
            profiles.append(trusted)
    except Exception:  # noqa: BLE001 - the trusted copy is a bonus here
        pass
    return profiles


def _release_names(ctx: Ctx) -> set[str]:
    """File names (and stems) of the release workflow: `tld-release.yml`, plus `release.workflow` of the working
    tree's profile and of the trusted copy."""
    names = {RELEASE_WORKFLOW}
    for prof in _profiles(ctx):
        section = (prof or {}).get("release")
        value = section.get("workflow") if isinstance(section, dict) else None
        if isinstance(value, str) and value.strip():
            names.add(os.path.basename(value.strip()))
    return names | {re.sub(r"\.ya?ml$", "", n) for n in names}


def is_release_workflow(ctx: Ctx, ident) -> bool:
    return isinstance(ident, str) and os.path.basename(ident.strip()) in _release_names(ctx)


def _is_true(value) -> bool:
    return value is True or value == "true"


def _is_exactly_false(value) -> bool:
    return value is False or value == "false"


def release_real_run(ctx: Ctx, ident, why: str) -> str | None:
    """The deny message for a real release run, or None while the release marker names this workflow."""
    marker = markers.read(ctx.project_dir, "release")
    if marker is not None and isinstance(ident, str):
        want = re.sub(r"\.ya?ml$", "", os.path.basename(ident.strip()))
        have = marker.get("workflow")
        if isinstance(have, str) and re.sub(r"\.ya?ml$", "", os.path.basename(have)) == want:
            return None
    return (f"blocked: {why}. A real release run tags the head of the main branch and publishes a release. Only the "
            "release skill starts one: after the owner's yes it runs 'tld guard allow-release <workflow-file>' (it "
            "lapses after 10 minutes), dispatches, and runs 'tld guard end-allow' afterwards.")


def release_inputs_problem(ctx: Ctx, ident, values: dict[str, list]) -> str | None:
    """Judge a release dispatch whose `dry_run` / `skip_checks` values are known (each key maps to every value
    given): skip_checks true is always denied; a real run needs the marker."""
    if any(not _is_exactly_false(v) for v in values.get("skip_checks", [])):
        return deny("this release dispatch sets skip_checks to something other than false; a session never skips the green-commit check")
    dry = values.get("dry_run", [])
    if not dry or any(not _is_true(v) for v in dry):
        return release_real_run(ctx, ident, "this release dispatch does not set dry_run to true")
    return None

def _glob(word: str) -> bool:
    """A word the shell may expand into other words. Only the two `inputs[...]` field keys a release dispatch is
    allowed to carry are literal; every other bracket key is a word the shell decides (`inputs[a]=b` vanishes
    under nullglob, or matches a file), so it is unreadable."""
    return bool(UNREADABLE_WORD.search(RELEASE_KEY.sub("", word)))


def curl_dispatch_glob(word: str) -> bool:
    """A curl word with glob or brace characters that names a workflow dispatch (a scheme-less URL too): the shell
    decides the real word, so the workflow cannot be checked against the release one."""
    if not UNREADABLE_WORD.search(word):
        return False
    bare = UNREADABLE_WORD.sub("", word)
    return "dispatch" in bare or "workflows" in bare


def _release_fields(words: list[str], start: int, skip_opts: tuple[str, ...], keymap: dict[str, str]):
    """(values, unreadable): every -f/-F value whose key is in `keymap` (key -> name, matched case-insensitively).
    An option that takes a value consumes the next word verbatim, even one that looks like a flag."""
    values: dict[str, list] = {"dry_run": [], "skip_checks": []}
    unreadable, i = False, start
    while i < len(words):
        w = words[i]
        i += 1
        name, eq, val = w.partition("=")
        short = w[:2] in ("-f", "-F") and len(w) > 2 and not w.startswith("--")
        if name in ("-f", "--raw-field", "-F", "--field") or short:
            if short:
                val = w[2:].lstrip("=") if w[2:3] == "=" else w[2:]
            elif not eq:
                val, i = (words[i] if i < len(words) else ""), i + 1
            key, _, v = val.partition("=")
            if w.startswith(("-F", "--field")) and v.startswith("@"):
                unreadable = True
            if key.lower() in keymap:
                values[keymap[key.lower()]].append(v)
        elif name == "--json" or name == "--input":
            unreadable = True
            i += 0 if eq or name == "--json" else 1
        elif name in skip_opts and not eq:
            i += 1
        elif w[:2] in skip_opts and not w.startswith("--") and len(w) == 2:
            i += 1
    return values, unreadable


def _release_gh_run(ctx: Ctx, it: Item, ident: str) -> str | None:
    """`gh workflow run <release workflow>`: every -f/-F value of dry_run and skip_checks is read."""
    values, unreadable = _release_fields(it.words, 0, RUN_VALUE_OPTS, {"dry_run": "dry_run", "skip_checks": "skip_checks"})
    if unreadable or any(is_dynamic(w) or _glob(w) for w in it.words):
        return deny(UNREADABLE_RELEASE)
    return release_inputs_problem(ctx, ident, values)


def _release_api(ctx: Ctx, it: Item, api, ident: str) -> str | None:
    """`gh api .../dispatches` of the release workflow: inputs[dry_run] / inputs[skip_checks] fields. A body file is
    never read (it can change between the check and the run)."""
    keymap = {"inputs[dry_run]": "dry_run", "inputs[skip_checks]": "skip_checks"}
    values, unreadable = _release_fields(it.words, 2, API_VALUE_OPTS, keymap)
    if unreadable or api.field_files or api.input_file or any(is_dynamic(w) for w in it.words) \
            or any(_glob(w) for w in it.words):
        return deny(UNREADABLE_RELEASE)
    return release_inputs_problem(ctx, ident, values)

def _release_mcp(ctx: Ctx, wid: str, inputs) -> str | None:
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except ValueError:
            return deny(UNREADABLE_RELEASE)
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        return deny(UNREADABLE_RELEASE)
    values: dict[str, list] = {"dry_run": [], "skip_checks": []}
    for k, v in inputs.items():
        if isinstance(k, str) and k.lower() in values:
            values[k.lower()].append("true" if v is True else "false" if v is False else v if isinstance(v, str) else "?")
    return release_inputs_problem(ctx, wid, values)


RUN_FIELD_OPTS = ("-f", "-F", "--field", "--raw-field")


def run_workflow_arg(words: list[str]) -> str | None:
    """The workflow argument of `gh workflow run`: the first positional word after `run`, not any word that merely
    looks like a workflow name (a field value, a branch). Options that take a value consume the next word."""
    try:
        i = words.index("workflow")
        i = words.index("run", i) + 1
    except ValueError:
        return None
    while i < len(words):
        w = words[i]
        i += 1
        if w.startswith("-"):
            if "=" not in w and w in RUN_VALUE_OPTS + RUN_FIELD_OPTS:
                i += 1
        else:
            return w
    return None


CURL_VALUE_OPTS = ("-H", "--header", "-X", "--request", "--method", "-u", "--user", "-o", "--output", "-A",
                   "--user-agent", "-e", "--referer", "-b", "--cookie", "-d", "--data", "--data-raw", "--data-binary",
                   "--data-ascii", "--data-urlencode", "--json", "-F", "--form", "--form-string", "-T",
                   "--upload-file", "--post-data", "--post-file", "--body-data", "--body-file")
CURL_API_TEXT = re.compile(r"workflows|dispatch|releases|git/(refs|tags)|actions/runs")


def curl_dynamic_url(words: list[str]) -> bool:
    """A non-option curl word the shell expands (`https://api.github.com/repos/$REPO/...`, `"$URL"`) that may be
    the URL of a release, tag or dispatch call: its real value cannot be checked."""
    for k, w in enumerate(words[1:], 1):
        if not is_dynamic(w) or w.startswith("-") or (k > 1 and words[k - 1] in CURL_VALUE_OPTS):
            continue
        if CURL_API_TEXT.search(w) or w.startswith(("$", "`")) or "://" in w or "/" in w:
            return True
    return False
