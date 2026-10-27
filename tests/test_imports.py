import importlib

import pytest

MODULES = ["config", "db", "ai", "bot", "main", "webapp.server"]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)
