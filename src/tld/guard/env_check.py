"""env-check (session_start and prompt): warns when a cloud session runs in an environment the profile does not list.

Never denies and adds no context. It sets a notice for the user only. The profile key is `runtime.environments`;
the name the session runs in comes from the adapter (`Action.runtime_environment`). See docs/architecture/hooks.md.
"""
from __future__ import annotations

import unicodedata

from tld.guard._common import Ctx, ProfileError

NAME = "env-check"
MAX_NAME = 100
NOTICE_UNSET = ('this cloud session does not say which environment it runs in (the variable TLD_ENVIRONMENT is not set), '
                'and this repository\'s profile expects {expected}. If that is not the environment you meant to use, '
                'stop and start a new session in the right one.')
NOTICE_OTHER = ('this session says it runs in the environment "{got}", and this repository\'s profile expects '
                '{expected}. If that is not the environment you meant to use, stop and start a new session in the right one.')


def _clean(text: str) -> str:
    """Drop control and format characters (Cc, Cf), then cut to MAX_NAME."""
    kept = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    return kept[:MAX_NAME]


def _names(profile: dict | None) -> list[str]:
    runtime = profile.get("runtime") if isinstance(profile, dict) else None
    envs = runtime.get("environments") if isinstance(runtime, dict) else None
    if not isinstance(envs, list):
        return []
    cleaned = [_clean(e).strip() for e in envs if isinstance(e, str)]
    return [n for n in cleaned if n]


def evaluate(ctx: Ctx) -> None:
    ctx.notice = None   # a notice set before this point is not ours; a trust-lookup notice below is kept
    a = ctx.action
    if a.kind not in ("session_start", "prompt") or not a.remote:
        return None
    if a.kind == "prompt" and not a.invoked:
        return None
    names = _names(ctx.profile)
    if not names:
        return None
    got = _clean(a.runtime_environment or "").strip()
    if got.casefold() in {n.casefold() for n in names}:
        return None
    try:
        off = ctx.disabled(NAME)
    except ProfileError:   # an advisory hook never denies on a malformed profile
        return None
    if off:
        return None
    expected = " or ".join('"' + n + '"' for n in names)
    warning = (NOTICE_OTHER.format(got=got, expected=expected) if got
               else NOTICE_UNSET.format(expected=expected))
    ctx.notice = f"{ctx.notice}; {warning}" if ctx.notice else warning
    return None
