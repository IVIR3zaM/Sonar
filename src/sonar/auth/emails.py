"""Pure email normalization for the sign-in allow-list (SPEC §13 Access list)."""


def normalize_email(email: str) -> str:
    """Trim and lowercase `email`; it must have exactly one `@` with text on both sides."""
    normalized = email.strip().lower()
    local, separator, domain = normalized.partition("@")
    if not separator or "@" in domain or not local or not domain:
        raise ValueError(f"'{email.strip()}' is not a valid email: use the form name@example.com.")
    return normalized
