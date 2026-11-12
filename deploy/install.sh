#!/bin/sh
# Installer for tld, the command line and the board server.
#
#   curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/tkcs-lab/tkcs-lab-devflow/releases/latest/download/install.sh | sh -s -- board
#
# Usage: install.sh [cli|board|uninstall]   (default: cli)
#
# This file is stamped by the release workflow: the release replaces the version default below with its own
# version. A copy taken from a checkout is not stamped and refuses to run unless TLD_VERSION is set.
#
# Variables (the first five are the interface; the last three are test hooks):
#   TLD_VERSION       version to install; a leading v is dropped (default: the stamped release version)
#   TLD_PYTHON        interpreter for the venv (default: the first of python3.13, python3.12, python3.11,
#                     python3 that is 3.11 or newer)
#   TLD_BIN_DIR       where the tld link goes (default: $HOME/.local/bin)
#   TLD_BOARD_DIR     board directory (default: $HOME/tld-board)
#   XDG_DATA_HOME     the data directory is $XDG_DATA_HOME/tld (default: $HOME/.local/share)
#   TLD_RELEASE_BASE  (test hook) download base; files are $TLD_RELEASE_BASE/v<version>/<name>
#   TLD_PIP_ARGS      (test hook) extra pip arguments, word-split on purpose
#   TLD_VENV_ARGS     (test hook) extra arguments for python -m venv
#
# The downloads are checked against SHA256SUMS of the same release: that catches a corrupt or truncated
# download, not a tampered release (see SECURITY.md).
set -eu

TLD_VERSION="${TLD_VERSION:-@TLD_VERSION@}"
BASE="${TLD_RELEASE_BASE:-https://github.com/tkcs-lab/tkcs-lab-devflow/releases/download}"
BIN="${TLD_BIN_DIR:-$HOME/.local/bin}"
BOARD_DIR="${TLD_BOARD_DIR:-$HOME/tld-board}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/tld"
TMP=""

say() { printf '%s\n' "tld-install: $*"; }
die() { printf '%s\n' "tld-install: $*" >&2; exit 1; }

cleanup() { if [ -n "$TMP" ]; then rm -rf "$TMP"; fi; }

make_tmp() {
    TMP=$(mktemp -d "${TMPDIR:-/tmp}/tld-install.XXXXXX") || die "could not create a temporary directory"
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}

# Sets VERSION. The value feeds rm -rf and the download URL, so only digits and exactly two inner dots pass.
check_version() {
    case "$TLD_VERSION" in
        *@*) die "this copy of install.sh is not from a release: run the one from a release, or set TLD_VERSION=X.Y.Z" ;;
    esac
    VERSION=${TLD_VERSION#v}
    case "$VERSION" in
        '' | *[!0-9.]* | .* | *. | *..*) die "invalid version: $TLD_VERSION" ;;
    esac
    if [ "$(printf %s "$VERSION" | tr -dc . | wc -c)" -ne 2 ]; then
        die "invalid version: $TLD_VERSION"
    fi
}

# fetch NAME DEST
fetch() {
    curl -fsSL "$BASE/v$VERSION/$1" -o "$2" ||
        die "cannot download $1 for v$VERSION (a release before the first one with installer assets has none)"
}

# verify FILE: FILE is in $TMP and its name is looked up in the downloaded SHA256SUMS.
verify() {
    want=""
    while read -r sum name; do
        name=${name#\*}
        if [ "$name" = "$1" ]; then
            want=$sum
            break
        fi
    done < "$TMP/SHA256SUMS"
    [ -n "$want" ] || die "no checksum for $1 in SHA256SUMS"
    if command -v sha256sum >/dev/null 2>&1; then
        got=$(sha256sum "$TMP/$1" | cut -d ' ' -f 1)
    elif command -v shasum >/dev/null 2>&1; then
        got=$(shasum -a 256 "$TMP/$1" | cut -d ' ' -f 1)
    else
        die "need sha256sum or shasum"
    fi
    [ "$got" = "$want" ] || die "checksum mismatch for $1: refusing to install"
}

pick_python() {
    if [ -n "${TLD_PYTHON:-}" ]; then
        PY=$TLD_PYTHON
        return 0
    fi
    for c in python3.13 python3.12 python3.11 python3; do
        if "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
            PY=$c
            return 0
        fi
    done
    die "need Python 3.11 or newer: install one or set TLD_PYTHON"
}

install_cli() {
    check_version
    pick_python
    make_tmp
    WHEEL="tld-$VERSION-py3-none-any.whl"
    fetch "$WHEEL" "$TMP/$WHEEL"
    fetch SHA256SUMS "$TMP/SHA256SUMS"
    verify "$WHEEL"

    mkdir -p "$BIN" "$DATA/venvs"
    VENV="$DATA/venvs/$VERSION"
    rm -rf "$VENV"
    # shellcheck disable=SC2086
    "$PY" -m venv ${TLD_VENV_ARGS:-} "$VENV" || {
        rm -rf "$VENV"
        die "could not create a virtual environment; on Debian or Ubuntu install python3-venv"
    }
    # shellcheck disable=SC2086
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check ${TLD_PIP_ARGS:-} "$TMP/$WHEEL" || {
        rm -rf "$VENV"
        die "could not install the wheel into $VENV"
    }
    out=$("$VENV/bin/tld" --version 2>&1 || true)
    if [ "$out" != "tld $VERSION" ]; then
        rm -rf "$VENV"
        die "tld --version printed '$out', expected 'tld $VERSION'"
    fi

    if [ -e "$BIN/tld" ] && [ ! -L "$BIN/tld" ]; then
        rm -rf "$VENV"
        die "$BIN/tld exists and was not made by this installer"
    fi
    OLD=$(readlink "$BIN/tld" 2>/dev/null || true)
    ln -s "$VENV/bin/tld" "$BIN/.tld.$$"
    mv -f "$BIN/.tld.$$" "$BIN/tld"

    # Keep this version and the one the link pointed into (for rollback); a venv is never moved.
    OLDV=""
    case "$OLD" in
        "$DATA/venvs/"*)
            OLDV=${OLD#"$DATA/venvs/"}
            OLDV=${OLDV%%/*}
            ;;
    esac
    for d in "$DATA/venvs"/*; do
        [ -d "$d" ] || continue
        b=${d##*/}
        if [ "$b" != "$VERSION" ] && [ "$b" != "$OLDV" ]; then
            rm -rf "$DATA/venvs/$b"
        fi
    done

    case ":$PATH:" in
        *":$BIN:"*) ;;
        *) say "$BIN is not on your PATH; add it with: export PATH=\"$BIN:\$PATH\"" ;;
    esac
    say "tld $VERSION installed: $BIN/tld"
}

