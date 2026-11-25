"""Merge rules, guarded keys and the trusted clamp (plan 90, sections 3.4 and 3.13)."""
import copy

from tld.profile import merge as m

LABEL = "acme/.github/tld/base.yaml@abcdef1"


def role(name, at, **kw):
    return {"role": name, "at": list(at), **kw}


def merged_roles(base_roles, repo_roles, allow=(), disable=None):
    repo = {"roles": {"required": repo_roles}}
    if disable:
        repo["roles"]["disable"] = disable
    return m.merge({"roles": {"required": base_roles}}, repo, list(allow))[0]["roles"]


def test_repository_overrides_a_scalar():
    merged, src = m.merge({"git": {"bot_login": "bot", "codeowners": ["a"]}}, {"git": {"bot_login": "me"}})
    assert merged["git"] == {"bot_login": "me", "codeowners": ["a"]}
    assert src["git.bot_login"] == "repo" and src["git.codeowners"] == "base"


def test_lists_replace():
    merged, _ = m.merge({"git": {"codeowners": ["a", "b"]}}, {"git": {"codeowners": ["c"]}})
    assert merged["git"]["codeowners"] == ["c"]


def test_required_roles_merge_by_role():
    r = merged_roles([role("security-reviewer", ["implement_phase"], blocking=True, when=["a"])],
                     [role("security-reviewer", ["dod"], when=["b"]), role("tech-writer", ["review"])])
    assert r["required"][0] == role("security-reviewer", ["implement_phase", "dod"], blocking=True,
                                    when=["a", "b"])
    assert r["required"][1]["role"] == "tech-writer"


def test_manual_rows_append():
    merged, _ = m.merge({"verify": {"dod_manual": ["x", "y"]}}, {"verify": {"dod_manual": ["y", "z"]}})
    assert merged["verify"]["dod_manual"] == ["x", "y", "z"]


def test_hook_disable_refused():
    errs = m.guarded_errors({}, {"hooks": {"disable": ["plan-gate"]}}, [], LABEL)
    assert errs == [f"toolkit.yaml: 'hooks.disable': 'plan-gate' is switched on by the base {LABEL}; the "
                    "repository cannot switch it off unless the base lists 'hooks.disable.plan-gate' in "
                    "tld.allow_override"]


def test_weaker_posture_refused():
    errs = m.guarded_errors({"roles": {"posture": {"security": "critical"}}},
                            {"roles": {"posture": {"security": "standard"}}}, [], LABEL)
    assert errs == ["toolkit.yaml: 'roles.posture.security': 'standard' is weaker than the base's 'critical' "
                    "(critical > standard > low); allowed only when the base lists 'roles.posture.security' "
                    "in tld.allow_override"]


def test_required_role_dropped():
    floor = {"roles": {"required": [role("reflektor", ["dod", "review"])]}}
    errs = m.guarded_errors(floor, {"roles": {"required": floor["roles"]["required"], "disable": ["reflektor"]}},
                            [], LABEL)
    assert errs == [f"toolkit.yaml: 'roles.disable': 'reflektor' is required by the base {LABEL} at dod, review; "
                    "allowed only when the base lists 'roles.required.reflektor' in tld.allow_override"]


def test_protect_list_widened():
    floor = {"hooks": {"protect_paths": [".env", "x"], "protect_paths_allow": []}}
    errs = m.guarded_errors(floor, {"hooks": {"protect_paths": [".env"], "protect_paths_allow": ["y"]}}, [], LABEL)
    assert len(errs) == 2
    assert errs[0].startswith(f"toolkit.yaml: 'hooks.protect_paths': leaves out 'x', which the base {LABEL} protects")
    assert errs[1].startswith(f"toolkit.yaml: 'hooks.protect_paths_allow': 'y' widens what the base {LABEL}")


def test_gate_switched_off():
    errs = m.guarded_errors({"hooks": {"plan_gate": {"enabled": True}}},
                            {"hooks": {"plan_gate": {"enabled": False}}}, [], LABEL)
    assert errs == ["toolkit.yaml: 'hooks.plan_gate.enabled': false switches off a gate the base turns on; "
                    "allowed only when the base lists 'hooks.plan_gate.enabled' in tld.allow_override"]


