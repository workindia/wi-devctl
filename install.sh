#!/usr/bin/env bash
# devctl - Install pre-built binary from GitHub releases
# Usage: curl -fsSL https://raw.githubusercontent.com/WorkIndia-Private/wi-devctl/main/install.sh | bash
#
# Private repo: GITHUB_TOKEN must be exported (not just set) before running:
#   export GITHUB_TOKEN=ghp_xxx
#   curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" \
#     "https://api.github.com/repos/WorkIndia-Private/wi-devctl/contents/install.sh?ref=main" | bash
#
# One-shot ai-kit + background sync (after binary install):
#   export DEVCTL_AI_KIT_REPO=https://github.com/your-org/ai-collab-kit
#   export DEVCTL_AI_KIT_BACKGROUND_SYNC=1   # optional: launchd (macOS) / cron (Linux)
#   curl -fsSL ... | bash
#
# Build devctl from a git branch instead of downloading a release:
#   export DEVCTL_BRANCH=feature/my-branch
#   export DEVCTL_AI_KIT_REPO=https://github.com/your-org/ai-collab-kit   # optional
#   export DEVCTL_AI_KIT_REPO_BRANCH=feature/configs                      # optional
#   curl -fsSL ... | bash
# Private collab repo: ensure git can clone it (SSH key or credential helper); GITHUB_TOKEN here
# only affects downloading devctl, not git clone.
set -e

DEVCTL_VERSION="${DEVCTL_VERSION:-latest}"
GITHUB_OWNER="${GITHUB_OWNER:-WorkIndia-Private}"
GITHUB_REPO="${GITHUB_REPO:-wi-devctl}"
INSTALL_DIR=""
STEP=0
TOTAL_STEPS=5

