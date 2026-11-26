"""The built-in defaults table and `apply` (plan 90, sections 3.1 and 3.13)."""
import json

from conftest import TLD
from tld.profile import defaults as d


def env(files=(), text=None, **kw):
    files = set(files)
    texts = dict(text or {})
    return d.Env(exists=lambda p: p in files, read=lambda p: texts.get(p), **kw)


def test_static_defaults():
    out, src = d.apply({}, env())
    assert out["git"] == {"branch_pattern": "<type>/<kebab-case>", "branch_types": ["feature", "fix", "chore"],
                          "merge_style": "merge-commit"}
    assert out["land"] == {"max_prs": 10} and out["stacks"] == [] and out["docs"]["must_read"] == []
    assert out["models"] == {"worker": "standard", "reviewer": "strong"}
    assert out["hooks"]["dod_gate"] == {"enabled": True, "max_attempts": 3}
    assert out["hooks"]["plan_gate"] == {"enabled": True} and out["hooks"]["board_gate"] == {"enabled": True}
    assert out["hooks"]["protect_paths"] == [".env", ".env.*", "*.lock", "package-lock.json", "go.sum"]
    assert out["hooks"]["disable"] == [] and out["hooks"]["protect_paths_allow"] == []
    assert src["land.max_prs"] == "default"
    written, src = d.apply({"git": {"merge_style": "squash"}, "land": {"max_prs": 3}}, env())
    assert written["git"]["merge_style"] == "squash" and written["land"]["max_prs"] == 3
    assert src["git.merge_style"] == "repo"


def test_static_defaults_equal_the_schema_defaults():
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    assert d.STATIC["models.worker"] == schema["properties"]["models"]["properties"]["worker"]["default"]
    assert d.STATIC["models.reviewer"] == schema["properties"]["models"]["properties"]["reviewer"]["default"]


def test_schema_defaults_equal_the_table():
    """Every `default` of the schema is the table's value (the plan directory's schema default is the
    existing-directory case, written with a trailing slash)."""
    schema = json.loads((TLD / "schema" / "profile.schema.json").read_text())
    found = {}

    def walk(node, path):
        for key, sub in node.get("properties", {}).items():
            if "default" in sub:
                found[f"{path}{key}"] = sub["default"]
            walk(sub, f"{path}{key}.")

    walk(schema, "")
    assert found == {"docs.plan_dir": "docs/plans/", "models.worker": "standard", "models.reviewer": "strong"}
    out, _ = d.apply({}, env(files=["docs/plans"]))
    assert out["docs"]["plan_dir"] == found["docs.plan_dir"].rstrip("/")
    for key in ("models.worker", "models.reviewer"):
        assert d.STATIC[key] == found[key]


def test_git_ops_repository():
    out, src = d.apply({}, env(origin_owner="acme"))
    assert out["git_ops"] == {"repo": "acme/git-ops", "workflow": "tld-git-ops.yml"}
    assert src["git_ops.repo"] == "default"
    out, _ = d.apply({"git_ops": {"repo": "o/x"}}, env(origin_owner="acme"))
    assert out["git_ops"]["repo"] == "o/x"
    out, _ = d.apply({}, env())
    assert "git_ops" not in out
    out, src = d.apply({}, env(main_branch="trunk"))
    assert out["git"]["main_branch"] == "trunk" and src["git.main_branch"] == "detected (origin/HEAD)"


def test_plan_directory_of_an_existing_repository():
    out, _ = d.apply({}, env(files=["docs/plans"]))
    assert out["docs"]["plan_dir"] == "docs/plans"
    out, _ = d.apply({}, env())
    assert out["docs"]["plan_dir"] == "docs"
    out, _ = d.apply({"docs": {"plan_dir": "plans"}}, env(files=["docs/plans"]))
    assert out["docs"]["plan_dir"] == "plans"