def test_allowed_by_the_base():
    floor = {"hooks": {"plan_gate": {"enabled": True}, "protect_paths": ["x"]},
             "roles": {"posture": {"security": "critical"}, "required": [role("reflektor", ["dod"])]}}
    merged = {"hooks": {"disable": ["secret-scan"], "plan_gate": {"enabled": False}, "protect_paths": [],
                        "protect_paths_allow": ["y"]},
              "roles": {"posture": {"security": "low"}, "disable": ["reflektor"]}}
    allow = ["hooks.disable.secret-scan", "hooks.plan_gate.enabled", "hooks.protect_paths",
             "hooks.protect_paths_allow", "roles.posture.security", "roles.required.reflektor"]
    assert m.guarded_errors(floor, merged, allow, LABEL) == []


def test_strengthening_allowed():
    floor = {"roles": {"posture": {"security": "standard"}}, "hooks": {"protect_paths": ["a"]}}
    merged = {"roles": {"posture": {"security": "critical"}}, "hooks": {"protect_paths": ["a", "b"],
                                                                         "plan_gate": {"enabled": True}}}
    assert m.guarded_errors(floor, merged, [], LABEL) == []


def test_no_extends_refuses_nothing():
    # No base means no floor: the caller does not run guarded_errors, and an empty floor of an
    # unguarded profile refuses nothing that is not below tld's own defaults.
    assert m.guarded_errors({}, {"hooks": {"protect_paths": [".env", ".env.*", "*.lock", "package-lock.json",
                                                              "go.sum", "more"]}}, [], LABEL) == []


def test_protect_paths_floor_is_tlds_default_list_when_base_omits_it():
    errs = m.guarded_errors({}, {"hooks": {"protect_paths": ["*.lock"]}}, [], LABEL)
    assert errs[0] == ("toolkit.yaml: 'hooks.protect_paths': leaves out '.env', which tld's default list "
                       "protects; list it, or have the base list 'hooks.protect_paths' in tld.allow_override")


def test_repo_cannot_unset_base_blocking():
    r = merged_roles([role("security-reviewer", ["dod"], blocking=True)],
                     [role("security-reviewer", ["dod"], blocking=False)])
    assert r["required"][0]["blocking"] is True


def test_repo_when_on_base_entry_without_when_is_ignored_with_warning():
    merged, _, warnings = m.merge_with_warnings({"roles": {"required": [role("reflektor", ["dod"])]}},
                                                {"roles": {"required": [role("reflektor", ["dod"], when=["a"])]}})
    assert "when" not in merged["roles"]["required"][0]
    assert warnings == ["'roles.required[0].when': no effect, the base runs reflektor on every diff"]


def test_override_re_rejects_unknown_names():
    ok = ["hooks.disable.plan-gate", "hooks.protect_paths", "hooks.protect_paths_allow", "hooks.dod_gate.enabled",
          "hooks.plan_gate.enabled", "hooks.board_gate.enabled", "roles.posture.security",
          "roles.required.reflektor"]
    bad = ["hooks.protect_paths\n", "roles.posture.security\n", "hooks.disable.nope", "hooks.disable", "hooks.dod_gate.max_attempts", "verify.fast", "roles.required",
           "roles.required.", "hooks.protect_paths.x", "xhooks.protect_paths"]
    assert all(m.OVERRIDE_RE.match(x) for x in ok)
    assert not any(m.OVERRIDE_RE.match(x) for x in bad)


def test_allowed_role_drop_removes_the_base_entry():
    base = [role("reflektor", ["dod"]), role("test-architect", ["make_plan"])]
    r = merged_roles(base, [], allow=["roles.required.reflektor"], disable=["reflektor"])
    assert [e["role"] for e in r["required"]] == ["test-architect"]
    assert r["disable"] == ["reflektor"]
    r = merged_roles(base, [], disable=["reflektor"])
    assert [e["role"] for e in r["required"]] == ["reflektor", "test-architect"]


# ---- clamp

def test_clamp_does_not_add_a_branch_disable():
    out, w = m.clamp({"hooks": {"disable": []}}, {"hooks": {"disable": ["plan-gate"]}}, "main")
    assert out["hooks"]["disable"] == [] and len(w) == 1


