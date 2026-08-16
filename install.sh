#!/bin/bash
set -euo pipefail

# rankrat installer. Installs the `rankrat` host wrapper (which drives the
# published Docker images) onto your PATH. Two modes:
#
#   Per-user (no root) — just for the current user:
#     curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh | bash
#     command -> ~/.local/bin/rankrat
#
#   System-wide (root) — the command for every user on the box:
#     curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh | sudo bash
#     command -> /usr/local/bin/rankrat
#
# The mode auto-detects from who runs it (root -> system, otherwise per-user);
# pass --system or --user to force it. Pass --uninstall to remove the command.
#
# Rankrat data (provider secrets, OAuth tokens, writable state) is per-user and
# owner-only: the wrapper defaults to ~/.config/rankrat and refuses any profile
# it does not exclusively own, so a system-wide install shares only the COMMAND
# — every user still runs `rankrat setup` into their own private profile. Pass a
# different profile per launch with `rankrat --data-dir DIR` or RANKRAT_DATA_DIR.

readonly INSTALL_LOG_FILE="/tmp/rankrat-install.log"
readonly SYSTEM_INSTALL_PATH="/usr/local/bin/rankrat"
readonly USER_INSTALL_RELATIVE_PATH=".local/bin/rankrat"
readonly WRAPPER_MARKER="Host wrapper for published Rankrat images"
readonly WRAPPER_URL="https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat"
# shellcheck disable=SC2016  # deliberately literal: $HOME/$PATH must land in the rc file unexpanded
readonly USER_PATH_SNIPPET='export PATH="$HOME/.local/bin:$PATH"'

MODE=""
ACTION="install"
INSTALL_PATH=""
WRAPPER_TEMPORARY_FILE=""

# This is a user-facing installer, so the output is deliberately plain prose
# (per the bash logging rule's carve-out for CLI output the user asked for),
# not JSON. Everything is still tee'd to INSTALL_LOG_FILE for a debug trail.
say() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

fail() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

trap 'printf "error: install failed — see %s\n" "$INSTALL_LOG_FILE" >&2' ERR
trap 'rm -f "$WRAPPER_TEMPORARY_FILE"' EXIT
exec > >(tee -a "$INSTALL_LOG_FILE") 2>&1

# resolve_mode fixes MODE (from --system/--user, else EUID) and the command path
# it implies, and rejects the nonsensical combinations up front.
resolve_mode() {
	if [[ -z "$MODE" ]]; then
		if ((EUID == 0)); then MODE="system"; else MODE="user"; fi
	fi

	case "$MODE" in
	system)
		((EUID == 0)) ||
			fail "the system-wide install needs root — re-run with sudo, or use --user for a per-user install"
		INSTALL_PATH="$SYSTEM_INSTALL_PATH"
		;;
	user)
		((EUID != 0)) ||
			fail "the per-user install must not run as root — run it as your normal account, or use --system"
		[[ -n "${HOME:-}" ]] || fail "HOME is unset; cannot resolve the per-user install path"
		INSTALL_PATH="$HOME/$USER_INSTALL_RELATIVE_PATH"
		;;
	*)
		fail "unknown mode: $MODE"
		;;
	esac
}

# require_managed_target refuses to touch a rankrat command path that exists but
# is not the rankrat wrapper, so the installer never clobbers an unrelated file.
require_managed_target() {
	[[ -e "$INSTALL_PATH" ]] || return 0
	grep -Fq "$WRAPPER_MARKER" "$INSTALL_PATH" 2>/dev/null ||
		fail "$INSTALL_PATH already exists and is not the rankrat wrapper — remove it first"
}

# warn_user_path tells a per-user installer, in the terminal, exactly how to put
# ~/.local/bin on PATH for both bash and zsh when it is not already there.
warn_user_path() {
	[[ "$MODE" == "user" ]] || return 0

	case ":$PATH:" in
	*":$HOME/.local/bin:"*) return 0 ;;
	esac

	warn "$HOME/.local/bin is not on your PATH — the rankrat command will not be found yet"
	printf '\nAdd it to your shell, then restart the shell (or source the file):\n\n'
	printf "  bash:  echo '%s' >> ~/.bashrc && source ~/.bashrc\n" "$USER_PATH_SNIPPET"
	printf "  zsh:   echo '%s' >> ~/.zshrc && source ~/.zshrc\n\n" "$USER_PATH_SNIPPET"
}

uninstall() {
	require_managed_target
	if [[ ! -e "$INSTALL_PATH" ]]; then
		say "no rankrat command at $INSTALL_PATH — nothing to remove"

		return
	fi
	rm -f -- "$INSTALL_PATH" || fail "could not remove $INSTALL_PATH"
	say "removed the rankrat command at $INSTALL_PATH"
	say "your profile (e.g. ~/.config/rankrat) was left untouched; delete it by hand if you want it gone"
}

install_wrapper() {
	require_managed_target

	command -v docker >/dev/null 2>&1 ||
		warn "docker was not found — rankrat needs Docker at runtime; install it before running the command"

	say "downloading the rankrat wrapper"
	WRAPPER_TEMPORARY_FILE="$(mktemp)"
	curl -fsSL "$WRAPPER_URL" -o "$WRAPPER_TEMPORARY_FILE" ||
		fail "could not download the rankrat wrapper from $WRAPPER_URL"
	grep -Fq "$WRAPPER_MARKER" "$WRAPPER_TEMPORARY_FILE" ||
		fail "the downloaded file is not the rankrat wrapper — refusing to install it"

	install -d "$(dirname "$INSTALL_PATH")"
	install -m 0755 "$WRAPPER_TEMPORARY_FILE" "$INSTALL_PATH" ||
		fail "could not install the rankrat command at $INSTALL_PATH"
	say "installed the rankrat command at $INSTALL_PATH ($MODE mode)"

	warn_user_path

	printf '\nrankrat is installed. Next:\n\n'
	printf '  rankrat setup      # create your owner-only profile and configure providers\n'
	printf '  rankrat http -d    # start the REST + Streamable-HTTP stack (detached)\n'
	printf '  rankrat            # MCP over stdio (default)\n\n'
	printf 'Your profile defaults to ~/.config/rankrat; override it per launch with\n'
	printf '"rankrat --data-dir /absolute/path" or the RANKRAT_DATA_DIR environment\n'
	printf 'variable to keep a separate profile per account or workspace.\n'
}

main() {
	local argument
	for argument in "$@"; do
		case "$argument" in
		--system) MODE="system" ;;
		--user) MODE="user" ;;
		--uninstall) ACTION="uninstall" ;;
		*) fail "unknown argument: $argument (supported: --system, --user, --uninstall)" ;;
		esac
	done

	resolve_mode

	case "$ACTION" in
	install) install_wrapper ;;
	uninstall) uninstall ;;
	*) fail "unknown action: $ACTION" ;;
	esac
}

main "$@"
