"""Four synthetic repositories for the /setup survey: security_heavy, ios_ui_app, docs_website, bare.

build(dest, repo="security_heavy", with_profile=False) returns the expected survey outcome (Design D12).
No real project names, no secrets, no network.
"""
from __future__ import annotations

from pathlib import Path

from . import init_repo

REPOS = ("security_heavy", "ios_ui_app", "docs_website", "bare")

PROFILE = """\
project:
  name: setup-fixture

docs:
  must_read:
    - README.md

git:
  main_branch: main
  branch_pattern: "<type>/<kebab-case>"
  branch_types: [feature, fix, chore]

verify:
  fast:
    - "echo fast"
  dod:
    - "echo dod"

stacks: []
"""

SECURITY_HEAVY = {
    "pyproject.toml": '[project]\nname = "vault-demo"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
    "README.md": "# vault-demo\n\nA small service that handles sign-in, secrets and personal data.\n",
    "SECURITY.md": "# Security policy\n\nReport problems privately to the maintainers.\n",
    "docs/threat-model.md": "# Threat model\n\nAssets: tokens, keys and user records. Attackers: remote clients.\n",
    "src/app/auth.py": '"""Sign-in: login form, oauth callback, jwt issue."""\n\n\ndef login(user: str, password_ok: bool) -> str:\n    return "jwt-for-" + user if password_ok else ""\n\n\ndef oauth_callback(code: str) -> str:\n    return "jwt-for-" + code\n',
    "src/app/session.py": '"""Sessions: a jwt is checked on each request; login refreshes it."""\n\n\ndef valid(jwt: str) -> bool:\n    return jwt.startswith("jwt-")\n\n\ndef oauth_scopes() -> list[str]:\n    return ["profile"]\n',
    "src/app/crypto.py": '"""Helpers: encrypt with aes, sign with hmac."""\nimport hashlib\nimport hmac\n\n\ndef sign(key: bytes, msg: bytes) -> str:\n    return hmac.new(key, msg, hashlib.sha256).hexdigest()\n\n\ndef encrypt(data: bytes) -> bytes:\n    """aes-gcm placeholder."""\n    return data[::-1]\n',
    "src/app/vault.py": '"""Vault: encrypt values at rest (aes), hmac the index."""\n\n\ndef store(name: str, value: bytes) -> str:\n    return "hmac:" + name\n',
    "src/app/secrets.py": '"""Reads the password and api_key from the environment; never logs a credential."""\nimport os\n\n\ndef password() -> str:\n    return os.environ.get("APP_PASSWORD", "")\n\n\ndef api_key() -> str:\n    return os.environ.get("APP_API_KEY", "")\n',
    "src/app/config.py": '"""Config: names of the password, api_key and credential settings."""\n\nSETTINGS = ("password", "api_key", "credential")\n',
    "src/app/client.py": '"""Outbound calls with requests.get."""\nimport requests\n\n\ndef fetch(url: str) -> str:\n    return requests.get(url, timeout=5).text\n',
    "src/app/sync.py": '"""Sync job using httpx."""\nimport httpx\n\n\ndef pull(url: str) -> str:\n    return httpx.get(url, timeout=5).text\n',
    "src/app/users.py": '"""User records: personal data, covered by gdpr erasure requests."""\n\n\ndef erase(user_id: int) -> bool:\n    return True  # gdpr erasure\n',
    "src/app/export.py": '"""Export of personal data for a gdpr access request."""\n\n\ndef export(user_id: int) -> dict:\n    return {"id": user_id}  # personal data\n',
    "tests/unit/test_auth.py": "from app import auth\n\n\ndef test_login_denied():\n    assert auth.login('a', False) == ''\n",
    ".github/workflows/ci.yml": "name: ci\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: python -m pytest -q\n",
}

IOS_UI_APP = {
    "Package.swift": '// swift-tools-version:5.9\nimport PackageDescription\n\nlet package = Package(name: "App", targets: [.target(name: "App"), .testTarget(name: "AppTests", dependencies: ["App"])])\n',
    "App.xcodeproj/project.pbxproj": "// !$*UTF8*$!\n{\n\tbuildSettings = {\n\t\tTARGETED_DEVICE_FAMILY = \"1,2\";\n\t};\n}\n",
    "README.md": "# App\n\nA small notes app for iPhone and iPad.\n",
    "Sources/App/Views/HomeView.swift": "import SwiftUI\n\nstruct HomeView: View {\n    var body: some View { Text(\"Home\") }\n}\n",
    "Sources/App/Views/Detail/DetailView.swift": "import SwiftUI\n\nstruct DetailView: View {\n    var body: some View { Text(\"Detail\") }\n}\n",
    "Sources/App/Model/Note.swift": "import Foundation\n\nstruct Note: Codable {\n    var id: Int\n    var text: String\n}\n",
    "Sources/App/Model/NetworkClient.swift": "import Foundation\n\nfinal class NetworkClient {\n    func load(_ url: URL) async throws -> Data {\n        try await URLSession.shared.data(from: url).0\n    }\n}\n",
    "Sources/App/Model/Sync.swift": "import Foundation\n\nfinal class Sync {\n    let session = URLSession(configuration: .default)\n}\n",
    "Tests/AppTests/NoteTests.swift": "import XCTest\n\nfinal class NoteTests: XCTestCase {\n    func testEmpty() { XCTAssertTrue(true) }\n}\n",
    "Tests/AppUITests/LaunchTests.swift": "import XCTest\n\nfinal class LaunchTests: XCTestCase {\n    func testLaunch() { XCTAssertTrue(true) }\n}\n",
    ".github/workflows/macos-tests.yml": "name: macos-tests\non: [workflow_dispatch, pull_request]\njobs:\n  test:\n    runs-on: macos-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: xcodebuild test\n",
}

