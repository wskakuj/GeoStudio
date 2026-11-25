"""The publish guard refuses old source code with a newer release tag."""
from pathlib import Path

import pytest

from geostudio import __version__
from tools.windows.check_release import check_source

ROOT = Path(__file__).resolve().parents[1]


def test_source_matches_its_tag():
    assert check_source(ROOT, "v" + __version__) == __version__


@pytest.mark.parametrize("tag", ["v99.99.99", "preview", "2.0.99", "v2.0.99-rc1"])
def test_wrong_tag_is_refused(tag):
    with pytest.raises(ValueError):
        check_source(ROOT, tag)
