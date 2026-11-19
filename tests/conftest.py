import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.helpers import Env  # noqa: E402


@pytest.fixture
def env(tmp_path):
    return Env(str(tmp_path))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("VAULTMOVE_PERF") != "1":
        skip = pytest.mark.skip(reason="set VAULTMOVE_PERF=1 to run the 200k-file performance test")
        for item in items:
            if "perf" in item.keywords:
                item.add_marker(skip)
