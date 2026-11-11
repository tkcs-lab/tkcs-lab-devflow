"""secret-scan: credential-looking content is denied; the message never echoes the secret.

Every fake token is assembled at run time from pieces, so this file (and the repo) never contains a
string that looks like a real credential.
"""
import random
import string

import pytest

from hooks_helpers import event, make_repo, make_repo_with_origin, run, run_script

HOOK = "secret-scan"
_rng = random.Random(7)


def rand(n, alphabet=string.ascii_letters + string.digits):
    """Deterministic high-entropy text that always contains a digit and a letter."""
    chars = [_rng.choice(alphabet) for _ in range(n)]
    chars[0] = next((c for c in alphabet if c.isalpha()), chars[0])  # a letter and a digit, always
    chars[1] = "7"
    return "".join(chars)


def build_tokens():
    return {
        "private-key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----\n" + rand(40) + "\n",
        "private-key-openssh": "-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----",
        "aws-access-key-id": "AKIA" + rand(16, string.ascii_uppercase + string.digits),
        "aws-secret-key": "aws_secret_access_key = " + rand(40, string.ascii_letters + string.digits + "/+"),
        "github-token": "ghp_" + rand(36),
        "github-token-oauth": "gho_" + rand(36),
        "github-fine-grained": "github_pat_" + rand(60, string.ascii_letters + string.digits + "_"),
        "gcp-api-key": "AIza" + rand(35, string.ascii_letters + string.digits + "_-"),
        "gcp-oauth-token": "ya29." + rand(40),
        "slack-token": "xoxb-" + rand(30, string.digits + "-"),
        "stripe-key": "sk_live_" + rand(30),
        "anthropic-key": "sk-ant-" + rand(40, string.ascii_letters + string.digits + "_-"),
        "openai-key": "sk-" + rand(48),
        "npm-token": "npm_" + rand(36),
        "azure-storage-key": "AccountKey=" + rand(64, string.ascii_letters + string.digits + "+/") + "==",
    }


TOKENS = build_tokens()


@pytest.mark.parametrize("pattern", sorted(TOKENS))
def test_specific_patterns_are_denied_without_echoing(feature_repo, pattern):
    secret = TOKENS[pattern]
    content = f"first line\nvalue = '{secret}'\nlast line\n" if "\n" not in secret else f"x\n{secret}\n"
    r = run(HOOK, event("Write", feature_repo, file_path=str(feature_repo / "a.txt"), content=content))
    assert r.code == 2
    assert f"(pattern: {pattern.split('-oauth')[0].split('-fine')[0].split('-openssh')[0]}" in r.stderr
    assert "line 2" in r.stderr
    token_part = secret.split("\n")[-1] if "\n" not in secret else secret.split("\n")[1]
    assert token_part[8:] not in r.stderr and secret[12:] not in r.stderr


GENERIC = [
    "API_KEY = '{v}'", "api_key: {v}", "export GITHUB_TOKEN={v}", "client_secret: \"{v}\"", "apiKey: '{v}',",
    "\"secret_token\": \"{v}\"", "SECRET_KEY={v}", "deploy-token = {v}", "my.service.key={v}", "AuthToken := \"{v}\"",
]
# (template, value) rows for D9: passwords, URL credentials, bearer tokens, `#` in a quoted value.
GENERIC_D9 = [
    ("DB_PASSWORD=\"{v}\"", rand(16)),
    ("postgres://user:{v}@db.example.org/app", "s3cretpw"),
    ("Authorization: Bearer {v}", "eyJ" + rand(12) + ".eyJ" + rand(12) + "." + rand(16)),
    ("SECRET_KEY=\"{v}\"", rand(11) + "#" + rand(12)),
]


@pytest.mark.parametrize("template", GENERIC)
def test_generic_assignments_are_denied(feature_repo, template):
    value = rand(32)
    for tool, ti in (("Write", {"content": "\n" + template.format(v=value)}),
                     ("Edit", {"old_string": "x", "new_string": "\n" + template.format(v=value)}),
                     ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "ok"},
                                              {"old_string": "b", "new_string": template.format(v=value)}]})):
        r = run(HOOK, event(tool, feature_repo, file_path=str(feature_repo / "a.txt"), **ti))
        assert r.code == 2, (tool, template)
        assert "high-entropy-assignment" in r.stderr
        assert value not in r.stderr and value[:10] not in r.stderr
    assert "edit 2" in r.stderr


@pytest.mark.parametrize("template,value", GENERIC_D9)
def test_password_url_bearer_and_hash_values_are_denied(feature_repo, template, value):
    line = template.format(v=value)
    r = run(HOOK, event("Write", feature_repo, file_path=str(feature_repo / "a.txt"), content=f"a\n{line}\n"))
    assert r.code == 2, line
    assert "line 2" in r.stderr and value not in r.stderr


