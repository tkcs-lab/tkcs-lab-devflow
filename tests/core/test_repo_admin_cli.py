"""repo_admin.py command line: validate-policy kinds and resolution, load_policy with extends, latest-pin, the audit header."""
import json

import pytest
import yaml

import test_repo_admin as fake_mod
from test_repo_admin import Fake, add_repo, repo
from test_repo_admin_extends import BASE_PATH, BASE_PIN, ORG_PATH, ORG_PIN, SHA_A, SHA_B, run, serve, tag_world, world


@pytest.fixture(autouse=True)
def _bind(ra):
    fake_mod.ApiErr = ra.ApiError


@pytest.fixture
def cmd(ra, tmp_path, monkeypatch, capsys):
    """cmd(argv, fake=None, doc=None) writes `doc` (text, or a dict as YAML) to policy.yaml, runs ra.main, returns (code, out, err)."""
    def go(argv, fake=None, doc=None, name="policy.yaml"):
        path = tmp_path / name
        if doc is not None:
            path.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc))
        monkeypatch.setattr(ra, "_client", lambda: fake if fake is not None else world())
        capsys.readouterr()
        code = ra.main([argv[0], *[str(path) if a == "{file}" else a for a in argv[1:]]])
        out, err = capsys.readouterr()
        return code, out, err
    return go


def test_small_policy_resolves_on_the_command_line(cmd, tmp_path):
    doc = run(BASE_PIN, ORG_PIN)
    code, out, err = cmd(["validate-policy", "{file}"], doc=doc)
    assert code == 0 and err == "" and out.startswith("policy: OK (") and out.endswith("policy.yaml)\n")
    code, out, err = cmd(["validate-policy", "{file}", "--resolved"], doc=doc)
    data = yaml.safe_load(out)
    assert code == 0 and data["org"] == "acme" and data["members"] == {"max_owners": 3}
    assert data["release"] == {"environment": "other"} and "extends" not in data
    assert not [k for k in data if k.startswith("_")]


def test_resolved_view(cmd):
    code, out, _ = cmd(["validate-policy", "{file}", "--explain"], doc=run(BASE_PIN, ORG_PIN))
    lines = out.splitlines()
    assert code == 0 and lines == sorted(lines, key=lambda l: l.split(" = ")[0])
    assert f'rulesets.tags = true  # base acme/.github/{BASE_PATH}@aaaaaaa' in lines
    assert f'release.environment = "other"  # base acme/git-ops/{ORG_PATH}@bbbbbbb' in lines
    assert 'org = "acme"  # run' in lines


def test_explain_names_the_override_source(cmd, tmp_path):
    org = tmp_path / "org.yaml"
    org.write_text(yaml.safe_dump(run(BASE_PIN, ORG_PIN, repo_settings={"allow_auto_merge": True})))
    override = {"repo_settings": {"allow_auto_merge": False}, "workflow_params": {"release": {"tag_prefix": "v"}}}
    code, out, err = cmd(["validate-policy", "{file}", "--explain", "--org-policy", str(org), "--repo-name", "app"],
                         doc=override, name="override.yaml")
    assert code == 0, err
    lines = out.splitlines()
    assert 'repo_settings.allow_auto_merge = false  # override app' in lines
    assert 'workflow_params.release.tag_prefix = "v"  # override app' in lines
    assert f'release.environment = "other"  # base acme/git-ops/{ORG_PATH}@bbbbbbb' in lines
    assert err == "policy: OK (" + str(tmp_path / "override.yaml") + ", repository override)\n"
    code, out, _ = cmd(["validate-policy", "{file}", "--resolved", "--org-policy", str(org), "--repo-name", "app"],
                       doc=override, name="override.yaml")
    assert yaml.safe_load(out)["repo_settings"] == {"allow_auto_merge": False}


def test_validate_policy_exits_1_on_a_bad_pin_or_an_org_key_in_an_override(cmd):
    code, out, err = cmd(["validate-policy", "{file}"], doc=run(f"acme/.github/{BASE_PATH}@v1"))
    assert code == 1 and out == ""
    assert err.startswith("policy: 'extends[0]'") and "latest-pin" in err
    fake = world()
    fake.routes[("GET", f"/repos/acme/.github/compare/main...{SHA_A}")] = {"status": "ahead"}
    code, _, err = cmd(["validate-policy", "{file}"], fake=fake, doc=run(BASE_PIN))
    assert code == 1 and "is not on the default branch" in err
    code, _, err = cmd(["validate-policy", "{file}"], doc={"labels": {"delete_unused": False}})
    assert code == 1 and "'labels' is organisation-level" in err


