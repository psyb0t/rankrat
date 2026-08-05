from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VEX_PATH = _PROJECT_ROOT / "security" / "rankrat-cpython.openvex.json"
_PYTHON_PRODUCT_PURL = "pkg:generic/python@3.14.6"
_CRYPTOGRAPHY_PRODUCT_PURL = "pkg:pypi/cryptography@49.0.0"
_EXPECTED_CVES = {
    "CVE-2026-11940",
    "CVE-2026-11972",
    "CVE-2026-15308",
}
_CRYPTOGRAPHY_VULNERABILITY_ID = "GHSA-g6cj-pr64-35w5"
_PIP_AUDIT_ID = "PYSEC-2026-3552"
_NOT_AFFECTED_STATUS = "not_affected"
_NOT_EXECUTABLE_JUSTIFICATION = "vulnerable_code_not_in_execute_path"
_FORBIDDEN_SOURCE_TOKENS = (
    "html" + ".parser",
    "HTML" + "Parser",
    "tar" + "file",
    "pkcs7_decrypt_" + "der",
    "pkcs7_decrypt_" + "pem",
    "pkcs7_decrypt_" + "smime",
    "Enveloped" + "Data",
)


def test_cpython_stdlib_vex_is_exact_and_application_source_has_no_execution_path() -> None:
    document = cast(
        dict[str, object],
        json.loads(_VEX_PATH.read_text(encoding="utf-8")),
    )
    statements = _statements(document)

    assert len(statements) == len(_EXPECTED_CVES) + 1
    statements_by_cve = {statement["vulnerability"]["name"]: statement for statement in statements}
    assert set(statements_by_cve) == _EXPECTED_CVES | {_CRYPTOGRAPHY_VULNERABILITY_ID}
    for cve in _EXPECTED_CVES:
        statement = statements_by_cve[cve]
        assert statement["products"] == [{"@id": _PYTHON_PRODUCT_PURL}]
        assert statement["status"] == _NOT_AFFECTED_STATUS
        assert statement["justification"] == _NOT_EXECUTABLE_JUSTIFICATION
        assert isinstance(statement["impact_statement"], str)
        assert statement["impact_statement"]

    cryptography_statement = statements_by_cve[_CRYPTOGRAPHY_VULNERABILITY_ID]
    assert cryptography_statement["products"] == [{"@id": _CRYPTOGRAPHY_PRODUCT_PURL}]
    assert cryptography_statement["status"] == _NOT_AFFECTED_STATUS
    assert cryptography_statement["justification"] == _NOT_EXECUTABLE_JUSTIFICATION
    assert cryptography_statement["impact_statement"]

    makefile = (_PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert f"PIP_AUDIT_IGNORED_VULNS := {_PIP_AUDIT_ID}" in makefile

    lockfile = (_PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "cryptography"\nversion = "49.0.0"' in lockfile

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
    assert document["version"] == 2
    assert isinstance(document["timestamp"], str)
    assert document["timestamp"]
    raw_statements: object = document["statements"]
    assert isinstance(raw_statements, list)
    statements_as_objects = cast(list[object], raw_statements)
    assert all(isinstance(statement, dict) for statement in statements_as_objects)
    return cast(list[dict[str, Any]], statements_as_objects)
