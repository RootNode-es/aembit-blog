import re
import unicodedata


def slugify(text: str) -> str:
    """Convert a string into a lowercase, hyphen-separated URL slug."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower())
    return slug.strip("-")
