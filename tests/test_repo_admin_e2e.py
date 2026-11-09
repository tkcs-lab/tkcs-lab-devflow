"""repo_admin.py as a subprocess, over real HTTP, against a small local server that behaves like GitHub's API."""
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from conftest import DEVFLOW

SCRIPT = DEVFLOW / "scripts" / "repo_admin.py"
TOKEN = "e2e-token-value"


class State:
    def __init__(self):
        self.requests = []  # (method, path, body, authorization)
        self.fail_with = None  # an HTTP status every request then gets
        self.repo = {"name": "app", "full_name": "acme/app", "archived": False, "fork": False, "default_branch": "main",
                     "has_wiki": True, "delete_branch_on_merge": True}
        self.labels = [{"name": f"old-{i}", "color": "ededed", "description": None} for i in range(130)] + [{"name": "bug", "color": "000000", "description": None}]
        self.files = {".archon/a.yml": "x\n", ".archon/deep/b.yml": "y\n", "README.md": "# app\n"}


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body=None, headers=None):
            raw = b"" if body is None else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def handle_any(self):
            url = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            state.requests.append((self.command, url.path, body, self.headers.get("Authorization")))
            m, p = self.command, url.path
            if state.fail_with:
                return self.reply(state.fail_with, {"message": "Server Error"})
            if m == "GET" and p == "/orgs/acme/repos":
                return self.reply(200, [state.repo])
            if m == "GET" and p == "/repos/acme/app":
                return self.reply(200, state.repo)
            if m == "PATCH" and p == "/repos/acme/app":
                state.repo.update(body)
                return self.reply(200, state.repo)
            if m == "GET" and p == "/repos/acme/app/labels":  # paginated, 100 per page
                page = int(q.get("page", 1))
                chunk = state.labels[(page - 1) * 100: page * 100]
                link = {}
                if page * 100 < len(state.labels):
                    link["Link"] = f'<http://127.0.0.1:{self.server.server_port}/repos/acme/app/labels?per_page=100&page={page + 1}>; rel="next"'
                return self.reply(200, chunk, link)
            if m == "POST" and p == "/repos/acme/app/labels":
                state.labels.append({"name": body["name"], "color": body.get("color"), "description": body.get("description")})
                return self.reply(201, body)
            if m == "PATCH" and p.startswith("/repos/acme/app/labels/"):
                return self.reply(200, body)
            if m == "DELETE" and p.startswith("/repos/acme/app/labels/"):
                return self.reply(204)
            if m == "GET" and p == "/repos/acme/app/issues":
                return self.reply(200, [])
            if m == "GET" and p == "/repos/acme/app/branches/main":
                return self.reply(200, {"commit": {"sha": "c1", "commit": {"tree": {"sha": "t1"}}}})
            if m == "GET" and p == "/repos/acme/app/git/trees/t1":
                tree = [{"path": ".archon", "type": "tree"}, {"path": ".archon/deep", "type": "tree"}]
                tree += [{"path": f, "type": "blob", "mode": "100644"} for f in state.files]
                return self.reply(200, {"tree": tree, "truncated": False})
            if m == "GET" and p.startswith("/repos/acme/app/contents/"):
                assert "raw" in self.headers["Accept"]
                return self.reply(200, state.files[p.split("/contents/", 1)[1]])
            if m == "POST" and p == "/repos/acme/app/git/trees":
                return self.reply(201, {"sha": "t2"})
            if m == "POST" and p == "/repos/acme/app/git/commits":
                return self.reply(201, {"sha": "c2"})
            if m == "POST" and p == "/repos/acme/app/git/refs":
                return self.reply(201, {})
            if m == "POST" and p == "/repos/acme/app/pulls":
                return self.reply(201, {"html_url": "https://github.com/acme/app/pull/1", "number": 1})
            if m == "GET" and p == "/user":
                return self.reply(200, {"login": "owner"})
            if m == "GET" and p == "/user/memberships/orgs/acme":
                return self.reply(200, {"role": "admin"})
            return self.reply(404, {"message": "Not Found"})

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = handle_any

    return H


@pytest.fixture
def server():
    state = State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


POLICY = {
    "org": "acme",
    "repo_settings": {"has_wiki": False, "delete_branch_on_merge": True},
    "labels": {"sync": [{"name": "bug", "color": "d73a4a"}, {"name": "enhancement", "color": "a2eeef"}], "delete_unused": True},
    "config_dirs": {"forbid": [".archon"]},
    "workflows": [{"template": "release"}],
}


