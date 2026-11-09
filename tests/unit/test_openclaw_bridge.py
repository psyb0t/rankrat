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
_MCP_REGISTRY_DESCRIPTION_MAXIMUM_LENGTH = 100
_OPENCLAW_BUILD_VERSION = "2026.3.24-beta.2"
_OPENCLAW_PLUGIN_API_COMPATIBILITY = f">={_OPENCLAW_BUILD_VERSION}"


def test_openclaw_manifest_declares_the_http_bridge() -> None:
    manifest = json.loads((_PLUGIN_ROOT / "openclaw.plugin.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "@psyb0t/rankrat"
    assert manifest["configSchema"] == {"type": "object", "additionalProperties": False}
    assert set(manifest["environment"]) == {"RANKRAT_URL", "RANKRAT_TOKEN"}
    assert manifest["environment"]["RANKRAT_URL"]["required"] is True
    assert manifest["mcpServers"] == {
        "rankrat": {"transport": "stdio", "command": "node", "args": ["./bin/cli.js"]}
    }
    assert manifest["extensions"] == ["./bin/cli.js"]
    assert "Streamable HTTP" in manifest["description"]


def test_codex_manifest_exposes_install_surface_metadata() -> None:
    manifest = json.loads(Path(".agents/.codex-plugin/plugin.json").read_text(encoding="utf-8"))

    interface = manifest["interface"]
    assert interface["displayName"] == "Rankrat"
    assert interface["category"] == "Developer Tools"
    assert "MCP Streamable HTTP" in interface["capabilities"]
    assert "MCP stdio" not in interface["capabilities"]
    assert interface["websiteURL"] == "https://github.com/psyb0t/rankrat"
    assert interface["defaultPrompt"]


def test_claude_manifest_asks_for_the_server_url_and_a_sensitive_bearer() -> None:
    manifest = json.loads(Path(".agents/.claude-plugin/plugin.json").read_text(encoding="utf-8"))

    assert manifest["userConfig"]["url"]["required"] is True
    assert manifest["userConfig"]["token"]["sensitive"] is True


def test_registry_entry_advertises_streamable_http() -> None:
    server = json.loads(Path("server.json").read_text(encoding="utf-8"))

    assert server["packages"][0]["transport"] == {
        "type": "streamable-http",
        "url": "http://localhost:8080/mcp",
    }


def test_bridge_package_pins_mcp_remote_and_declares_the_extension() -> None:
    package = json.loads((_PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))

    assert _BRIDGE.stat().st_mode & 0o111 == 0o111
    assert package["openclaw"] == {
        "extensions": ["./bin/cli.js"],
        "compat": {"pluginApi": _OPENCLAW_PLUGIN_API_COMPATIBILITY},
        "build": {"openclawVersion": _OPENCLAW_BUILD_VERSION},
    }
    assert package["dependencies"] == {"mcp-remote": "0.1.38"}


def test_bridge_builds_the_proxy_command_without_the_token_in_arguments() -> None:
    result = _run_bridge_module(
        """
import { main } from "./.agents/plugins/rankrat/bin/cli.js";

const calls = [];
const status = main(
  { RANKRAT_URL: "http://127.0.0.1:8080//", RANKRAT_TOKEN: "EXAMPLE-DO-NOT-USE" },
  ["--debug"],
  (command, arguments_, options) => {
    calls.push({ command, arguments_, env: options.env.RANKRAT_TOKEN, stdio: options.stdio });
    return { status: 0 };
  },
  () => "/fake/proxy.js",
);
process.stdout.write(JSON.stringify({ status, calls }));
""",
        {},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == 0
    (call,) = payload["calls"]
    assert call["arguments_"] == [
        "/fake/proxy.js",
        "http://127.0.0.1:8080/mcp",
        "--transport",
        "http-only",
        "--header",
        "Authorization: Bearer ${RANKRAT_TOKEN}",
        "--debug",
    ]
    assert "EXAMPLE-DO-NOT-USE" not in json.dumps(call["arguments_"])
    assert call["env"] == "EXAMPLE-DO-NOT-USE"
    assert call["stdio"] == "inherit"


def test_bridge_omits_the_header_without_a_token() -> None:
    result = _run_bridge_module(
        """
import { proxyArguments } from "./.agents/plugins/rankrat/bin/cli.js";

process.stdout.write(JSON.stringify(proxyArguments({ RANKRAT_URL: "http://h:1" }, [], "p.js")));
""",
        {},
    )

    assert json.loads(result.stdout) == ["p.js", "http://h:1/mcp", "--transport", "http-only"]


def test_bridge_without_a_url_fails_on_stderr_only() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "RANKRAT_URL"}
    # The executable and bridge path are fixed by this test, not caller input.
    result = subprocess.run(  # noqa: S603
        [_NODE_EXECUTABLE, str(_BRIDGE)],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Missing RANKRAT_URL" in result.stderr


def test_plugin_readme_documents_the_bridge_and_native_http() -> None:
    source = (_PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")

    assert "RANKRAT_URL" in source
    assert "RANKRAT_TOKEN" in source
    assert '"transport": "streamable-http"' in source
    assert "exact five MCP tool names and REST routes" in source
    assert "removed in 0.21.0" in source


def test_mcp_registry_description_fits_the_published_limit() -> None:
    server = json.loads(Path("server.json").read_text(encoding="utf-8"))

    assert 0 < len(server["description"]) <= _MCP_REGISTRY_DESCRIPTION_MAXIMUM_LENGTH


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
    assert "primaryEnv:" not in skill
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


def test_skill_points_to_the_single_public_rankrat_launcher() -> None:
    skill = Path(".agents/skills/rankrat/SKILL.md").read_text(encoding="utf-8")
    setup = Path(".agents/skills/rankrat/references/setup.md").read_text(encoding="utf-8")

    assert Path("rankrat").is_file()
    assert "rankrat.sh" not in skill
    assert "rankrat.sh" not in setup


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
