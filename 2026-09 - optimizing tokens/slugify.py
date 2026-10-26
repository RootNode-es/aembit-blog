import re
import unicodedata


def slugify(text: str) -> str:
    """Convert a string into a lowercase, hyphen-separated URL slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")
