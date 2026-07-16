"""The README is the PyPI landing page, so its assets have to resolve there too.

Relative and absolute paths each work in exactly one of the two places the
README is read, and which one is correct depends on whether the repository is
public yet:

    private repo   GitHub renders relative paths; raw.githubusercontent URLs are
                   fetched anonymously by GitHub's image proxy and 404.
    public repo    both work on GitHub.
    PyPI           only absolute URLs work — there is no repository to resolve a
                   relative path against.

So the image is relative today and must become absolute before the first PyPI
release. This test is the reminder: it fails once packaging is attempted with an
image PyPI cannot fetch.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"


def _img_srcs(text: str) -> list[str]:
    html = re.findall(r'<img[^>]+src="([^"]+)"', text)
    md = re.findall(r'!\[[^\]]*\]\(([^)\s]+)', text)
    return html + md


def test_relative_readme_images_exist_on_disk():
    """A relative path only renders on GitHub if the file is actually there."""
    for src in _img_srcs(README.read_text()):
        if src.startswith(("http://", "https://")):
            continue
        assert (REPO / src).is_file(), f"README references a missing image: {src}"


def test_readme_images_are_absolute_once_published():
    """Before the first PyPI release, every image must be an absolute URL.

    Skipped while the version is unreleased. When you bump off 0.1.0 to publish,
    this starts failing until the image URLs are absolute — which is the point.
    """
    import tomllib

    with open(REPO / "pyproject.toml", "rb") as fh:
        version = tomllib.load(fh)["project"]["version"]

    if version == "0.1.0":
        import pytest
        pytest.skip("0.1.0 is unreleased; images go absolute at publish time")

    relative = [s for s in _img_srcs(README.read_text())
                if not s.startswith(("http://", "https://"))]
    assert not relative, (
        f"README has relative images {relative}, which render as broken on the "
        f"PyPI page. Point them at raw.githubusercontent.com/alethicdev/alethic/main/..."
    )
