"""tiny_app shaped for one command's documented stop: the outcome is known without GitHub, a board or a model
judgement, so the task checks the command still reads the profile and stops where its playbook says.

`build(dest, command=...)`:
- `land`: no `git.bot_login`, so land stops with the missing-key message.
- `deps`: no `deps` block, so deps stops with the missing-key message.
- `upstream`: an `upstream` block, but no version file, so the sync stops and asks for the file.
- `docs`: a docs index that misses one doc (`docs/sync.md`); `docs check` reports it and changes nothing.
- `board`: no board variables; the board check prints the setup text.
- `implement`: a plan on `plan/tags` whose manifest has a dependency cycle; implement must stop before it
  creates the feature branch.
- `migrate`: a claude-toolkit era profile in `.claude/toolkit.yaml` (model names, `models.planner`, no
  `tld.version`); `migrate --dry-run` shows the plan and changes nothing.
No real project names, no secrets, no network.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import commit_all, init_repo, tiny_app
from evals.harness.common import git

REPO = "example-org/notes-demo"
PLAN_PATH = "docs/tags-plan.md"
PLAN_URL = f"https://github.com/{REPO}/blob/plan/tags/{PLAN_PATH}"
CYCLE_MANIFEST = {
    "plan_slug": "tags", "feature_branch": "feature/tags",
    "phases": [
        {"id": "p1-store", "title": "Tags in the store", "depends_on": ["p2-cli"], "complexity": "S",
         "touches": ["notes/store.py"], "brief": "1. Add tags to a note.",
         "acceptance": ["`python3 -m unittest discover -s tests -q`"]},
        {"id": "p2-cli", "title": "Tag filter", "depends_on": ["p1-store"], "complexity": "S",
         "touches": ["notes/cli.py"], "brief": "1. Add `list --tag`.",
         "acceptance": ["`python3 -m unittest discover -s tests -q`"]},
    ],
}


def _profile(extra: str = "", docs_index: bool = False) -> str:
    text = tiny_app.PROFILE
    if docs_index:
        text = text.replace("  plan_dir: docs/\n", "  plan_dir: docs/\n  index: docs/README.md\n")
    return text + extra


def build(dest: Path, command: str = "land") -> dict:
    files = dict(tiny_app.FILES)
    expected: dict = {"main_branch": "main"}
    if command == "land":
        files[".tld/toolkit.yaml"] = _profile()
        expected["stop_message"] = "toolkit.yaml: missing required key 'git.bot_login'"
    elif command == "deps":
        files[".tld/toolkit.yaml"] = _profile()
        expected["stop_message"] = "missing required key 'deps.cooldown_days'"
    elif command == "upstream":
        files[".tld/toolkit.yaml"] = _profile(
            "\nupstream:\n  repo: example-org/notes-upstream\n  tag_pattern: '^v[0-9]+\\.[0-9]+\\.[0-9]+$'\n"
            "  version_file: UPSTREAM_VERSION\n")
        expected["stop_message"] = "UPSTREAM_VERSION"
    elif command == "docs":
        files[".tld/toolkit.yaml"] = _profile(docs_index=True)
        files["CLAUDE.md"] = "Read [docs/README.md](docs/README.md) first.\n"
        files["docs/README.md"] = ("# Docs index\n\n| Doc | Read it when |\n|---|---|\n"
                                   "| [design.md](design.md) | you change the store or the CLI |\n")
        files["docs/sync.md"] = "# Sync\n\nHow notes are synced.\n"
        expected["stop_message"] = "docs/sync.md"
    elif command == "board":
        files[".tld/toolkit.yaml"] = _profile()
        expected["stop_message"] = ["TLD_BOARD_URL", "TLD_BOARD_TOKEN"]
    elif command == "implement":
        files[".tld/toolkit.yaml"] = _profile()
    elif command == "migrate":
        legacy = _profile().split("\n\n", 1)[1]  # without the tld block
        files.pop(".tld/toolkit.yaml", None)
        files[".claude/toolkit.yaml"] = legacy + "\nmodels:\n  planner: opus\n  worker: sonnet\n"
        expected["stop_message"] = [".tld/toolkit.yaml", "models.planner"]
    else:
        raise ValueError(f"no fixture for command {command!r}")
    init_repo(dest, files)
    if command == "implement":
        git("checkout", "-q", "-b", "plan/tags", cwd=dest)
        plan = ("# Plan: tags\n\n## Goal\n\nTags on notes.\n\n## Implementation manifest\n\n```yaml\n"
                + yaml.safe_dump(CYCLE_MANIFEST, sort_keys=False) + "```\n")
        (dest / PLAN_PATH).parent.mkdir(parents=True, exist_ok=True)
        (dest / PLAN_PATH).write_text(plan)
        commit_all(dest, "plan: tags")
        git("checkout", "-q", "main", cwd=dest)
        expected.update(stop_message="dependency cycle", plan_url=PLAN_URL)
    return expected
