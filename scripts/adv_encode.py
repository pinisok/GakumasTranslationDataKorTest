"""ADV text encoding utilities.

Pure functions for encoding text fields before CSV export:
- Escape sequences (newline, carriage return, tilde)
- Dot normalization (... → …, .... → ……)
- <em> tag word splitting
"""

import re

from .helper import REGEX_DOTS_4_TO_6, REGEX_DOTS_3


def _encode(string: str) -> str:
    """Encode a text string for CSV export.

    Escapes newlines/CR, converts ~ to fullwidth, normalizes dots to ellipsis.
    """
    string = string.replace("\n", "\\n").replace("\r", "\\r").replace("~", "～")
    string = REGEX_DOTS_4_TO_6.sub('……', string)
    string = REGEX_DOTS_3.sub('…', string)
    return string


END_EM_LENGTH = 5

_EM_PATTERN = re.compile(r'<em(?:\\?=)?>')


def _processEMtag(string: str) -> str:
    """Split multi-word <em> / <em\\=> tags into per-word tags.

    Example: <em>hello world</em>     → <em>hello</em> <em>world</em>
             <em\\=>hello world</em>  → <em\\=>hello</em> <em\\=>world</em>
    """
    if len(string) < 1:
        return string
    match = _EM_PATTERN.search(string)
    if match is None:
        return string
    start_idx = match.start()
    open_tag = match.group()  # "<em>" or "<em\=>" or "<em=>"
    open_len = len(open_tag)
    end_idx = string[start_idx:].find("</em>")
    if end_idx == -1:
        return string
    inner = string[start_idx + open_len:start_idx + end_idx]
    result = inner.replace(" ", f"</em> {open_tag}")
    return (
        string[:start_idx]
        + open_tag + result + "</em>"
        + _processEMtag(string[start_idx + end_idx + END_EM_LENGTH:])
    )
