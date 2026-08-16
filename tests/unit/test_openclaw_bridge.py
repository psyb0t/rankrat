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


def test_openclaw_manifest_declares_a_static_stdio_server() -> None:
    manifest = json.loads((_PLUGIN_ROOT / "openclaw.plugin.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "@psyb0t/rankrat"
    assert manifest["configSchema"] == {"type": "object", "additionalProperties": False}
    assert set(manifest["environment"]) == {
        "RANKRAT_DATA_DIR",
        "RANKRAT_IMAGE",
        "RANKRAT_LOG_LEVEL",
        "RANKRAT_READ_ONLY",
    }
    assert manifest["mcpServers"] == {
        "rankrat": {
            "transport": "stdio",
            "command": "node",
            "args": ["./bin/cli.js"],
        }
    }
    assert manifest["extensions"] == ["./bin/cli.js"]
    assert "Lighthouse" in manifest["description"]


def test_codex_manifest_exposes_install_surface_metadata() -> None:
    manifest = json.loads(Path(".agents/.codex-plugin/plugin.json").read_text(encoding="utf-8"))

    interface = manifest["interface"]
    assert interface["displayName"] == "Rankrat"
    assert interface["category"] == "Developer Tools"
    assert "MCP stdio" in interface["capabilities"]
    assert interface["websiteURL"] == "https://github.com/psyb0t/rankrat"
    assert interface["defaultPrompt"]


def test_bridge_uses_openclaw_safe_environment_and_standard_layout(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".config" / "rankrat"
    root.mkdir(parents=True, mode=0o700)
    config = _create_config(root)
    secrets = root / "secrets"
    oauth = root / "oauth"
    state = root / "state"
    secrets.mkdir(mode=0o700)
    oauth.mkdir(mode=0o700)
    state.mkdir(mode=0o700)

    result = _run_bridge_module_isolated(
        """
import { runStdio } from "./.agents/plugins/rankrat/bin/cli.js";

const status = runStdio(process.env, [], (command, arguments_, options) => {
  process.stdout.write(JSON.stringify({ command, arguments_, options }));
  return { status: 0 };
});
process.exitCode = status;
""",
        {"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
    )

    invocation = json.loads(result.stdout)
    arguments = invocation["arguments_"]
    assert result.returncode == 0
    assert f"type=bind,src={config.resolve()},dst=/run/config" in arguments
    assert f"type=bind,src={config.resolve()},dst=/run/config,readonly" not in arguments
    assert f"type=bind,src={secrets.resolve()},dst=/run/secrets,readonly" in arguments
    assert f"type=bind,src={oauth.resolve()},dst=/run/oauth" in arguments
    assert f"type=bind,src={state.resolve()},dst=/run/state" in arguments
    assert "RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3" in arguments


def test_bridge_package_declares_clawhub_extension_without_runtime_dependencies() -> None:
    package = json.loads((_PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    source = _BRIDGE.read_text(encoding="utf-8")

    assert _BRIDGE.stat().st_mode & 0o111 == 0o111
    assert package["openclaw"] == {
        "extensions": ["./bin/cli.js"],
        "compat": {"pluginApi": _OPENCLAW_PLUGIN_API_COMPATIBILITY},
        "build": {"openclawVersion": _OPENCLAW_BUILD_VERSION},
    }
    assert package.get("dependencies", {}) == {}
    assert "mcp-remote" not in source
    assert "RANKRAT_TRANSPORT" not in source
    assert "RANKRAT_AUTH_TOKEN" not in source
    assert "RANKRAT_URL" not in source


def test_mcp_registry_description_fits_the_published_limit() -> None:
    server = json.loads(Path("server.json").read_text(encoding="utf-8"))

    assert 0 < len(server["description"]) <= _MCP_REGISTRY_DESCRIPTION_MAXIMUM_LENGTH


def test_bridge_rejects_missing_boundary_directory_without_stdout() -> None:
    result = _run_bridge({"HOME": "", "RANKRAT_DATA_DIR": ""})

    assert result.returncode == 1
    assert "Missing HOME" in result.stderr
    assert result.stdout == ""


def test_bridge_reports_an_inaccessible_docker_executable_without_stdout(
    tmp_path: Path,
) -> None:
    data_directory = _create_data_directory(tmp_path)
    result = _run_bridge({"RANKRAT_DATA_DIR": str(data_directory), "PATH": "/nonexistent"})

    assert result.returncode == 1
    assert "Could not start Rankrat's stdio container" in result.stderr
    assert result.stdout == ""


def test_bridge_runs_hardened_read_only_docker_stdio_command(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile with spaces")
    config = data_directory / "config"
    secrets = data_directory / "secrets"
    oauth = data_directory / "oauth"
    state = data_directory / "state"

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
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_LOG_LEVEL": "debug",
            "RANKRAT_IMAGE": "registry.example/rankrat:test",
            "RANKRAT_READ_ONLY": "true",
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
    assert arguments[arguments.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert arguments[arguments.index("--pids-limit") + 1] == "128"
    assert arguments[arguments.index("--memory") + 1] == "512m"
    assert arguments[arguments.index("--cpus") + 1] == "1"
    assert f"/{Path('tmp')}:rw,noexec,nosuid,size=32m" in arguments
    assert f"type=bind,src={config.resolve()},dst=/run/config,readonly" in arguments
    assert f"type=bind,src={secrets.resolve()},dst=/run/secrets,readonly" in arguments
    assert f"type=bind,src={oauth.resolve()},dst=/run/oauth" in arguments
    assert f"type=bind,src={state.resolve()},dst=/run/state" in arguments
    assert "RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3" in arguments
    assert f"type=bind,src={oauth.resolve()},dst=/run/oauth,readonly" not in arguments
    assert "RANKRAT_LOG_LEVEL=debug" in arguments
    assert "RANKRAT_READ_ONLY=true" in arguments
    assert "UNRELATED_RANKRAT_SETTING=must-not-be-forwarded" not in arguments
    assert arguments[-2:] == ["registry.example/rankrat:test", "stdio"]


def test_bridge_runs_writable_with_only_config_writable(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path)
    config = data_directory / "config"
    secrets = data_directory / "secrets"
    oauth = data_directory / "oauth"

    result = _run_bridge_module(
        """
import { runStdio } from "./.agents/plugins/rankrat/bin/cli.js";

const status = runStdio(process.env, [], (command, arguments_, options) => {
  process.stdout.write(JSON.stringify({ command, arguments_, options }));
  return { status: 0 };
});
process.exitCode = status;
""",
        {
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "false",
        },
    )

    invocation = json.loads(result.stdout)
    arguments = invocation["arguments_"]
    assert result.returncode == 0
    assert f"type=bind,src={config.resolve()},dst=/run/config" in arguments
    assert f"type=bind,src={config.resolve()},dst=/run/config,readonly" not in arguments
    assert f"type=bind,src={secrets.resolve()},dst=/run/secrets,readonly" in arguments
    assert f"type=bind,src={oauth.resolve()},dst=/run/oauth" in arguments
    assert "RANKRAT_READ_ONLY=false" in arguments


def test_bridge_makes_config_writable_for_normal_write_mode(
    tmp_path: Path,
) -> None:
    data_directory = _create_data_directory(tmp_path)
    config = data_directory / "config"

    result = _run_bridge_module(
        """
import { runStdio } from "./.agents/plugins/rankrat/bin/cli.js";

const status = runStdio(process.env, [], (command, arguments_, options) => {
  process.stdout.write(JSON.stringify({ command, arguments_, options }));
  return { status: 0 };
});
process.exitCode = status;
""",
        {
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "false",
        },
    )

    arguments = json.loads(result.stdout)["arguments_"]
    assert result.returncode == 0
    assert f"type=bind,src={config.resolve()},dst=/run/config" in arguments
    assert f"type=bind,src={config.resolve()},dst=/run/config,readonly" not in arguments
    assert "RANKRAT_READ_ONLY=false" in arguments


def test_bridge_rejects_invalid_read_only_setting(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path)

    invalid = _run_bridge(
        {
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "yes",
        }
    )

    assert invalid.returncode == 1
    assert "must be either true or false" in invalid.stderr
    assert invalid.stdout == ""


def test_bridge_rejects_unsafe_or_symlinked_writable_boundary(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path)
    config = data_directory / "config"
    config.chmod(0o755)

    unsafe = _run_bridge(
        {
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "false",
        }
    )

    config.chmod(0o700)
    boundary = config / "boundaries.json"
    target = tmp_path / "real-boundaries.json"
    boundary.rename(target)
    boundary.symlink_to(target)
    symlinked = _run_bridge({"RANKRAT_DATA_DIR": str(data_directory)})

    assert unsafe.returncode == 1
    assert "must be owner-only" in unsafe.stderr
    assert symlinked.returncode == 1
    assert "must not contain symbolic links" in symlinked.stderr
    assert unsafe.stdout == symlinked.stdout == ""


def test_bridge_rejects_symlinked_ancestor_directories(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    _create_data_directory(real_root)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)

    config_result = _run_bridge({"RANKRAT_DATA_DIR": str(linked_root)})

    assert config_result.returncode == 1
    assert "must not contain symbolic links" in config_result.stderr
    assert config_result.stdout == ""


def test_bridge_rejects_unsafe_mount_delimiters_before_docker(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path)

    invalid_directories = (
        "/",
        f"{data_directory},readonly",
        f"{data_directory}\nforged",
        f"{data_directory}/../{data_directory.name}",
    )
    for invalid_directory in invalid_directories:
        result = _run_bridge({"RANKRAT_DATA_DIR": invalid_directory})
        assert result.returncode == 1
        assert result.stdout == ""


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


def _run_bridge_module_isolated(
    script: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    # OpenClaw starts stdio MCP children with a restricted environment.
    return subprocess.run(  # noqa: S603
        [_NODE_EXECUTABLE, "--input-type=module", "--eval", script],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
    )


def _create_config(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    boundary = config / "boundaries.json"
    boundary.write_text("{}", encoding="utf-8")
    boundary.chmod(0o600)
    return config


def _create_data_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)
    _create_config(path)
    for name in ("secrets", "oauth", "state"):
        (path / name).mkdir(mode=0o700)
    return path