def test_validate_policy_checks_the_extends_form(ra):
    assert ra.validate_policy({"org": "acme", "extends": [f"acme/.github/{BASE_PATH}@v1"]}) != []
    assert ra.validate_policy({"org": "acme", "extends": "nonsense"})[0].startswith("'extends[0]'")
    assert ra.validate_policy({"org": "acme", "extends": [BASE_PIN, BASE_PIN]}) == ["'extends': acme/.github/" + BASE_PATH + " is listed twice"]
    assert ra.validate_policy({"org": "acme", "extends": [BASE_PIN]}) == []
    assert ra.validate_policy({"org": "acme", "extends": []}) == []


def test_validate_kinds_and_ok_lines(cmd, tmp_path):
    f = str(tmp_path / "policy.yaml")
    assert cmd(["validate-policy", "{file}"], doc={"org": "acme"})[1] == f"policy: OK ({f})\n"
    assert cmd(["validate-policy", "{file}"], doc={"security": {"secret_scanning": True}})[1] == f"policy: OK ({f}, repository override)\n"
    assert cmd(["validate-policy", "{file}", "--kind", "base"], doc={"security": {"secret_scanning": True}})[1] == f"policy: OK ({f}, base)\n"
    code, _, err = cmd(["validate-policy", "{file}", "--kind", "run"], doc={"security": {"secret_scanning": True}})
    assert code == 1 and "missing required key 'org'" in err
    code, _, err = cmd(["validate-policy", "{file}", "--kind", "base"], doc={"org": "acme"})
    assert code == 1 and "is set only in the policy file you run" in err
    assert cmd(["validate-policy", "{file}", "--kind", "base", "--public"], doc={"members": {"max_owners": 2}})[0] == 1


def test_base_kind_runs_the_shape_check(cmd):
    secret = "gh" + "p_" + "A1b2C3d4E5" * 3 + "abcdef"
    for kind in ("base", "override"):
        code, out, err = cmd(["validate-policy", "{file}", "--kind", kind], doc=f"security: {{secret_scanning: true}}\n# {secret}\n")
        assert code == 1 and "refused: line 2 looks like" in err and secret not in out + err
    code, _, err = cmd(["validate-policy", "{file}", "--kind", "base"], doc="a: &x 1\nb: *x\n")
    assert code == 1 and "uses YAML anchors or aliases" in err
    code, _, err = cmd(["validate-policy", "{file}"], doc="security: &x {secret_scanning: true}\nactions: *x\n")
    assert code == 1 and "anchors" in err  # auto picks override, which is shape-checked


def test_public_flag_needs_base_kind(cmd):
    code, _, err = cmd(["validate-policy", "{file}", "--public"], doc={"org": "acme"})
    assert code == 2 and err == "validate-policy: --public needs --kind base\n"
    code, _, err = cmd(["validate-policy", "{file}", "--kind", "override", "--public"], doc={})
    assert code == 2
    code, _, err = cmd(["validate-policy", "{file}", "--org-policy", "x.yaml"], doc={"org": "acme"})
    assert code == 2 and err == "validate-policy: --org-policy needs --repo-name\n"


def test_offline_does_not_fetch(cmd):
    fake = world()
    code, out, _ = cmd(["validate-policy", "{file}", "--offline"], fake=fake, doc=run(BASE_PIN, ORG_PIN))
    assert code == 0 and out.startswith("policy: OK (") and fake.reads == []
    for flag in ("--resolved", "--explain"):  # the unresolved file is not the effective policy
        code, out, err = cmd(["validate-policy", "{file}", "--offline", flag], fake=fake, doc=run(BASE_PIN))
        assert code == 1 and out == "" and "bases are not fetched" in err and fake.reads == []
    code, _, err = cmd(["validate-policy", "{file}", "--offline"], fake=fake, doc=run(f"acme/.github/{BASE_PATH}@v1"))
    assert code == 1 and "latest-pin" in err and fake.reads == []


def test_load_policy_refuses_an_override_file(ra, tmp_path):
    f = tmp_path / "override.yaml"
    f.write_text("security: {secret_scanning: true}\n")
    with pytest.raises(SystemExit) as exc:
        ra.load_policy(str(f))
    assert str(exc.value) == (f"repo_admin: '{f}' is a repository override file (it has no 'org'); "
                              "run the audit with the organisation's policy file")
    f.write_text("{}\n")
    with pytest.raises(SystemExit, match="missing required key 'org'"):
        ra.load_policy(str(f))


