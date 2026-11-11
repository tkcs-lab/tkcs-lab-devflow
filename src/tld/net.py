"""HTTP helpers shared by the clients of the toolkit (the board client, repo-admin's GitHub client).

    from tld.net import SameHostRedirects, opener

urllib copies every request header, `Authorization` included, to a redirect target. `SameHostRedirects`
keeps it only when the target has the same scheme, host and port as the request (S18). Stdlib only.
"""
from __future__ import annotations

import urllib.parse
import urllib.request


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
    """An opener that follows redirects with SameHostRedirects."""
    return urllib.request.build_opener(SameHostRedirects)
