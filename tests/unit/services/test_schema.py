from __future__ import annotations

import pytest

from rankrat.errors import InputLimitError, SchemaFetchError
from rankrat.providers.schema_fetch import SchemaFetchResult
from rankrat.services import schema
from rankrat.services.schema import (
    LocalSchemaValidationRequest,
    LocalSchemaValidationService,
    PublicSchemaValidationRequest,
    assess_google_indexing_eligibility,
    assess_google_indexing_json_ld,
)


@pytest.mark.parametrize(
    "html,reason",
    (
        (
            b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
            "JobPosting",
        ),
        (
            b'<script type="application/ld+json">'
            b'{"@graph":[{"@type":"VideoObject",'
            b'"publication":{"@type":"BroadcastEvent"}}]}</script>',
            "BroadcastEvent",
        ),
    ),
)
def test_schema_eligibility_accepts_only_documented_google_types(html: bytes, reason: str) -> None:
    result = assess_google_indexing_eligibility(html)
    assert result.eligible is True
    assert reason in result.reason


@pytest.mark.parametrize(
    "html",
    (
        b"<html><body>no schema</body></html>",
        b'<script type="application/ld+json">{"@type":"Article"}</script>',
        b'<script type="application/ld+json">{"@type":"BroadcastEvent"}</script>',
        b'<script type="application/ld+json">not-json</script>',
        b"\xff",
    ),
)
def test_schema_eligibility_fails_closed_for_non_eligible_or_malformed_content(html: bytes) -> None:
    assert assess_google_indexing_eligibility(html).eligible is False


def test_schema_eligibility_ignores_scripts_without_json_ld_content_type() -> None:
    assert assess_google_indexing_eligibility(b"<script type>ignored</script>").eligible is False


@pytest.mark.parametrize(
    "html",
    (
        b'<SCRIPT TYPE=application/ld+json>{"@type":"JobPosting"}</SCRIPT>',
        b'<script defer type = "Application/LD+JSON" data-value=">">'
        b'{"@type":"JobPosting"}</script >',
        b'<script data-value=">" type=application/ld+json>{"@type":"JobPosting"}</script>',
    ),
)
def test_schema_eligibility_accepts_strict_json_ld_script_variations(html: bytes) -> None:
    assert assess_google_indexing_eligibility(html).eligible is True


@pytest.mark.parametrize(
    "html",
    (
        b"<script type='application/ld+json'",
        b"<script type='application/ld+json'>{}</script",
        b"<script type='application/ld+json' type='application/ld+json'>{}</script>",
        b"<scripture type='application/ld+json'>{}</scripture>",
        b'<!-- <script type=\'application/ld+json\'>{"@type":"JobPosting"}</script> -->',
        b"<div data-example=\"<script type='application/ld+json'>\">ignored</div>",
        b'<script> <script type=\'application/ld+json\'>{"@type":"JobPosting"}</script> </script>',
        b"<!" * 1_024,
    ),
)
def test_schema_eligibility_fails_closed_for_malformed_or_nested_markup(html: bytes) -> None:
    assert assess_google_indexing_eligibility(html).eligible is False
    assert tuple(schema._types(["valid", 1])) == ()
    assert tuple(schema._types(["JobPosting"])) == ("JobPosting",)


@pytest.mark.parametrize(
    "html",
    (
        b"<!" * 100_000,
        b"<!--" * 50_000,
        b"<script type='application/ld+json'" * 20_000,
    ),
)
def test_schema_eligibility_rejects_large_unterminated_markup_in_one_pass(html: bytes) -> None:
    assert assess_google_indexing_eligibility(html).eligible is False


def test_json_ld_script_scanner_internal_fail_closed_branches() -> None:
    assert schema._extract_json_ld_scripts("plain text") == ()
    assert schema._is_named_tag("<script", 0, "script") is False
    assert schema._parse_script_open_tag("<script", 0) is None
    assert schema._parse_script_open_tag("<script ", 0) is None
    assert schema._parse_script_open_tag("<script /", 0) is None
    assert schema._parse_script_open_tag("<script type=", 0) is None
    assert schema._parse_script_open_tag("<script type>", 0) is None
    assert schema._parse_html_attribute_value("", 0) == (None, 0)
    assert schema._parse_html_attribute_value("'unterminated", 0) == (None, 13)
    assert schema._parse_html_attribute_value(">", 0) == (None, 0)
    assert schema._find_script_end_tag("plain text", 0) is None
    assert schema._find_script_end_tag("</script", 0) is None
    assert schema._find_script_end_tag("</scripta>", 0) is None
    assert schema._find_script_end_tag("</script unexpected>", 0) is None
    assert schema._find_script_end_tag("plain text", len("plain text")) is None


def test_local_schema_json_and_html_checks_enforce_bounds() -> None:
    service = LocalSchemaValidationService()
    assert service.validate_json_ld(LocalSchemaValidationRequest('{"@type":"JobPosting"}')).eligible
    assert assess_google_indexing_json_ld("not-json").eligible is False
    assert (
        assess_google_indexing_eligibility(
            b"<script type='application/ld+json'>" + b"[" * 33 + b"]" * 33 + b"</script>"
        ).eligible
        is False
    )
    assert assess_google_indexing_json_ld("[" * 33 + "]" * 33).eligible is False
    assert (
        assess_google_indexing_eligibility(
            b"".join(b"<script type='application/ld+json'>{}</script>" for _ in range(65))
        ).eligible
        is False
    )
    assert (
        assess_google_indexing_eligibility(
            b"<script type='application/ld+json'>\"" + b"x" * 65_537 + b'"</script>'
        ).eligible
        is False
    )
    assert assess_google_indexing_json_ld("[" + "0," * 10_000 + "0]").eligible is False
    with pytest.raises(InputLimitError):
        LocalSchemaValidationRequest("x" * 1_048_577)
    with pytest.raises(InputLimitError):
        LocalSchemaValidationRequest("\U0001f600" * 262_145)
    assert assess_google_indexing_eligibility(b"<" * 1_048_577).eligible is False


@pytest.mark.asyncio
async def test_public_schema_url_validation_uses_bounded_fetcher_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LocalSchemaValidationService()
    calls: list[tuple[str, float]] = []

    async def fetch(url: str, timeout_seconds: float) -> SchemaFetchResult:
        calls.append((url, timeout_seconds))
        return SchemaFetchResult(
            url="https://example.com/jobs",
            content_type="text/html",
            body=b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
        )

    monkeypatch.setattr(service._fetcher, "fetch", fetch)
    report = await service.validate_url(
        PublicSchemaValidationRequest("https://example.com/jobs", 2.5)
    )

    assert calls == [("https://example.com/jobs", 2.5)]
    assert report.url == "https://example.com/jobs"
    assert report.eligibility.eligible is True


@pytest.mark.asyncio
async def test_public_schema_url_validation_preserves_fetcher_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LocalSchemaValidationService()

    async def reject(_: str, __: float) -> SchemaFetchResult:
        raise SchemaFetchError("schema URL host is not publicly routable")

    monkeypatch.setattr(service._fetcher, "fetch", reject)
    with pytest.raises(SchemaFetchError, match="not publicly routable"):
        await service.validate_url(PublicSchemaValidationRequest("https://invalid.example/", 1.0))
