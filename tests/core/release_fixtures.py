"""Cases shared by the tests of `tld ops release-check` and of the tld-release template's green step.

Each case: (id, check_runs, state, total, self_names, expected_exit). `state` None means no combined status is given.
"""


def run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


CASES = [
    ("all-success", [run("test"), run("lint")], None, None, [], 0),
    ("neutral-only", [run("a", conclusion="neutral")], None, None, [], 0),
    ("skipped-only", [run("a", conclusion="skipped")], None, None, [], 0),
    ("conclusion-none", [run("test"), run("a", conclusion=None)], None, None, [], 1),
    ("in-progress", [run("test"), run("slow", "in_progress", None)], None, None, [], 3),
    ("failure", [run("test"), run("lint", conclusion="failure")], None, None, [], 1),
    ("own-run-left-out", [run("test"), run("tld-release", conclusion="failure")], None, None, ["tld-release"], 0),
    ("status-pending-none", [run("test")], "pending", 0, [], 0),
    ("status-pending-one", [run("test")], "pending", 1, [], 3),
    ("status-failure", [run("test")], "failure", 1, [], 1),
    ("status-error", [run("test")], "error", 1, [], 1),
    ("status-success", [run("test")], "success", 1, [], 0),
    ("empty", [], None, None, [], 0),
]