DOCS_WEBSITE = {
    "go.mod": "module example.test/docsite\n\ngo 1.22\n",
    "lib.go": "package docsite\n\nfunc Add(a, b int) int { return a + b }\n",
    "lib_test.go": 'package docsite\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal("bad sum")\n\t}\n}\n',
    "README.md": "# docsite\n\nA tiny Go library with a documentation website.\n",
    "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n\n- Initial release.\n",
    "docs/index.md": "# Home\n\nStart here.\n",
    "docs/guide.md": "# Guide\n\nHow to use the library.\n",
    "docs/api.md": "# API\n\n`Add(a, b)` returns the sum.\n",
    "docs/faq.md": "# FAQ\n\nQuestions and answers.\n",
    "docs/design.md": "# Design\n\nOne function, no state.\n",
    "docs/contributing.md": "# Contributing\n\nOpen a pull request.\n",
    "docs/notes.md": "# Notes\n\nLoose notes.\n",
    "docs/adr/README.md": "# Architecture decisions\n\n- [0001 Record decisions](0001-record.md)\n",
    "docs/adr/0001-record.md": "# 1. Record decisions\n\nStatus: accepted. We keep decisions in this folder.\n",
    "website/docusaurus.config.js": "module.exports = { title: 'docsite', url: 'https://example.test', baseUrl: '/' };\n",
    "website/package.json": '{\n  "name": "website",\n  "private": true,\n  "scripts": {"build": "docusaurus build", "check-links": "linkcheck ./build"}\n}\n',
}

BARE = {
    "README.md": "A bare repository.\n",
    ".gitignore": "*.log\n",
}

FILES = {"security_heavy": SECURITY_HEAVY, "ios_ui_app": IOS_UI_APP, "docs_website": DOCS_WEBSITE, "bare": BARE}

EXPECTED = {
    "security_heavy": {
        "stacks": ["python"],
        "website": None,
        "dispatchable": [],
        "roles": {
            "posture": {"security": "critical"},
            "disable": ["website-maintainer"],
            "required": [
                {"role": "security-reviewer", "at": ["implement_phase", "implement_final"], "blocking": True},
                {"role": "test-architect", "at": ["make_plan"], "blocking": False},
            ],
        },
    },
    "ios_ui_app": {
        "stacks": ["swift", "ipados"],
        "website": None,
        "dispatchable": ["macos-tests.yml"],
        "roles": {
            "posture": {"security": "standard"},
            "disable": ["website-maintainer"],
            "required": [
                {"role": "security-reviewer", "at": ["implement_final"], "blocking": False},
                {"role": "ux-reviewer", "at": ["implement_final"], "blocking": False, "when": ["Sources/App/Views/**"]},
            ],
        },
    },
    "docs_website": {
        "stacks": ["go"],
        "website": {"dir": "website", "build": "npm run build", "links": "npm run check-links"},
        "dispatchable": [],
        "roles": {
            "posture": {"security": "standard"},
            "required": [
                {"role": "security-reviewer", "at": ["implement_final"], "blocking": False},
                {"role": "test-architect", "at": ["make_plan"], "blocking": False},
                {"role": "tech-writer", "at": ["dod"], "blocking": False},
            ],
        },
    },
    "bare": {
        "stacks": [],
        "website": None,
        "dispatchable": [],
        "roles": {"posture": {"security": "standard"}, "disable": ["website-maintainer"]},
    },
}


def build(dest: Path, repo: str = "security_heavy", with_profile: bool = False) -> dict:
    if repo not in FILES:
        raise ValueError(f"unknown repo {repo!r}; expected one of {REPOS}")
    files = dict(FILES[repo])
    if with_profile:
        files[".tld/toolkit.yaml"] = PROFILE
    init_repo(dest, files)
    docs = repo == "docs_website"
    return {
        "main_branch": "main",
        "repo": repo,
        **EXPECTED[repo],
        "adr_dir": "docs/adr" if docs else None,
        "adr_index": "docs/adr/README.md" if docs else None,
        "changelog": {"file": "CHANGELOG.md", "section": "## [Unreleased]"} if docs else None,
    }
