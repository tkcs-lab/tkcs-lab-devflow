"""Decoding of bash ANSI-C quoting (`$'...'`), standard library only.

    ansi_c_decode(r"\x2d\x2dforce")  ->  "--force"
"""
from __future__ import annotations

_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
           "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
_OCTAL = "01234567"
_HEX = "0123456789abcdefABCDEF"


def ansi_c_decode(body: str) -> str:
    """The text bash makes of `$'body'` (without the quotes). A NUL ends the string, as in bash;
    an unknown escape is kept as a backslash plus the character."""
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e = body[i + 1]
        i += 2
        if e in _SIMPLE:
            out.append(_SIMPLE[e])
        elif e in _OCTAL:
            j = i
            while j < n and j < i + 2 and body[j] in _OCTAL:
                j += 1
            code = int(body[i - 1:j], 8) & 0xFF
            i = j
            if code == 0:
                break
            out.append(chr(code))
        elif e in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[e]
            j = i
            while j < n and j < i + width and body[j] in _HEX:
                j += 1
            if j == i:
                out.append("\\" + e)
                continue
            code = int(body[i:j], 16)
            i = j
            if code == 0:
                break
            try:
                out.append(chr(code))
            except (ValueError, OverflowError):
                out.append("\\" + e + body[i - (j - i):i])
        elif e == "c" and i < n:
            code = ord(body[i]) & 0x1F
            i += 1
            if code == 0:
                break
            out.append(chr(code))
        else:
            out.append("\\" + e)
    return "".join(out)