uninstall_cli() {
    if [ -L "$BIN/tld" ]; then
        target=$(readlink "$BIN/tld" 2>/dev/null || true)
        case "$target" in
            "$DATA/venvs/"*) rm -f "$BIN/tld" ;;
        esac
    fi
    rm -rf "$DATA"
    say "tld removed. A board directory ($BOARD_DIR) is untouched; run 'docker compose down' in it to stop the board (the data volume stays)."
}

# has_value NAME: the .env file of the board has a non-empty NAME.
has_value() {
    grep -Eq "^$1=.+" "$BOARD_DIR/.env"
}

install_board() {
    check_version
    if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
        die "Docker with the compose plugin is required"
    fi
    make_tmp
    fetch compose.yaml "$TMP/compose.yaml"
    fetch SHA256SUMS "$TMP/SHA256SUMS"
    verify compose.yaml
    if grep -Eq 'image: *["'"'"']?@' "$TMP/compose.yaml"; then
        die "compose.yaml is not stamped"
    fi

    mkdir -p "$BOARD_DIR"
    # Local changes belong in compose.override.yaml, which compose merges and this installer never touches.
    cp "$TMP/compose.yaml" "$BOARD_DIR/.compose.yaml.$$"
    mv -f "$BOARD_DIR/.compose.yaml.$$" "$BOARD_DIR/compose.yaml"

    if L=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' tld-board 2>/dev/null); then
        case "$L" in
            '' | '<no value>')
                die "a container named tld-board made by docker run exists: run docker rm -f tld-board once; the data volume tld-board-data is reused"
                ;;
        esac
    fi

    if [ ! -e "$BOARD_DIR/.env" ]; then
        (
            umask 077
            token=$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n')
            {
                printf 'TLD_BOARD_TOKEN=%s\n' "$token"
                printf 'TLD_BOARD_OWNER_PASSPHRASE=\n'
                printf 'TLD_BOARD_PUBLIC_ORIGIN=\n'
                printf 'TLD_BOARD_SESSION_URL=https://claude.ai/code/\n'
            } > "$BOARD_DIR/.env"
        )
        say "created $BOARD_DIR/.env with a new board token (it stays in that file)"
    fi

    (cd "$BOARD_DIR" && docker compose pull) ||
        die "could not pull the board image; if the message says denied, the package ghcr.io/tkcs-lab/tld-board must be made public once by the repository owner (CONTRIBUTING.md, first release)"

    empty=""
    for name in TLD_BOARD_OWNER_PASSPHRASE TLD_BOARD_PUBLIC_ORIGIN; do
        if ! has_value "$name"; then
            empty="$empty $name"
        fi
    done
    if [ -n "$empty" ]; then
        say "the board is not started: empty in $BOARD_DIR/.env:$empty"
        say "fill them in, then run: cd $BOARD_DIR && docker compose up -d"
        return 0
    fi
    (cd "$BOARD_DIR" && docker compose up -d) || die "could not start the board"
    say "board started from $BOARD_DIR"
}

case "${1:-cli}" in
    cli) install_cli ;;
    board) install_board ;;
    uninstall) uninstall_cli ;;
    *)
        printf '%s\n' "usage: install.sh [cli|board|uninstall]" >&2
        exit 2
        ;;
esac