def test_empty_section_turns_the_feature_on():
    out, _ = d.apply({"deps": None, "spec": {}, "sysml": None, "release": {"version_files": []}}, env())
    assert out["deps"] == {"cooldown_days": 3, "time_budget_minutes": 90}
    assert out["spec"] == {"version": "2.1.0"} and out["sysml"] == {"subset": 1}
    assert out["release"] == {"version_files": [], "workflow": "tld-release.yml"}
    out, _ = d.apply({}, env())
    assert not {"deps", "spec", "sysml", "release"} & set(out)
    out, _ = d.apply({"deps": {"cooldown_days": 7}}, env())
    assert out["deps"] == {"cooldown_days": 7, "time_budget_minutes": 90}


def test_file_checked_defaults():
    files = ["docs/README.md", "docs/adr", "CHANGELOG.md", ".tld/admin-policy.yaml"]
    text = {"CONTRIBUTING.md": "x\n## Decisions, plans and ADRs\ny\n"}
    out, src = d.apply({}, env(files=files, text=text))
    docs = out["docs"]
    assert docs["index"] == "docs/README.md" and src["docs.index"] == "default (docs/README.md exists)"
    assert (docs["adr_dir"], docs["adr_index"]) == ("docs/adr", "docs/adr/README.md")
    assert docs["adr_bar"] == "CONTRIBUTING.md#decisions-plans-and-adrs"
    assert docs["changelog"] == {"file": "CHANGELOG.md", "section": "## [Unreleased]", "policy": "unreleased"}
    assert out["admin"]["policy"] == ".tld/admin-policy.yaml"
    out, _ = d.apply({}, env(files=["docs/adr"], text={"CONTRIBUTING.md": "no heading"}))
    assert "adr_bar" not in out["docs"]
    out, _ = d.apply({"docs": {"adr_dir": "decisions"}}, env(files=["docs/adr"], text=text))
    assert out["docs"]["adr_dir"] == "decisions" and "adr_bar" not in out["docs"]
    out, _ = d.apply({}, env())
    assert not {"index", "adr_dir", "changelog", "website"} & set(out["docs"]) and "admin" not in out


def test_website_default():
    out, _ = d.apply({}, env(files=["scripts/build_site.py"]))
    assert out["docs"]["website"] == {"dir": ".", "build": "python3 scripts/build_site.py --out _site",
                                      "links": "python3 -m pytest tests/unit/test_website_links.py -q"}


def test_turned_off_with_false():
    files = ["docs/README.md", "docs/adr", "CHANGELOG.md", "scripts/build_site.py", ".tld/admin-policy.yaml"]
    profile = {"docs": {"index": False, "adr_dir": False, "changelog": False, "website": False},
               "admin": False, "git_ops": False, "land": {"max_prs": False}}
    out, src = d.apply(profile, env(files=files, origin_owner="acme"))
    assert out["docs"].keys() == {"must_read", "plan_dir"}
    assert "admin" not in out and "git_ops" not in out and "max_prs" not in out["land"]
    assert src["admin"] == "off (false)" and src["docs.index"] == "off (false)"


def test_plan_dir_without_root():
    out, src = d.apply({}, d.Env())
    assert out["docs"]["plan_dir"] == "docs"
    assert "index" not in out["docs"] and src["docs.index"] == "not applied (no root)"


def test_off_switch_stops_dependent_defaults():
    files = ["docs/adr", ".tld/admin-policy.yaml", "CHANGELOG.md"]
    text = {"CONTRIBUTING.md": "## Decisions, plans and ADRs"}
    out, _ = d.apply({"admin": False}, env(files=files))
    assert "admin" not in out
    out, _ = d.apply({"docs": {"adr_dir": False}}, env(files=files, text=text))
    assert not {"adr_dir", "adr_index", "adr_bar"} & set(out["docs"]) and "changelog" in out["docs"]
    out, _ = d.apply({"docs": {"changelog": False}}, env(files=files))
    assert "changelog" not in out["docs"]
