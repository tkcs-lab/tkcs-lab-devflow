"""repo-admin checks for the central git-ops repository and for where Actions secrets are held.

Registered as the one entry `git_ops` in repo_admin.CHECKS. It runs only when the policy has a `git_ops`
section (`repo`, `workflow`, `allowlist`). Findings:

- git-ops-workflow, git-ops-allowlist (fix): the central repository lacks the shipped `tld-git-ops.yml` workflow
  or an allowlist naming every audited repository. The fix is one pull request into the central repository through
  apply_files (never a direct push: the workflow file is guarded). The workflow is the template tld ships, copied
  as it is (it has no placeholders); the allowlist is built from the repository names and the organisation only.
- git-ops-environment, git-ops-token (warn, manual text): the environment `git-ops` (deployment branches limited
  to the default branch) and the secret GIT_OPS_TOKEN. They are never created: the owner does it, a secret value
  is never read, stored or printed. Only names, scopes and protection rules are read.
- secrets_scope (warn): an Actions secret of a repository or of the organisation, or one held in an environment
  that any branch may deploy to. A workflow edited on a pushed branch runs at once with such secrets; a secret in an
  environment limited to the default branch is not reported.

Everything read from the audited repositories (names, file text) is untrusted: it is bounded here and never
reaches a pull request title, body or commit message (apply_files writes its own fixed ones).
"""
from __future__ import annotations

import dataclasses
import fnmatch
import json
import re
import urllib.parse

ENV_NAME, SECRET_NAME = "git-ops", "GIT_OPS_TOKEN"
WORKFLOW_DIR = ".github/workflows"
DEFAULT_WORKFLOW = "tld-git-ops.yml"
ALLOWLIST_PATH = "git-ops-allowlist.json"  # the only path the shipped workflow reads
WORKFLOW_TEMPLATE = "tld-git-ops.yml"
ALLOWLIST_TEMPLATE = "git-ops-allowlist.json"
SAFE_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
MAX_WORKFLOW_BYTES = 1_000_000
MAX_ALLOWLIST_BYTES = 256_000
MAX_ENTRIES = 2000
MAX_SHOWN = 8
MAX_ENVIRONMENTS = 100


def _ra():
    from tld.ops import repo_admin
    return repo_admin


