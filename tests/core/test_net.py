import http.server
import threading
import urllib.request

import pytest

from tld import __version__
from tld import net


class Echo(http.server.BaseHTTPRequestHandler):
    seen: list[str | None] = []

    def do_GET(self):
        Echo.seen.append(self.headers.get("User-Agent"))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture
def echo():
    Echo.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), Echo)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def test_opener_identifies_as_tld_not_python_urllib(echo):
    with net.opener().open(echo, timeout=10) as resp:
        assert resp.status == 200
    assert Echo.seen == [f"tld/{__version__}"]
    assert "urllib" not in Echo.seen[0]


def test_request_user_agent_wins_over_the_default(echo):
    req = urllib.request.Request(echo, headers={"User-Agent": "tld-repo-admin"})
    with net.opener().open(req, timeout=10):
        pass
    assert Echo.seen == ["tld-repo-admin"]
