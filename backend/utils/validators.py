"""Reusable Pydantic field validators."""

import re
from typing import Annotated

from pydantic import AfterValidator

# Intentionally permissive: accepts any syntactically valid email including
# special-use TLDs (.local, .internal, .test) used in development environments.
# Format: <local-part>@<domain>.<tld>  (TLD 2–63 chars, all alphanumeric + hyphen)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z0-9\-]{2,63}$")


def _validate_email(v: str) -> str:
    if not _EMAIL_RE.match(v):
        raise ValueError(f"'{v}' is not a valid email address")
    return v.lower()


EmailStr = Annotated[str, AfterValidator(_validate_email)]