def _shown(text, limit: int = 60) -> str:
    """A name from a repository, safe to put in a finding: one line, no markup-significant control characters,
    bounded."""
    text = re.sub(r"[^\w.\-/ ,()]", "?", " ".join(str(text).split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _text(text, limit: int = 300) -> str:
    """A whole message that carries names from a repository: one line, no markup, mention or control character."""
    text = re.sub(r"[^\w .,;()'\-/]", "?", " ".join(str(text).split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _names(names, limit: int = MAX_SHOWN) -> str:
    names = sorted({_shown(n) for n in names})
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _quote(path: str, safe: str = "/") -> str:
    return urllib.parse.quote(path, safe=safe)


# ---------------------------------------------------------------------------------------- the templates

def workflow_template() -> str:
    return (_ra().TEMPLATES / WORKFLOW_TEMPLATE).read_text()


def default_protected_branches() -> list[str]:
    """The protected branch globs of the allowlist template tld ships."""
    data = json.loads((_ra().TEMPLATES / ALLOWLIST_TEMPLATE).read_text())
    return [b for b in data.get("protected_branches", []) if isinstance(b, str)]


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def build_allowlist(owner: str, repos: list[str], protected: list[str]) -> str:
    """The allowlist file: the organisation and the audited repository names come from validated values; entries
    that were already in the file are carried over unchanged (json.dumps escapes them, they cannot inject)."""
    return json.dumps({"owner": owner, "repos": repos, "protected_branches": protected}, indent=2) + "\n"


def parse_allowlist(text: str | None) -> dict | None:
    """The allowlist as the workflow's jq shape check reads it, or None when it would be refused (a missing or
    invalid file, or one too large to trust)."""
    if text is None or len(text.encode("utf-8", "replace")) > MAX_ALLOWLIST_BYTES:
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):  # a deeply nested file must not stop the audit
        return None
    if not isinstance(data, dict) or not isinstance(data.get("owner"), str) or not data["owner"]:
        return None
    repos = data.get("repos")
    if not isinstance(repos, list) or not repos or len(repos) > MAX_ENTRIES or not all(isinstance(r, str) and r for r in repos):
        return None
    protected = data.get("protected_branches", [])
    if not isinstance(protected, list) or len(protected) > MAX_ENTRIES or not all(isinstance(b, str) for b in protected):
        return None
    return data


# ---------------------------------------------------------------------------------------- the central repository

def _read(ctx, fn: str, commit: str, path: str) -> str | None:
    """A file of the central repository at its default branch head; None when it is not there."""
    ra = _ra()
    try:
        return ctx.c.get_text(f"/repos/{fn}/contents/{_quote(path)}", {"ref": commit})
    except ra.ApiError as exc:
        if exc.status == 404:
            return None
        raise


def _central(ctx, cfg: dict) -> str:
    return cfg.get("repo") or f"{ctx.org}/git-ops"


def _mode(snap, path: str) -> str:
    mode = next((e.get("mode", "100644") for e in snap.entries if e["path"] == path), "100644")
    return mode if mode in ("100644", "100755") else "100644"


def _workflow_finding(ctx, central: str, snap, workflow: str) -> list:
    ra = _ra()
    path = f"{WORKFLOW_DIR}/{workflow}"
    have = _read(ctx, central, snap.commit, path)
    want = workflow_template()
    if have is not None and len(have.encode("utf-8", "replace")) <= MAX_WORKFLOW_BYTES and _norm(have) == want:
        return []
    what = "is missing" if have is None else "differs from the one tld ships"
    change = {"op": "put", "path": path, "content": want, "mode": _mode(snap, path)}
    return [ra.Finding("git-ops-workflow", central, f"workflow:{workflow}", f"the central repository {what}: {path}; "
                       "install the shipped workflow with a pull request into its default branch", "fix",
                       ra.Action("files", repo=central, changes=[change]))]


USUAL_GLOB = re.compile(r"[A-Za-z0-9._*?-]{1,100}")


def _usual(glob: str) -> bool:
    """A repos entry the audit can reason about. The workflow matches with bash `[[ == ]]` (extglob on), so an entry
    with [ ] ( ) @ ! + \\ ^ or a newline can match more than fnmatch says: it is reported and counted as broad."""
    return USUAL_GLOB.fullmatch(glob) is not None


def _covers(glob: str, name: str) -> bool:
    """Whether the entry allows the repository. The dispatcher chooses the case of the repository input and GitHub
    finds a repository whatever the case, so the comparison ignores case."""
    return fnmatch.fnmatchcase(name.lower(), glob.lower()) or fnmatch.fnmatchcase(name, glob)


def _places(positions: list[int]) -> str:
    """Where in repos[] the entries are, in words of our own: a lookalike or zero-width character cannot be seen."""
    shown = ", ".join(f"repos[{i}]" for i in positions[:MAX_SHOWN])
    return shown + (f" and {len(positions) - MAX_SHOWN} more" if len(positions) > MAX_SHOWN else "")


def _broad(glob: str) -> bool:
    """A repos entry that matches every repository: only wildcards, or one the audit cannot reason about."""
    return not _usual(glob) or not glob.replace("*", "").replace("?", "")


def _allowlist_finding(ctx, central: str, snap, cfg: dict) -> list:
    ra = _ra()
    wanted_path = cfg.get("allowlist", ALLOWLIST_PATH)
    if wanted_path != ALLOWLIST_PATH:
        return [ra.Finding("git-ops-allowlist", central, "allowlist:path", f"git_ops.allowlist is '{_shown(wanted_path)}', "
                           f"but the shipped workflow reads only {ALLOWLIST_PATH}", "warn",
                           manual=f"set `git_ops.allowlist` to {ALLOWLIST_PATH} in the policy")]
    owner = ctx.org
    audited, skipped = [], []
    for repo in ctx.repos:
        name = repo["name"]
        if repo["full_name"].split("/", 1)[0].lower() != owner.lower():
            continue
        # a name that starts with - or . is never added: the workflow's globs would read it as an option or a hidden path
        (audited if SAFE_REPO.fullmatch(name) and name[0] not in "-." else skipped).append(name)
    audited = sorted(set(audited))
    text = _read(ctx, central, snap.commit, ALLOWLIST_PATH)
    data = parse_allowlist(text)
    notes = f" ({len(skipped)} repository name(s) with unusual characters are left out)" if skipped else ""
    out: list = []
    if data is None and text is not None:
        # never rebuild a file that exists: the owner's protected branches and repos would be lost
        return [ra.Finding("git-ops-allowlist", central, "allowlist", f"{ALLOWLIST_PATH} exists but is not a valid "
                           "allowlist (owner, repos, protected_branches), so it is left as it is", "warn",
                           manual=f"repair {ALLOWLIST_PATH} by hand (a string owner, a non-empty list of repository "
                                  "names, a list of branch globs), then audit again")]
    if data is None:
        if not audited:
            return [ra.Finding("git-ops-allowlist", central, "allowlist", f"{ALLOWLIST_PATH} is missing and no "
                               "repository is in scope to list", "warn",
                               manual=f"add {ALLOWLIST_PATH} with the repositories the workflow may act on")]
        repos, protected = audited, default_protected_branches()
        why = "is missing"
    else:
        existing = list(data["repos"])
        # every existing entry is kept as it is; entries that are too wide are reported, never silently changed
        unusual = [i for i, g in enumerate(existing) if not _usual(g)]
        broad = [i for i, g in enumerate(existing) if _broad(g) and _usual(g)]
        in_scope = {r["name"] for r in ctx.repos}
        outside = sorted({r["name"] for r in ctx.all_repos if r["name"] not in in_scope
                          and any(_covers(g, r["name"]) for g in existing if not _broad(g))})
        if unusual:
            out.append(ra.Finding("git-ops-allowlist", central, "allowlist:unusual", f"{ALLOWLIST_PATH} has {len(unusual)} "
                                  f"repos entry with characters beyond letters, digits, . _ - * ? ({_places(unusual)}), "
                                  "which the workflow's bash matching may read as matching every repository", "warn",
                                  manual="replace each by plain repository names or simple globs"))
        if broad:
            out.append(ra.Finding("git-ops-allowlist", central, "allowlist:broad", f"{ALLOWLIST_PATH} has {len(broad)} "
                                  f"entry made only of wildcards ({_places(broad)}), which matches every repository", "warn",
                                  manual="replace it by the names or globs of the repositories the workflow may act on"))
        if outside:
            out.append(ra.Finding("git-ops-allowlist", central, "allowlist:outside", f"{ALLOWLIST_PATH} also covers "
                                  f"repositories outside this audit: {_names(outside)}", "warn",
                                  manual="narrow the entries, or add those repositories to the audit's scope"))
        owner_ok = data["owner"].lower() == owner.lower()
        if not owner_ok and (unusual or broad or outside or ctx.partial or not ctx.org_complete):
            # a wrong owner makes the workflow refuse every run, so these entries do nothing yet; fixing the owner
            # would switch them on
            return out + [ra.Finding("git-ops-allowlist", central, "allowlist:owner", f"{ALLOWLIST_PATH} names the owner "
                                     f"'{_shown(data['owner'])}', not {owner}, and has entries that match "
                                     "every repository or repositories outside this audit (or this audit did not see "
                                     "every repository); the owner is not changed while that is so", "warn",
                                     manual=f"replace those entries first (see the other findings), then set the owner to {owner}")]
        have_protected = [b for b in data.get("protected_branches", []) if isinstance(b, str)]
        if not have_protected:
            out.append(ra.Finding("git-ops-allowlist", central, "allowlist:protected", f"{ALLOWLIST_PATH} protects "
                                  "no branch (protected_branches is missing or empty)", "warn",
                                  manual="list the branch globs the workflow must never delete"))
        missing = [n for n in audited if not any(_covers(g, n) for g in existing if _usual(g))]
        if owner_ok and not missing and have_protected:
            return out
        repos = existing + missing
        protected = have_protected + ([b for b in default_protected_branches() if b not in have_protected]
                                      if not have_protected else [])
        parts = []
        if not owner_ok:
            parts.append(f"names the owner '{_shown(data['owner'])}', not {owner}")
        if missing:
            parts.append(f"does not list {_names(missing)}")
        if not have_protected:
            parts.append("has no protected branches (the shipped defaults are added)")
        why = " and ".join(parts)
    content = build_allowlist(owner, repos, protected)
    if parse_allowlist(content) is None:  # a file this audit would refuse next time: do not write it
        return out + [ra.Finding("git-ops-allowlist", central, "allowlist:size", f"{ALLOWLIST_PATH} {why}, but the updated "
                                 "file would be too large or have too many entries to keep", "warn",
                                 manual="shorten the lists by hand (use globs for groups of repositories)")]
    change = {"op": "put", "path": ALLOWLIST_PATH, "content": content, "mode": _mode(snap, ALLOWLIST_PATH)}
    return out + [ra.Finding("git-ops-allowlist", central, "allowlist", f"{ALLOWLIST_PATH} {why}{notes}; update it with a "
                             "pull request into the default branch of the central repository", "fix",
                             ra.Action("files", repo=central, changes=[change]))]


def _open_items(ctx, central_repo: dict) -> list:
    """The environment git-ops and the secret GIT_OPS_TOKEN as warnings with manual text; nothing is created."""
    ra = _ra()
    fn = central_repo["full_name"]
    default = ctx.repo(central_repo)["default_branch"]
    shown = _shown(default)
    found: list = []
    out: list = []
    ra._env_and_secret(ctx, "git-ops-environment", fn, central_repo, found, ENV_NAME, SECRET_NAME, "the git-ops workflow")
    for f in found:
        if f.severity in ("unavailable", "error"):
            out.append(dataclasses.replace(f, message=_text(f.message)))
        elif f.subject.startswith("secret:"):
            manual = f.manual or ("set it in the environment (value from the token the owner created; never paste it into chat)")
            out.append(dataclasses.replace(f, check="git-ops-token", severity="warn", action=None, manual=manual))
        else:
            out.append(dataclasses.replace(
                f, check="git-ops-environment", severity="warn", action=None, message=_text(f.message),
                manual=f"in https://github.com/{fn}/settings/environments create `{ENV_NAME}` with deployment branches "
                       f"limited to the selected branch `{shown}` only"))
    return out


def check_central(ctx, cfg: dict) -> list:
    ra = _ra()
    central = _central(ctx, cfg)
    workflow = cfg.get("workflow", DEFAULT_WORKFLOW)
    repo = next((r for r in ctx.all_repos if r["full_name"].lower() == central.lower()), None)
    if repo is None:
        return [ra.Finding("git-ops-workflow", central, "repository", f"the central repository {central} is not among "
                           "the repositories listed for this audit", "warn",
                           manual="create it (private) and run the audit without --repo, or keep it in the organisation")]
    if repo.get("archived"):
        return [ra.Finding("git-ops-workflow", central, "repository", f"the central repository {central} is archived",
                           "warn", manual="unarchive it, or point `git_ops.repo` at another repository")]
    central = repo["full_name"]  # the spelling GitHub uses: apply finds the repository by it
    out: list = []
    snap = ctx.snapshot(repo)
    if snap.empty:
        out.append(ra.Finding("git-ops-workflow", central, "repository", f"the central repository {central} has no commit "
                              "yet, so a pull request cannot be opened", "warn",
                              manual="make a first commit on its default branch (a README), then audit again"))
    else:
        ra._part("git-ops-workflow", central, out, lambda: _workflow_finding(ctx, central, snap, workflow))
        ra._part("git-ops-allowlist", central, out, lambda: _allowlist_finding(ctx, central, snap, cfg))
    ra._part("git-ops-environment", central, out, lambda: _open_items(ctx, repo))
    return out


# ---------------------------------------------------------------------------------------- secrets_scope

def _limited_to_default(ctx, fn: str, env: dict, default: str) -> bool:
    have = env.get("deployment_branch_policy")
    if not isinstance(have, dict) or not have.get("custom_branch_policies"):
        return False
    policies = ctx.c.paginate(f"/repos/{fn}/environments/{_quote(str(env.get('name', '')), '')}/deployment-branch-policies",
                              key="branch_policies")
    return bool(policies) and all(p.get("name") == default and p.get("type", "branch") == "branch" for p in policies)


def _secret_names(ctx, path: str) -> list[dict]:
    return [s for s in ctx.c.paginate(path, key="secrets") if isinstance(s, dict) and s.get("name")]


def secrets_scope(ctx) -> list:
    """Repository and organisation Actions secrets, and secrets of environments any branch may deploy to. Only names
    and scopes are read."""
    ra = _ra()
    Finding = ra.Finding
    out: list = []
    fix = ("move each into an environment limited to the default branch (Settings, Environments), set it there "
           "(the value is never readable), then delete the other secret")

    def org_part():
        found = []
        secrets = _secret_names(ctx, f"/orgs/{ctx.org}/actions/secrets")
        if secrets:
            listed = _names(f"{s['name']} ({s.get('visibility', '?')})" for s in secrets)
            found.append(Finding("secrets_scope", ctx.org, "org-secrets", f"organisation Actions secrets are read by "
                                 f"every workflow on every branch of the repositories they are shared with: {listed}",
                                 "warn", manual=fix))
        return found

    ra._part("secrets_scope", ctx.org, out, org_part)

    def one(repo):
        fn, found = repo["full_name"], []
        default = ctx.repo(repo)["default_branch"]
        secrets = _secret_names(ctx, f"/repos/{fn}/actions/secrets")
        if secrets:
            found.append(Finding("secrets_scope", fn, "repo-secrets", "repository Actions secrets are read by every "
                                 f"workflow on every branch, also one edited on a pushed branch: {_names(s['name'] for s in secrets)}",
                                 "warn", manual=fix))
        envs = [e for e in ctx.c.paginate(f"/repos/{fn}/environments", key="environments") if isinstance(e, dict) and e.get("name")]
        for env in envs[:MAX_ENVIRONMENTS]:
            name = str(env["name"])
            if _limited_to_default(ctx, fn, env, default):
                continue
            held = _secret_names(ctx, f"/repos/{fn}/environments/{_quote(name, '')}/secrets")
            if held:
                found.append(Finding("secrets_scope", fn, f"env:{name}", f"environment {_shown(name)} holds secrets "
                                     f"({_names(s['name'] for s in held)}) but does not limit its deployment branches to "
                                     f"the default branch {_shown(default)}", "warn",
                                     manual=f"limit the deployment branches of {_shown(name)} to the selected branch "
                                            f"`{_shown(default)}` only (Settings, Environments)"))
        if len(envs) > MAX_ENVIRONMENTS:
            found.append(Finding("secrets_scope", fn, "env:more", f"{len(envs) - MAX_ENVIRONMENTS} more environments "
                                 "were not read: the secrets check is incomplete", "warn",
                                 manual="look at the environments of this repository by hand"))
        return found

    return out + ra.per_repo(ctx, "secrets_scope", one)


# ---------------------------------------------------------------------------------------- the check

def check_git_ops(ctx) -> list:
    cfg = ctx.p.get("git_ops")
    if cfg is None:
        return []
    ra = _ra()
    out: list = []
    central = _central(ctx, cfg)
    bad = [k for k, ok in (("repo", re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$", central)),
                           ("workflow", re.match(r"^[A-Za-z0-9._-]+\.ya?ml$", cfg.get("workflow", DEFAULT_WORKFLOW)))) if not ok]
    if bad:
        return [ra.Finding("git-ops-workflow", ctx.org, "policy", f"git_ops.{bad[0]} in the policy is not a valid value, "
                           "so the central repository is not checked", "warn", manual="correct it in the policy")] + secrets_scope(ctx)
    try:
        out += check_central(ctx, cfg)
    except ra.ApiError as exc:
        out.append(ra.failure("git-ops-workflow", _central(ctx, cfg), exc))
    return out + secrets_scope(ctx)