def test_long_line_is_scanned_quickly(feature_repo):
    import time
    key = f' API_KEY = "{rand(32)}"'
    t = time.monotonic()
    r = run(HOOK, event("Write", feature_repo, file_path=str(feature_repo / "a.txt"), content="a" * 200_000 + key))
    assert r.code == 2 and time.monotonic() - t < 5  # a backtracking pattern takes minutes; 5 s is a wide margin
    t = time.monotonic()
    r = run(HOOK, event("Write", feature_repo, file_path=str(feature_repo / "a.txt"), content="a" * 20_000))
    assert r.code == 0 and time.monotonic() - t < 5


def test_allow_mark_must_end_the_line(feature_repo):
    secret = "ghp_" + rand(36)
    mid = f"t = '{secret}'  # secret-scan:allow and then more"
    r = run(HOOK, event("Write", feature_repo, file_path="a", content=mid))
    assert r.code == 2
    end = f"t = '{secret}'  # secret-scan:allow  "
    assert run(HOOK, event("Write", feature_repo, file_path="a", content=end)).code == 0


def test_notebook_cells_are_scanned(feature_repo):
    r = run(HOOK, event("NotebookEdit", feature_repo, notebook_path="n.ipynb", new_source="t = 'ghp_" + rand(36) + "'"))
    assert r.code == 2


ALLOWED = [
    "API_KEY = os.environ['API_KEY']", "token = get_token()", "API_KEY=your-api-key-here", "SECRET_KEY=changeme",
    "SECRET_KEY=change_me_to_a_long_random_string_please", "export TOKEN=$(vault read x)", "export TOKEN=${TOKEN}",
    "api_key: \"short\"", "monkey = 'abcdefghij0123456789abcdefghij'", "PUBLIC_KEY = '" + rand(40) + "'",
    "sha256 = '" + "e3b0c44298fc1c149afbf4c8996fb924" + "'", "key_name = 'a_perfectly_normal_identifier_name'",
    "TOKEN_URL = 'https://example.com/oauth/token'", "secret_name: my-prod-secret-name-v2", "the token is rotated monthly",
    "-----BEGIN CERTIFICATE-----", "# BEGIN PRIVATE KEY handling is described in the docs", "ssh-keygen -t ed25519",
    "api_key: {{ secrets.API_KEY }}", "token: ${{ secrets.DEPLOY_TOKEN_FOR_THE_RELEASE_JOB }}",
    "key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx1'", "API_KEY = 'example-" + rand(30) + "'",
    "# a long line of ordinary prose " + "words " * 40, "",
    "token = '" + "ghp_" + rand(36) + "'  # secret-scan:allow",
    'url = "https://user:${PASSWORD}@host/x"', 'password = "changeme-placeholder-value"', "Authorization: Bearer ${TOKEN}",
]


@pytest.mark.parametrize("line", ALLOWED)
def test_allowed(feature_repo, line):
    r = run(HOOK, event("Write", feature_repo, file_path=str(feature_repo / "a.txt"), content=f"a\n{line}\nb\n"))
    assert (r.code, r.stderr) == (0, ""), line


def test_removing_a_secret_is_allowed(feature_repo):
    secret = "ghp_" + rand(36)
    r = run(HOOK, event("Edit", feature_repo, file_path="a.txt", old_string=f"token = '{secret}'", new_string="token = ENV"))
    assert r.code == 0


def test_other_tools_are_ignored(feature_repo):
    secret = "ghp_" + rand(36)
    assert run(HOOK, event("Bash", feature_repo, command=f"echo {secret}")).code == 0
    assert run(HOOK, event("Read", feature_repo, file_path="a")).code == 0


def test_message_names_the_line_and_how_to_proceed(feature_repo):
    content = "a\nb\n" + "t = '" + "ghp_" + rand(36) + "'\n"
    r = run(HOOK, event("Write", feature_repo, file_path="/x/creds.py", content=content))
    assert "line 3" in r.stderr and "/x/creds.py" in r.stderr and "GitHub token" in r.stderr
    assert "secret-scan:allow" in r.stderr and "environment" in r.stderr


def test_disable_flag(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", committed="git:\n  main_branch: main\nhooks:\n  disable: [secret-scan]\n")
    r = run(HOOK, event("Write", repo, file_path="a", content="t = '" + "ghp_" + rand(36) + "'"))
    assert r.code == 0


def test_script_contract_and_fail_open(feature_repo):
    ev = event("Write", feature_repo, file_path="a", content="t = '" + "ghp_" + rand(36) + "'")
    denied = run_script(HOOK, ev)
    assert denied.returncode == 2 and denied.stdout == ""
    assert run_script(HOOK, event("Write", feature_repo, file_path="a", content="hello")).returncode == 0
    broken = run_script(HOOK, {}, project=feature_repo, stdin="not json")
    assert broken.returncode == 1 and "cannot read the hook event" in broken.stderr, "a broken event does not block"
