from __future__ import annotations

import runpy

import pytest

from rankrat import cli


def test_module_entrypoint_propagates_the_cli_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "main", lambda: 17)
    with pytest.raises(SystemExit) as exit_error:
        runpy.run_module("rankrat.__main__", run_name="__main__")
    assert exit_error.value.code == 17
