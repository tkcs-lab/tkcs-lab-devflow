"""HTTP helpers shared by the clients of the toolkit (the board client, repo-admin's GitHub client).

    from tld.net import SameHostRedirects, opener

urllib copies every request header, `Authorization` included, to a redirect target. `SameHostRedirects`
keeps it only when the target has the same scheme, host and port as the request (S18). The opener also sends
`User-Agent: tld/<version>` unless a request sets its own: urllib's default `Python-urllib/3.x` is refused by
Cloudflare's Browser Integrity Check (error 1010), which breaks a board behind Cloudflare. Stdlib only.
"""
from __future__ import annotations

import urllib.parse
import urllib.request

from tld import __version__

USER_AGENT = f"tld/{__version__}"


def same_origin(a: str, b: str) -> bool:
    """True when both URLs have the same scheme and the same host and port."""
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return pa.scheme.lower() == pb.scheme.lower() and pa.netloc.lower() == pb.netloc.lower()


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but drop the Authorization header when the target is another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and not same_origin(newurl, req.full_url):
            new.remove_header("Authorization")
        return new


def opener() -> urllib.request.OpenerDirector:
    """An opener that follows redirects with SameHostRedirects and identifies itself as tld/<version>.

    A User-Agent set on the request itself wins over the opener's default.
    """
    built = urllib.request.build_opener(SameHostRedirects)
    built.addheaders = [("User-Agent", USER_AGENT)]
    return built