def run(url, tmp_path, *argv, env_extra=None):
    policy = tmp_path / "policy.yaml"
    policy.write_text(yaml.safe_dump(POLICY))
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")}
    env.update({"GH_TOKEN": TOKEN, "GITHUB_API_URL": url, "PATH": "/nonexistent", **(env_extra or {})})
    cmd = [sys.executable, "-I", str(SCRIPT), argv[0], *(["--policy", str(policy)] if argv[0] in ("audit", "apply") else []), *argv[1:]]
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def writes(state):
    return [(m, p) for m, p, _, _ in state.requests if m != "GET"]


def test_audit_reads_everything_it_needs_and_writes_nothing(server, tmp_path):
    state, url = server
    p = run(url, tmp_path, "audit", "--format", "json")
    assert p.returncode == 3, p.stderr
    data = json.loads(p.stdout)
    by_id = {f["message"]: f for f in data["findings"]}
    assert "has_wiki is True, policy wants False" in by_id
    assert "label 'enhancement' is missing" in by_id
    assert "label: update 'bug' (color)" in by_id
    assert sum(1 for f in data["findings"] if f["message"].startswith("label 'old-")) == 130, "the second page of labels was read"
    assert any(f["check"] == "files" and "2 file(s)" in f["message"] for f in data["findings"])
    assert any(f["message"] == "workflow .github/workflows/devflow-release.yml is missing" for f in data["findings"])
    assert writes(state) == []
    assert all(auth == f"Bearer {TOKEN}" for _, _, _, auth in state.requests)
    assert TOKEN not in p.stdout + p.stderr


def test_dry_run_then_apply_without_allow_delete(server, tmp_path):
    state, url = server
    p = run(url, tmp_path, "apply")
    assert p.returncode == 0, p.stderr
    assert "Dry run: nothing was changed" in p.stdout and writes(state) == []
    p = run(url, tmp_path, "apply", "--yes")
    assert p.returncode == 0, p.stdout + p.stderr
    made = writes(state)
    assert ("PATCH", "/repos/acme/app") in made and ("POST", "/repos/acme/app/labels") in made
    assert ("PATCH", "/repos/acme/app/labels/bug") in made
    assert not [w for w in made if w[0] == "DELETE"], "130 unused labels were held back"
    assert p.stdout.count("Held back") == 130
    assert "opened https://github.com/acme/app/pull/1" in p.stdout
    assert state.repo["has_wiki"] is False
    tree_body = next(b for m, pth, b, _ in state.requests if pth.endswith("/git/trees") and m == "POST")
    paths = {e["path"]: e for e in tree_body["tree"]}
    assert paths[".archon/a.yml"]["sha"] is None and paths[".archon/deep/b.yml"]["sha"] is None
    release = yaml.safe_load(paths[".github/workflows/devflow-release.yml"]["content"])
    assert release["jobs"]["release"]["if"] == "github.ref == 'refs/heads/main'"
    ref_body = next(b for m, pth, b, _ in state.requests if pth.endswith("/git/refs"))
    assert re.fullmatch(r"refs/heads/chore/repo-admin-\d{8}", ref_body["ref"]) and ref_body["sha"] == "c2"
    assert not any(m == "PUT" or (m == "PATCH" and pth.endswith("/git/refs/heads/main")) for m, pth, *_ in state.requests)


def test_allow_delete_deletes_only_what_was_selected(server, tmp_path):
    state, url = server
    p = run(url, tmp_path, "audit", "--format", "json")
    ids = [f["id"] for f in json.loads(p.stdout)["findings"] if f["message"] == "label 'old-7' is not in the policy and is unused"]
    assert len(ids) == 1
    p = run(url, tmp_path, "apply", "--only", ids[0], "--allow-delete", "--yes")
    assert p.returncode == 0, p.stdout + p.stderr
    assert writes(state) == [("DELETE", "/repos/acme/app/labels/old-7")]


def test_whoami_over_http(server, tmp_path):
    state, url = server
    p = run(url, tmp_path, "whoami", "--org", "acme")
    assert p.returncode == 0 and json.loads(p.stdout) == {"authenticated": True, "login": "owner", "org": "acme", "role": "admin", "can_administer": True}


@pytest.mark.parametrize("status", [500, 401])
def test_a_failing_server_is_reported_not_raised(server, tmp_path, status):
    state, url = server
    state.fail_with = status
    p = run(url, tmp_path, "audit")
    assert p.returncode == 1 and "Traceback" not in p.stderr
    assert f"HTTP {status}" in p.stderr and TOKEN not in p.stdout + p.stderr


def test_unreachable_server_is_a_clean_error(tmp_path):
    p = run("http://127.0.0.1:9", tmp_path, "audit")
    assert p.returncode == 1 and "Traceback" not in p.stderr and "repo_admin:" in p.stderr
