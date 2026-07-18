"""The README is the PyPI landing page, so its images must resolve there.

PyPI renders this README with no repository to resolve a relative path against,
so `docs/architecture.png` renders as a broken image on the project page. Only an
absolute URL works there.

The images were relative for a while, deliberately: GitHub fetches README images
anonymously, so a raw.githubusercontent URL 404s on a private repo. That
constraint ended when the repo went public, and absolute is now correct in both
places at once.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
RAW_PREFIX = "https://raw.githubusercontent.com/alethicdev/alethic-kernel/main/"


def _img_srcs(text: str) -> list[str]:
    html = re.findall(r'<img[^>]+src="([^"]+)"', text)
    md = re.findall(r'!\[[^\]]*\]\(([^)\s]+)', text)
    return html + md


def test_readme_images_are_absolute():
    """A relative image renders broken on PyPI, where there is no repo."""
    relative = [s for s in _img_srcs(README.read_text())
                if not s.startswith(("http://", "https://"))]
    assert not relative, (
        f"README has relative images {relative}, which render broken on the PyPI "
        f"page. Use {RAW_PREFIX}<path>."
    )


def test_readme_images_point_at_files_that_exist():
    """An absolute URL can rot silently — it is not checked by anything at build.

    Anything under our own raw.githubusercontent prefix names a path in this
    repo, so it can be checked here without a network call: a renamed or deleted
    asset fails now rather than as a broken image on the project page.
    """
    for src in _img_srcs(README.read_text()):
        if not src.startswith(RAW_PREFIX):
            continue
        path = REPO / src[len(RAW_PREFIX):]
        assert path.is_file(), f"README image points at a missing file: {src}"