def test_load_policy_without_extends_is_unchanged(ra, tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("org: acme\nextends: []\nrepo_settings: {allow_auto_merge: true}\n")
    fake = Fake({})
    pol = ra.load_policy(str(f), fake)
    assert pol == {"org": "acme", "extends": [], "repo_settings": {"allow_auto_merge": True}, "_dir": str(tmp_path)} and fake.reads == []
    f.write_text("org: acme\nextends: [nonsense]\n")
    with pytest.raises(SystemExit, match=r"^policy: 'extends\[0\]': must be"):
        ra.load_policy(str(f), fake)
    f.write_text(yaml.safe_dump(run(BASE_PIN, ORG_PIN)))
    pol = ra.load_policy(str(f), world())
    assert pol["_inherited"] is True and pol["members"] == {"max_owners": 3} and pol["_dir"] == str(tmp_path)
    broken = world()
    broken.routes[("GET", f"/repos/acme/.github/compare/main...{SHA_A}")] = {"status": "diverged"}
    with pytest.raises(SystemExit, match="policy: 'extends\\[0\\]': aaaaaaa is not on the default branch"):
        ra.load_policy(str(f), broken)


def test_latest_pin_command_prints_json(cmd):
    fake = tag_world([("v1", "1" * 40)], with_file=["1" * 40])
    code, out, _ = cmd(["latest-pin", f"acme/.github/{BASE_PATH}"], fake=fake)
    assert code == 0 and json.loads(out) == {"sha": "1" * 40, "tag": "v1"}
    code, out, err = cmd(["latest-pin", "nonsense"], fake=fake)
    assert code == 1 and out == "" and err == "latest-pin: 'nonsense' must be <owner>/<repo>/<path>\n"


def test_latest_pin_missing_file_exits_1(cmd):
    fake = tag_world([("v1", "1" * 40)], with_file=[], head_has_file=False)
    code, out, err = cmd(["latest-pin", f"acme/.github/{BASE_PATH}"], fake=fake)
    assert code == 1 and out == "" and err == f"latest-pin: {BASE_PATH} does not exist in acme/.github\n"


def test_audit_header_names_the_extends(ra, tmp_path, monkeypatch, capsys):
    fake = world()
    fake.routes[("GET", "/orgs/acme/repos")] = [repo("app")]
    fake.routes[("GET", "/orgs/acme")] = {"public_repos": 1, "total_private_repos": 0}
    add_repo(fake.routes, "app", {})
    monkeypatch.setattr(ra, "_client", lambda: fake)
    f = tmp_path / "p.yaml"
    f.write_text(yaml.safe_dump(run(BASE_PIN, ORG_PIN, repo_settings={"allow_auto_merge": True})))
    ra.main(["audit", "--policy", str(f), "--check", "repo"])
    out = capsys.readouterr().out
    labels = f"acme/.github/{BASE_PATH}@aaaaaaa, acme/git-ops/{ORG_PATH}@bbbbbbb"
    assert f"\nExtends: {labels}.\n" in out
    assert out.index("repositories in scope") < out.index("Extends:")
    ra.main(["audit", "--policy", str(f), "--check", "repo", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["extends"] == labels.split(", ")
    f.write_text(yaml.safe_dump({"org": "acme", "repo_settings": {"allow_auto_merge": True}}))
    ra.main(["audit", "--policy", str(f), "--check", "repo"])
    assert "Extends:" not in capsys.readouterr().out
    ra.main(["audit", "--policy", str(f), "--check", "repo", "--format", "json"])
    assert "extends" not in json.loads(capsys.readouterr().out)


def test_fetched_text_cannot_forge_a_line_or_move_the_cursor(cmd, ra, tmp_path):
    hostile = "workflows: [{template: release, \"x\\ny: policy: OK\": 1, \"e\\e]0;PWN\\a\": 2}]\n"
    fake = world(base_text=hostile)
    code, out, err = cmd(["validate-policy", "{file}"], fake=fake, doc=run(BASE_PIN))
    assert code == 1 and out == ""
    assert "\x1b" not in err and "\x07" not in err and all(line.startswith("policy: ") for line in err.splitlines())
    f = tmp_path / "p.yaml"
    f.write_text(yaml.safe_dump(run(BASE_PIN)))
    with pytest.raises(SystemExit) as exc:
        ra.load_policy(str(f), fake)
    msg = str(exc.value)
    assert "\x1b" not in msg and all(line.startswith("policy: ") for line in msg.splitlines())


def test_offline_org_policy_with_extends_is_refused(cmd, tmp_path):
    org = tmp_path / "org.yaml"
    org.write_text(yaml.safe_dump(run(BASE_PIN)))
    code, _, err = cmd(["validate-policy", "{file}", "--resolved", "--offline", "--org-policy", str(org), "--repo-name", "app"],
                       doc={"security": {"secret_scanning": True}}, name="o.yaml")
    assert code == 1 and "bases are not fetched" in err


def test_latest_pin_turns_a_timeout_into_a_clean_error(cmd, ra, monkeypatch):
    def boom(client, source):
        raise TimeoutError("timed out")
    monkeypatch.setattr(ra.repo_admin_extends, "latest_pin", boom)
    code, out, err = cmd(["latest-pin", f"acme/.github/{BASE_PATH}"], fake=tag_world([("v1", "1" * 40)], with_file=["1" * 40]))
    assert code == 1 and out == "" and err == "latest-pin: timed out\n"
