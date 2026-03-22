#!/usr/bin/env bash
# devctl - Install pre-built binary from GitHub releases
# Usage: curl -fsSL https://raw.githubusercontent.com/WorkIndia-Private/wi-devctl/main/install.sh | bash
#
# Private repo: GITHUB_TOKEN must be exported (not just set) before running:
#   export GITHUB_TOKEN=ghp_xxx
#   curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" \
#     "https://api.github.com/repos/WorkIndia-Private/wi-devctl/contents/install.sh?ref=main" | bash
set -e

DEVCTL_VERSION="${DEVCTL_VERSION:-latest}"
GITHUB_OWNER="${GITHUB_OWNER:-WorkIndia-Private}"
GITHUB_REPO="${GITHUB_REPO:-wi-devctl}"
INSTALL_DIR=""
STEP=0

log_step() {
  STEP=$((STEP + 1))
  echo "[devctl] [$STEP/5] $*" >&2
}

# Debug: show token status (not the value)
[ "${DEVCTL_DEBUG:-0}" = "1" ] && echo "[devctl] GITHUB_TOKEN: ${GITHUB_TOKEN:+set (${#GITHUB_TOKEN} chars)}" >&2

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
  elif [ -w /usr/local/bin ] 2>/dev/null; then
    echo "/usr/local/bin"
  else
    mkdir -p "$HOME/.local/bin"
    echo "$HOME/.local/bin"
  fi
}

# Append export PATH line to shell profiles if the dir is not already in PATH.
# Only needed when falling back to ~/.local/bin (standard locations are already on PATH).
ensure_path_in_profiles() {
  local dir="$1"
  local export_line="export PATH=\"$dir:\$PATH\""
  local added=0
  for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    [ -f "$rc" ] || continue
    if ! grep -qF "$dir" "$rc" 2>/dev/null; then
      printf '\n# Added by devctl installer\n%s\n' "$export_line" >> "$rc"
      echo "  → Added to $rc" >&2
      added=1
    fi
  done
  if [ "$added" = "0" ]; then
    echo "  → $dir already in shell profiles" >&2
  fi
}

# Resolve version tag (latest -> v1.0.0) and get download URL
get_download_url() {
  local asset_name="$1"

  local api_url
  if [ "$DEVCTL_VERSION" = "latest" ]; then
    api_url="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest"
  else
    api_url="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/tags/${DEVCTL_VERSION}"
  fi

  echo "  → Fetching release info..." >&2

  local curl_args=(-fsSL -H "Accept: application/vnd.github.v3+json")
  if [ -n "$GITHUB_TOKEN" ]; then
    curl_args+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl_args+=("$api_url")

  local json
  json=$(curl "${curl_args[@]}" 2>&1) || {
    echo "❌ Failed to fetch release." >&2
    echo "$json" | head -5 >&2
    echo "  For private repos: export GITHUB_TOKEN=ghp_xxx" >&2
    exit 1
  }

  if [ -z "$json" ] || [ "$(echo "$json" | head -c 1)" != "{" ]; then
    echo "❌ Invalid response (check token/repo access):" >&2
    echo "$json" | head -3 >&2
    echo "  For private repos: export GITHUB_TOKEN=ghp_xxx" >&2
    exit 1
  fi

  # Check for API error response (401, 404 - have "message" at top level, no "tag_name")
  if ! echo "$json" | grep -q '"tag_name"'; then
    local msg
    msg=$(echo "$json" | grep -o '"message": *"[^"]*"' | sed 's/.*: *"\(.*\)"/\1/' | head -1)
    if [ -n "$msg" ]; then
      echo "❌ API error: $msg" >&2
      echo "  Token needs 'repo' scope. Export: GITHUB_TOKEN=ghp_xxx" >&2
      exit 1
    fi
  fi

  local version download_url
  if command -v jq >/dev/null 2>&1; then
    version=$(echo "$json" | jq -r '.tag_name // empty')
    download_url=$(echo "$json" | jq -r --arg name "$asset_name" '
      .assets[] | select(.name == $name) | .browser_download_url
    ')
  else
    version=$(echo "$json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d.get('tag_name',''))
" 2>/dev/null)
    download_url=$(echo "$json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
name='$asset_name'
for a in d.get('assets',[]):
    if a.get('name')==name:
        print(a.get('browser_download_url',''))
        break
" 2>/dev/null)
  fi

  if [ -z "$version" ] || [ "$version" = "null" ]; then
    echo "❌ No release found. Push a tag (e.g. v1.0.0) to create a release." >&2
    exit 1
  fi

  # browser_download_url works for public repos; for private, we need the API asset URL with Accept header
  if [ -z "$download_url" ] || [ "$download_url" = "null" ]; then
    # Fallback: construct URL (works for public repos)
    download_url="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${version}/${asset_name}"
    echo "  → Asset $asset_name, trying direct URL" >&2
  else
    echo "  → Found $asset_name" >&2
  fi

  echo "$download_url"
}

download_and_install() {
  local url="$1" output="$2" err

  echo "  → Downloading..." >&2

  local curl_args=(-fL -o "$output")
  if [ -n "$GITHUB_TOKEN" ]; then
    curl_args+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl_args+=(-H "Accept: application/octet-stream")
  curl_args+=("$url")

  err=$(curl "${curl_args[@]}" 2>&1) || {
    echo "❌ Download failed." >&2
    echo "$err" | head -3 >&2
    echo "  For private repos: export GITHUB_TOKEN=ghp_xxx" >&2
    rm -f "$output"
    exit 1
  }
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

  log_step "Resolving download URL"
  local url
  url=$(get_download_url "$asset_name")

  local tmpfile
  tmpfile=$(mktemp)
  trap 'rm -f "$tmpfile"' EXIT

  log_step "Downloading binary"
  download_and_install "$url" "$tmpfile"

  log_step "Installing"
  chmod +x "$tmpfile"
  mv "$tmpfile" "${INSTALL_DIR}/${binary_name}"

  echo "✅ Installed to ${INSTALL_DIR}/${binary_name}" >&2

  # Persist PATH for ~/.local/bin fallback (standard locations are already on PATH)
  if [ "$INSTALL_DIR" = "$HOME/.local/bin" ]; then
    ensure_path_in_profiles "$INSTALL_DIR"
  fi

  # Ensure install dir is in PATH for the current shell session
  export PATH="${INSTALL_DIR}:$PATH"
  "${INSTALL_DIR}/${binary_name}" --version >&2 || {
    echo "❌ Binary verification failed" >&2
    exit 1
  }

  echo "" >&2
  echo "🚀 devctl ready. Run: devctl --help" >&2

  if [ "$INSTALL_DIR" = "$HOME/.local/bin" ]; then
    echo "  Restart your shell (or run: source ~/.zshrc) for PATH to take effect." >&2
  fi
}

main "$@"
