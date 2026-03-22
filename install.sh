#!/usr/bin/env bash
set -e

DEVCTL_VERSION="${DEVCTL_VERSION:-latest}"
GITHUB_OWNER="${GITHUB_OWNER:-WorkIndia-Private}"
GITHUB_REPO="${GITHUB_REPO:-wi-devctl}"
INSTALL_DIR=""
STEP=0

log_step() {
  STEP=$((STEP + 1))
  echo "[devctl] [$STEP/6] $*" >&2
}

detect_platform() {
  local os arch
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
  if [ -d "/opt/homebrew/bin" ] && [ -w "/opt/homebrew/bin" ]; then
    echo "/opt/homebrew/bin"
  elif [ -w /usr/local/bin ]; then
    echo "/usr/local/bin"
  else
    mkdir -p "$HOME/.local/bin"
    echo "$HOME/.local/bin"
  fi
}

get_asset_url() {
  local asset_name="$1"

  if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ GITHUB_TOKEN is required" >&2
    exit 1
  fi

  local api_url
  if [ "$DEVCTL_VERSION" = "latest" ]; then
    api_url="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest"
  else
    api_url="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/tags/${DEVCTL_VERSION}"
  fi

  echo "  → Fetching release metadata..." >&2

  local json
  json=$(curl -fsSL \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "$api_url") || {
      echo "❌ Failed to fetch release metadata (check token / repo access)" >&2
      exit 1
    }

  if [ -z "$json" ]; then
    echo "❌ Empty response from GitHub API" >&2
    exit 1
  fi

  local url

  if command -v jq >/dev/null 2>&1; then
    url=$(echo "$json" | jq -r --arg name "$asset_name" '
      .assets[] | select(.name == $name) | .url
    ')
  else
    url=$(echo "$json" | python3 - "$asset_name" <<'PY'
import json, sys
data = json.load(sys.stdin)
name = sys.argv[1]
for a in data.get("assets", []):
    if a.get("name") == name:
        print(a.get("url", ""))
        break
PY
)
  fi

  url=$(echo "$url" | tr -d '\r\n ')

  if [ -z "$url" ] || [ "$url" = "null" ]; then
    echo "❌ Asset not found: $asset_name" >&2
    echo "Available assets:" >&2
    echo "$json" | grep '"name":' >&2 || true
    exit 1
  fi

  echo "  → Resolved asset: $asset_name" >&2
  echo "  → Download URL: $url" >&2

  echo "$url"
}

download_binary() {
  local url="$1"
  local output="$2"

  echo "  → Downloading binary..." >&2

  if command -v curl >/dev/null 2>&1; then
    curl -fL \
      -H "Authorization: token $GITHUB_TOKEN" \
      -H "Accept: application/octet-stream" \
      "$url" \
      -o "$output" || {
        echo "❌ Download failed (auth or asset issue)" >&2
        exit 1
      }
  else
    wget \
      --header="Authorization: token $GITHUB_TOKEN" \
      --header="Accept: application/octet-stream" \
      -O "$output" \
      "$url"
  fi
}

main() {
  log_step "Detecting platform"
  local platform
  platform=$(detect_platform)
  echo "  → $platform" >&2

  log_step "Choosing install directory"
  INSTALL_DIR=$(choose_install_dir)
  echo "  → $INSTALL_DIR" >&2

  local binary_name="devctl"
  [[ "$platform" == windows* ]] && binary_name="devctl.exe"

  local asset_name="devctl-${platform}"
  [[ "$platform" == windows* ]] && asset_name="${asset_name}.exe"

  log_step "Resolving asset"
  local url
  url=$(get_asset_url "$asset_name")

  local tmpfile
  tmpfile=$(mktemp)

  log_step "Downloading binary"
  download_binary "$url" "$tmpfile"

  log_step "Installing binary"
  chmod +x "$tmpfile"
  mv "$tmpfile" "${INSTALL_DIR}/${binary_name}"

  log_step "Verifying installation"
  echo "✅ Installed to ${INSTALL_DIR}/${binary_name}" >&2

  "${INSTALL_DIR}/${binary_name}" --version || {
    echo "❌ Binary verification failed" >&2
    exit 1
  }

  echo "🚀 devctl ready. Try: devctl --help" >&2
}

main "$@"