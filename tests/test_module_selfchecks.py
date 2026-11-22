from __future__ import annotations

import runpy
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module_path",
    [
        "astra/agent/apply.py",
        "astra/agent/loop.py",
        "astra/context/stemming.py",
        "astra/context/file_terms.py",
        "astra/patch/analyzer.py",
        "astra/runtime/repo_lock.py",
    ],
)
def test_module_self_check_examples_execute(module_path):
    """Keep executable module examples working and include them in coverage."""
    runpy.run_path(str(REPOSITORY_ROOT / module_path), run_name="__main__")
