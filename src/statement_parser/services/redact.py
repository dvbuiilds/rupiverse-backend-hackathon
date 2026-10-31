import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)


def redact(markdown: str) -> str:
    """Mask personal identifiers before the text leaves the server. Keeps UPI payee names and amounts."""
    text = _drop_lines_before_first_heading(markdown)
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    # Account, card and CKYC numbers: keep only the last four digits.
    return _LONG_NUMBER.sub(lambda m: "X" * (len(m.group()) - 4) + m.group()[-4:], text)


def _drop_lines_before_first_heading(text: str) -> str:
    """Drops digit-free lines above the first heading (name and address). Keeps all text if there is no heading."""
    heading = _HEADING.search(text)
    if heading is None:
        return text
    head, body = text[: heading.start()], text[heading.start() :]
    kept = [line for line in head.splitlines() if any(ch.isdigit() for ch in line)]
    return "\n".join(kept) + "\n" + body
