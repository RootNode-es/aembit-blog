import pytest

from slugify import slugify


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello World", "hello-world"),
        ("  Leading and trailing  ", "leading-and-trailing"),
        ("Optimizing Tokens: A Guide!", "optimizing-tokens-a-guide"),
        ("multiple   spaces__and--dashes", "multiple-spaces-and-dashes"),
        ("Café Crème", "cafe-creme"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected
