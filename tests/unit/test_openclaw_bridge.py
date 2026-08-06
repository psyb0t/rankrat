from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from rankrat.config import Settings
from rankrat.constants import (
    API_PREFIX,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_PATH,
    LIGHTHOUSE_AUDIT_OPERATION,
    LIGHTHOUSE_AUDIT_PATH,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_PATH,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_PATH,
    LIGHTHOUSE_SEO_FINDINGS_OPERATION,
    LIGHTHOUSE_SEO_FINDINGS_PATH,
)

_PLUGIN_ROOT = Path(".agents/plugins/rankrat")
_BRIDGE = _PLUGIN_ROOT / "bin/cli.js"
_NODE_EXECUTABLE = "/usr/local/bin/node"
_LIGHTHOUSE_OPERATIONS = (
    (LIGHTHOUSE_AUDIT_OPERATION, LIGHTHOUSE_AUDIT_PATH),
    (LIGHTHOUSE_SEO_FINDINGS_OPERATION, LIGHTHOUSE_SEO_FINDINGS_PATH),
    (
        LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
        LIGHTHOUSE_ACCESSIBILITY_FINDINGS_PATH,
    ),
    (LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION, LIGHTHOUSE_PERFORMANCE_FINDINGS_PATH),
    (
        LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
        LIGHTHOUSE_BEST_PRACTICES_FINDINGS_PATH,
    ),
)


def test_openclaw_manifest_declares_a_static_stdio_server() -> None:
    manifest = json.loads((_PLUGIN_ROOT / "openclaw.plugin.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "@psyb0t/rankrat"
    assert manifest["configSchema"] == {"type": "object", "additionalProperties": False}
    assert manifest["mcpServers"] == {
        "rankrat": {
            "transport": "stdio",
            "command": "node",
            "args": ["./bin/cli.js"],
        }
    }
    assert "extensions" not in manifest
    assert "Lighthouse" in manifest["description"]


def test_bridge_package_has_no_runtime_extension_or_http_proxy_dependency() -> None:
    package = json.loads((_PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    source = _BRIDGE.read_text(encoding="utf-8")

    assert _BRIDGE.stat().st_mode & 0o111 == 0o111
    assert "openclaw" not in package
    assert package.get("dependencies", {}) == {}
    assert "mcp-remote" not in source
    assert "RANKRAT_TRANSPORT" not in source
    assert "RANKRAT_AUTH_TOKEN" not in source
    assert "RANKRAT_URL" not in source


def test_bridge_rejects_missing_boundary_directory_without_stdout() -> None:
    result = _run_bridge({"RANKRAT_CONFIG_DIR": ""})

    assert result.returncode == 1
    assert "Missing RANKRAT_CONFIG_DIR" in result.stderr
    assert result.stdout == ""


def test_bridge_reports_an_inaccessible_docker_executable_without_stdout() -> None:
    result = _run_bridge({"RANKRAT_CONFIG_DIR": "/", "PATH": "/nonexistent"})

    assert result.returncode == 1
    assert "Could not start Rankrat's stdio container" in result.stderr
    assert result.stdout == ""


def test_bridge_runs_hardened_docker_stdio_command(tmp_path: Path) -> None:
    config = tmp_path / "config with spaces"
    secrets = tmp_path / "secrets"
    oauth = tmp_path / "oauth"
    for directory in (config, secrets, oauth):
        directory.mkdir()

    result = _run_bridge_module(
        """
import { runStdio } from "./.agents/plugins/rankrat/bin/cli.js";

const status = runStdio(process.env, [], (command, arguments_, options) => {
  process.stdout.write(JSON.stringify({ command, arguments_, options }));
  return { status: 23 };
});
process.exitCode = status;
""",
        {
            "RANKRAT_CONFIG_DIR": str(config),
            "RANKRAT_SECRETS_DIR": str(secrets),
            "RANKRAT_OAUTH_DIR": str(oauth),
            "RANKRAT_READ_ONLY": "false",
            "RANKRAT_UNBOUNDED": "true",
            "RANKRAT_ALLOW_AGENT_ONBOARDING": "true",
            "RANKRAT_LOG_LEVEL": "debug",
            "RANKRAT_IMAGE": "registry.example/rankrat:test",
            "UNRELATED_RANKRAT_SETTING": "must-not-be-forwarded",
        },
    )

    invocation = json.loads(result.stdout)
    arguments = invocation["arguments_"]
    assert result.returncode == 23
    assert invocation["command"] == "docker"
    assert invocation["options"] == {"stdio": "inherit"}
    assert "--read-only" in arguments
    assert "--cap-drop=ALL" in arguments
    assert "no-new-privileges:true" in arguments
    assert f"/{Path('tmp')}:rw,noexec,nosuid,size=32m" in arguments
    assert f"type=bind,src={config.resolve()},dst=/run/config,readonly" in arguments
    assert f"type=bind,src={secrets.resolve()},dst=/run/secrets,readonly" in arguments
    assert f"type=bind,src={oauth.resolve()},dst=/run/oauth,readonly" in arguments
    assert "RANKRAT_READ_ONLY=false" in arguments
    assert "RANKRAT_UNBOUNDED=true" in arguments
    assert "RANKRAT_ALLOW_AGENT_ONBOARDING=true" in arguments
    assert "RANKRAT_LOG_LEVEL=debug" in arguments
    assert "UNRELATED_RANKRAT_SETTING=must-not-be-forwarded" not in arguments
    assert arguments[-2:] == ["registry.example/rankrat:test", "stdio"]


def test_streamable_http_recipe_keeps_the_bearer_in_openclaw_environment() -> None:
    source = (_PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")

    assert '"transport":"streamable-http"' in source
    assert "Bearer ${RANKRAT_AUTH_TOKEN}" in source
    assert "mcp-remote" not in source
    assert "both Rankrat transports" in source
    assert "exact five MCP tool names and REST routes" in source


def test_all_agent_manifests_describe_the_optional_lighthouse_surface() -> None:
    manifest_paths = (
        Path(".agents/.claude-plugin/plugin.json"),
        Path(".agents/.codex-plugin/plugin.json"),
        _PLUGIN_ROOT / "openclaw.plugin.json",
        _PLUGIN_ROOT / "package.json",
    )

    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "Lighthouse" in manifest["description"]


def test_agent_docs_match_stable_read_discovery_and_lighthouse_contract() -> None:
    skill = Path(".agents/skills/rankrat/SKILL.md").read_text(encoding="utf-8")
    setup = Path(".agents/skills/rankrat/references/setup.md").read_text(encoding="utf-8")

    assert "Read tools have a stable\ndiscovery surface" in skill
    assert "primaryEnv: RANKRAT_CONFIG_DIR" in skill
    assert "primaryEnv: RANKRAT_URL" not in skill
    assert "tool list adapts to which" not in skill
    assert "Read tools stay discoverable" in setup
    assert "Chromium runs with\n`--no-sandbox`" in setup
    assert "public cross-origin redirect" in setup
    assert "outer sandbox such as gVisor or Kata" in setup
    for tool_name, route_path in _LIGHTHOUSE_OPERATIONS:
        assert tool_name in skill
        assert tool_name in setup
        assert f"`POST {API_PREFIX}{route_path}`" in setup


def test_agent_setup_documents_every_runtime_environment_setting() -> None:
    setup = Path(".agents/skills/rankrat/references/setup.md").read_text(encoding="utf-8")
    expected_environment_names = {
        f"RANKRAT_{field_name.upper()}"
        for field_name in Settings.model_fields
        if field_name != "mode"
    }

    for environment_name in expected_environment_names:
        assert f"`{environment_name}`" in setup


def test_skill_bundles_the_canonical_rankrat_wrapper_without_drift() -> None:
    canonical_wrapper = Path("rankrat.sh").read_bytes()
    bundled_wrapper = Path(".agents/skills/rankrat/references/rankrat.sh").read_bytes()

    assert bundled_wrapper == canonical_wrapper


def _run_bridge(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # The executable and bridge path are fixed by this test, not caller input.
    return subprocess.run(  # noqa: S603
        [_NODE_EXECUTABLE, str(_BRIDGE)],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={**os.environ, **environment},
    )


def _run_bridge_module(
    script: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    # The executable and module source are fixed by this test, not caller input.
    return subprocess.run(  # noqa: S603
        [_NODE_EXECUTABLE, "--input-type=module", "--eval", script],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={**os.environ, **environment},
    )
