import os

import pytest

from sollab.storage import connect


def pytest_collection_modifyitems(config, items):
    del config
    if os.environ.get("SOLLAB_SKIP_NETWORK") == "1":
        skip = pytest.mark.skip(reason="SOLLAB_SKIP_NETWORK=1")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def conn(tmp_path):
    database = connect(tmp_path / "sollab.db")
    yield database
    database.close()
