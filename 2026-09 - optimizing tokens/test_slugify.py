import pytest

from slugify import slugify


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello World", "hello-world"),
        ("  Leading and trailing  ", "leading-and-trailing"),
        ("Multiple   spaces---and_underscores", "multiple-spaces-and-underscores"),
        ("Special!@#$%^&*()Chars", "special-chars"),
        ("Café Déjà Vu", "cafe-deja-vu"),
        ("Python 3.12 Release", "python-3-12-release"),
        ("already-a-slug", "already-a-slug"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected
