from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VEX_PATH = _PROJECT_ROOT / "security" / "rankrat-cpython.openvex.json"
_PYTHON_PRODUCT_PURL = "pkg:generic/python@3.14.6"
_PATCHED_CRYPTOGRAPHY_VERSION = "50.0.0"
_VULNERABLE_CRYPTOGRAPHY_VERSION = "49.0.0"
_EXPECTED_CVES = {
    "CVE-2026-11940",
    "CVE-2026-11972",
    "CVE-2026-15308",
}
_PIP_AUDIT_ID = "PYSEC-2026-3552"
_NOT_AFFECTED_STATUS = "not_affected"
_NOT_EXECUTABLE_JUSTIFICATION = "vulnerable_code_not_in_execute_path"
_FORBIDDEN_SOURCE_TOKENS = (
    "html" + ".parser",
    "HTML" + "Parser",
    "tar" + "file",
)


def test_cpython_stdlib_vex_and_cryptography_remediation_are_exact() -> None:
    document = cast(
        dict[str, object],
        json.loads(_VEX_PATH.read_text(encoding="utf-8")),
    )
    statements = _statements(document)

    assert len(statements) == len(_EXPECTED_CVES)
    statements_by_cve = {statement["vulnerability"]["name"]: statement for statement in statements}
    assert set(statements_by_cve) == _EXPECTED_CVES
    for cve in _EXPECTED_CVES:
        statement = statements_by_cve[cve]
        assert statement["products"] == [{"@id": _PYTHON_PRODUCT_PURL}]
        assert statement["status"] == _NOT_AFFECTED_STATUS
        assert statement["justification"] == _NOT_EXECUTABLE_JUSTIFICATION
        assert isinstance(statement["impact_statement"], str)
        assert statement["impact_statement"]

    makefile = (_PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert _PIP_AUDIT_ID not in makefile

    lockfile = (_PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert f'name = "cryptography"\nversion = "{_PATCHED_CRYPTOGRAPHY_VERSION}"' in lockfile
    assert f'name = "cryptography"\nversion = "{_VULNERABLE_CRYPTOGRAPHY_VERSION}"' not in lockfile

    for source_path in sorted((_PROJECT_ROOT / "src").rglob("*.py")):
        source = source_path.read_text(encoding="utf-8")
        assert not any(token in source for token in _FORBIDDEN_SOURCE_TOKENS), source_path


def _statements(document: dict[str, object]) -> list[dict[str, Any]]:
    assert document["@context"] == "https://openvex.dev/ns/v0.2.0"
    assert document["@id"] == (
        "https://github.com/psyb0t/rankrat/security/rankrat-cpython.openvex.json"
    )
    assert document["author"] == "psyb0t/rankrat maintainers"
    assert document["role"] == "Product security assessment"
    assert document["version"] == 3
    assert isinstance(document["timestamp"], str)
    assert document["timestamp"]
    raw_statements: object = document["statements"]
    assert isinstance(raw_statements, list)
    statements_as_objects = cast(list[object], raw_statements)
    assert all(isinstance(statement, dict) for statement in statements_as_objects)
    return cast(list[dict[str, Any]], statements_as_objects)