def test_clamp_gate_false_on_branch_stays_on():
    out, w = m.clamp({"hooks": {"dod_gate": {"enabled": True}}},
                     {"hooks": {"dod_gate": {"enabled": False, "max_attempts": 2}}}, "main")
    assert out["hooks"]["dod_gate"] == {"enabled": True, "max_attempts": 2} and len(w) == 1


def test_clamp_posture_takes_higher_rank():
    out, _ = m.clamp({"roles": {"posture": {"security": "critical"}}},
                     {"roles": {"posture": {"security": "low"}}}, "main")
    assert out["roles"]["posture"]["security"] == "critical"
    out, w = m.clamp({"roles": {"posture": {"security": "low"}}},
                     {"roles": {"posture": {"security": "critical"}}}, "main")
    assert out["roles"]["posture"]["security"] == "critical" and w == []


def test_clamp_protect_paths_union():
    out, w = m.clamp({"hooks": {"protect_paths": ["a", "b"]}}, {"hooks": {"protect_paths": ["b", "c"]}}, "main")
    assert out["hooks"]["protect_paths"] == ["a", "b", "c"] and len(w) == 1


def test_clamp_protect_paths_allow_intersection():
    out, w = m.clamp({"hooks": {"protect_paths_allow": ["a"]}}, {"hooks": {"protect_paths_allow": ["a", "z"]}},
                     "main")
    assert out["hooks"]["protect_paths_allow"] == ["a"] and len(w) == 1


def test_clamp_keeps_floor_required_role_blocking_and_points():
    trusted = {"roles": {"required": [role("security-reviewer", ["implement_final", "dod"], blocking=True)]}}
    branch = {"roles": {"required": [role("security-reviewer", ["dod"])]}}
    out, w = m.clamp(trusted, branch, "main")
    assert out["roles"]["required"] == [role("security-reviewer", ["dod", "implement_final"], blocking=True)]
    assert len(w) == 1
    out, w = m.clamp(trusted, {"roles": {}}, "main")
    assert out["roles"]["required"] == trusted["roles"]["required"] and len(w) == 1


def test_clamp_drops_roles_disable_of_a_floor_role():
    trusted = {"roles": {"required": [role("reflektor", ["dod"])]}}
    out, w = m.clamp(trusted, {"roles": {"disable": ["reflektor", "debugger"]}}, "main")
    assert out["roles"]["disable"] == ["debugger"]
    assert out["roles"]["required"] == trusted["roles"]["required"]
    assert any("'roles.disable'" in x for x in w)


def test_clamp_warning_text():
    _, w = m.clamp({"hooks": {"plan_gate": {"enabled": True}}}, {"hooks": {"plan_gate": {"enabled": False}}},
                   "develop")
    assert w == ["toolkit.yaml: warning: 'hooks.plan_gate.enabled' is weaker here than on develop (the remote "
                 "default branch); the develop value applies until this change is merged"]


def test_clamp_leaves_inputs_alone_and_equal_profiles_quiet():
    trusted = {"hooks": {"disable": [], "protect_paths": ["a"], "plan_gate": {"enabled": True}}}
    branch = copy.deepcopy(trusted)
    out, w = m.clamp(trusted, branch, "main")
    assert out == trusted and w == [] and branch == trusted


def test_clamp_without_a_trusted_posture_means_standard():
    out, w = m.clamp({}, {"roles": {"posture": {"security": "low"}}}, "main")
    assert out["roles"]["posture"]["security"] == "standard" and len(w) == 1
    out, w = m.clamp({}, {"roles": {"posture": {"security": "critical"}}}, "main")
    assert out["roles"]["posture"]["security"] == "critical" and w == []
    out, w = m.clamp({}, {}, "main")
    assert out == {} and w == []


def test_unknown_posture_is_named_not_a_key_error():
    errs = m.guarded_errors({}, {"roles": {"posture": {"security": "high"}}}, [], LABEL)
    assert errs == ["toolkit.yaml: 'roles.posture.security': must be one of critical, standard, low (got 'high')"]
    out, w = m.clamp({"roles": {"posture": {"security": "weird"}}}, {"roles": {"posture": {"security": "standard"}}},
                     "main")
    assert out["roles"]["posture"]["security"] == "critical" and len(w) == 1


def test_builtin_protect_list_is_the_defaults_copy():
    from tld.profile import defaults
    assert m.BUILTIN_PROTECT_PATHS == defaults.STATIC["hooks.protect_paths"]