log_step() {
  STEP=$((STEP + 1))
  echo "[devctl] [$STEP/${TOTAL_STEPS}] $*" >&2
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
  # Only use a system directory if it is writable AND already on PATH.
  # Directories may exist without being on PATH (e.g. /opt/homebrew/bin on Intel Macs).
  for dir in "/opt/homebrew/bin" "/usr/local/bin"; do
    if [ -d "$dir" ] && [ -w "$dir" ] && [[ ":$PATH:" == *":$dir:"* ]]; then
      echo "$dir"
      return
    fi
  done
  mkdir -p "$HOME/.local/bin"
  echo "$HOME/.local/bin"
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
    # Use the API asset URL (.url), not .browser_download_url.
    # For private repos, browser_download_url redirects to a pre-signed CDN URL that
    # rejects the Authorization header. The API URL + Accept: application/octet-stream
    # lets GitHub handle auth cleanly before redirecting.
    download_url=$(echo "$json" | jq -r --arg name "$asset_name" '
      .assets[] | select(.name == $name) | .url
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
        print(a.get('url',''))
        break
" 2>/dev/null)
  fi

  if [ -z "$version" ] || [ "$version" = "null" ]; then
    echo "❌ No release found. Push a tag (e.g. v1.0.0) to create a release." >&2
    exit 1
  fi

  if [ -z "$download_url" ] || [ "$download_url" = "null" ]; then
    echo "❌ Asset $asset_name not found in release $version." >&2
    exit 1
  fi

  echo "  → Found $asset_name" >&2
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

build_devctl_from_branch() {
  local branch="$1" output="$2"
  local build_dir clone_url built

  if ! command -v git >/dev/null 2>&1; then
    echo "❌ git is required to build from branch. Install git and re-run." >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 is required to build from branch." >&2
    exit 1
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "❌ Python 3.11+ is required to build from branch." >&2
    exit 1
  fi
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "❌ pip is required to build from branch." >&2
    exit 1
  fi

  build_dir=$(mktemp -d)
  clone_url="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git"
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    clone_url="https://${GITHUB_TOKEN}@github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git"
  fi

  echo "  → Cloning ${GITHUB_OWNER}/${GITHUB_REPO} (branch: ${branch})..." >&2
  if ! git clone --depth 1 --branch "$branch" "$clone_url" "$build_dir/src" 2>&1; then
    echo "  → Shallow clone failed, trying full clone..." >&2
    rm -rf "$build_dir/src"
    if ! git clone "$clone_url" "$build_dir/src" 2>&1; then
      rm -rf "$build_dir"
      echo "❌ Clone failed. For private repos: export GITHUB_TOKEN=ghp_xxx" >&2
      exit 1
    fi
    if ! git -C "$build_dir/src" checkout "$branch" 2>&1; then
      rm -rf "$build_dir"
      echo "❌ Checkout failed for branch: ${branch}" >&2
      exit 1
    fi
  fi

  echo "  → Building binary (PyInstaller)..." >&2
  if ! (
    cd "$build_dir/src"
    python3 -m pip install -q setuptools wheel pyinstaller pyyaml click certifi
    python3 -m pip install -q -e . --no-build-isolation
    pyinstaller --onefile --name devctl --paths src \
      --hidden-import certifi --collect-all certifi \
      src/devctl/cli/main.py
  ); then
    rm -rf "$build_dir"
    echo "❌ Build failed." >&2
    exit 1
  fi

  built="$build_dir/src/dist/devctl"
  [[ "$output" == *.exe ]] && built="${built}.exe"
  if [ ! -f "$built" ]; then
    rm -rf "$build_dir"
    echo "❌ Built binary not found at $built" >&2
    exit 1
  fi

  chmod +x "$built"
  mv "$built" "$output"
  rm -rf "$build_dir"
  echo "✅ Built and installed to $output" >&2
}

warmup_devctl_binary() {
  local devctl_bin="$1"
  # PyInstaller --onefile unpacks on each launch; a light run before setup reduces
  # first-run extraction flakes (especially right after branch build).
  echo "  → Warming up binary (--help)..." >&2
  "$devctl_bin" --help >/dev/null 2>&1 || true
  sleep 1
}

run_ai_kit_setup_with_retry() {
  local devctl_bin="$1"
  shift
  local attempt
  for attempt in 1 2 3; do
    if "$devctl_bin" "$@"; then
      return 0
    fi
    if [ "$attempt" -lt 3 ]; then
      echo "  → ai-kit setup failed (attempt ${attempt}/3), retrying in 2s..." >&2
      sleep 2
    fi
  done
  return 1
}

main() {
  TOTAL_STEPS=5
  [ -n "${DEVCTL_AI_KIT_REPO:-}" ] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
  [ "${DEVCTL_AI_KIT_BACKGROUND_SYNC:-}" = "1" ] && TOTAL_STEPS=$((TOTAL_STEPS + 1))

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

  if [ -n "${DEVCTL_BRANCH:-}" ]; then
    log_step "Building from branch (DEVCTL_BRANCH=${DEVCTL_BRANCH})"
    build_devctl_from_branch "${DEVCTL_BRANCH}" "${INSTALL_DIR}/${binary_name}"
  else
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
  fi

  # Persist PATH for ~/.local/bin fallback (standard locations are already on PATH)
  if [ "$INSTALL_DIR" = "$HOME/.local/bin" ]; then
    ensure_path_in_profiles "$INSTALL_DIR"
  fi

  # Ensure install dir is in PATH for the current shell session
  export PATH="${INSTALL_DIR}:$PATH"
  local ver_output
  ver_output=$("${INSTALL_DIR}/${binary_name}" --version 2>&1) || {
    echo "❌ Binary verification failed (non-zero exit)" >&2
    exit 1
  }
  if [ -z "$ver_output" ]; then
    echo "❌ Binary verification failed (no output from --version; binary may be wrong arch or corrupt)" >&2
    exit 1
  fi
  echo "  → $ver_output" >&2

  local devctl_bin="${INSTALL_DIR}/${binary_name}"

  if [ -n "${DEVCTL_AI_KIT_REPO:-}" ]; then
    log_step "ai-kit setup (DEVCTL_AI_KIT_REPO)"
    if ! command -v git >/dev/null 2>&1; then
      echo "❌ git is required for ai-kit setup. Install git and re-run, or run manually:" >&2
      echo "   $devctl_bin ai-kit setup --repo <url>" >&2
      exit 1
    fi
    local setup_args=(ai-kit setup --repo "$DEVCTL_AI_KIT_REPO")
    if [ -n "${DEVCTL_AI_KIT_REPO_BRANCH:-}" ]; then
      setup_args+=(--branch "$DEVCTL_AI_KIT_REPO_BRANCH")
    fi
    warmup_devctl_binary "$devctl_bin"
    if ! run_ai_kit_setup_with_retry "$devctl_bin" "${setup_args[@]}"; then
      echo "❌ ai-kit setup failed after 3 attempts." >&2
      exit 1
    fi
    echo "  → ai-kit setup complete" >&2
  fi

  if [ "${DEVCTL_AI_KIT_BACKGROUND_SYNC:-}" = "1" ]; then
    log_step "Background sync (DEVCTL_AI_KIT_BACKGROUND_SYNC=1)"
    case "$platform" in
      darwin-*|linux-*)
        if ! "$devctl_bin" ai-kit install-background-sync; then
          echo "❌ install-background-sync failed." >&2
          exit 1
        fi
        ;;
      *)
        echo "  → Skipping background sync (supported on macOS and Linux only)" >&2
        ;;
    esac
  fi

  echo "" >&2
  echo "🚀 devctl ready. Run: devctl --help" >&2

  if [ "$INSTALL_DIR" = "$HOME/.local/bin" ]; then
    echo "  Restart your shell (or run: source ~/.zshrc) for PATH to take effect." >&2
  fi
}

main "$@"
