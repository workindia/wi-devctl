#!/usr/bin/env bash
# devctl installer
# Usage: curl -fsSL https://YOUR_DOMAIN/install.sh | bash

set -e

DEVCTL_VERSION="${DEVCTL_VERSION:-latest}"
GITHUB_OWNER="${DEVCTL_GITHUB_OWNER:-WorkIndia-Private}"
GITHUB_REPO="${DEVCTL_GITHUB_REPO:-wi-devctl}"
INSTALL_DIR=""

detect_platform() {
  local os
  local arch
  os=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m | tr '[:upper:]' '[:lower:]')

  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
  esac

  case "$os" in
    darwin) os="darwin" ;;
    linux) os="linux" ;;
    mingw*|msys*|cygwin*) os="windows" ;;
    *) echo "Unsupported OS: $os" >&2; exit 1 ;;
  esac

  echo "${os}-${arch}"
}

choose_install_dir() {
  local bin_dir
  if [ -w /usr/local/bin ]; then
    bin_dir="/usr/local/bin"
  elif [ -w "$HOME/.local/bin" ]; then
    bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
  else
    bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    echo "Installing to $bin_dir (add to PATH if needed)" >&2
  fi
  echo "$bin_dir"
}

main() {
  local platform
  platform=$(detect_platform)
  INSTALL_DIR=$(choose_install_dir)

  local binary_name="devctl"
  if [ "$platform" = "windows-amd64" ] || [ "$platform" = "windows-arm64" ]; then
    binary_name="devctl.exe"
  fi

  local asset_name="devctl-${platform}"
  if [[ "$platform" == windows* ]]; then
    asset_name="${asset_name}.exe"
  fi

  local url
  if [ "$DEVCTL_VERSION" = "latest" ]; then
    url="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest/download/${asset_name}"
  else
    url="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${DEVCTL_VERSION}/${asset_name}"
  fi

  echo "Downloading devctl for ${platform}..." >&2
  local tmpfile
  tmpfile=$(mktemp)
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$tmpfile" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$tmpfile" "$url"
  else
    echo "curl or wget required" >&2
    exit 1
  fi

  chmod +x "$tmpfile"
  mv "$tmpfile" "${INSTALL_DIR}/${binary_name}"
  echo "Installed to ${INSTALL_DIR}/${binary_name}" >&2
  "${INSTALL_DIR}/${binary_name}" --version
}

main "$@"
