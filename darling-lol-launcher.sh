#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${XDG_DATA_HOME:-$HOME/.local/share}/darling-lol"
SHARE_DIR="@SHARE_DIR@"
FHS_BIN="@FHS_BIN@"
UNSHARE_BIN="@UNSHARE_BIN@"

mkdir -p "$WORKSPACE" "$WORKSPACE/usr-local"
export DISPLAY="${DISPLAY:-:0}"
export EGL_PLATFORM="${EGL_PLATFORM:-x11}"
export DPREFIX="${DPREFIX:-$HOME/.darling}"
export DARLING_HOST_UID="$(id -u)"
export DARLING_HOST_GID="$(id -g)"
export DARLING_WORKSPACE="$WORKSPACE"

# Refresh packaged sources on upgrades; never replace compiled or installed data.
# cp -n left old tools in place forever, hiding fixes from subsequent packages.
for item in docs patches research scripts tests tools upstream LICENSE NOTICE.md README.md requirements.txt; do
  if [ -e "$SHARE_DIR/$item" ]; then
    cp -r --no-preserve=mode,ownership "$SHARE_DIR/$item" "$WORKSPACE/"
  fi
done
cd "$WORKSPACE"

# Map subordinate IDs BEFORE bubblewrap sets no_new_privs. Inside this namespace
# UID 0 is an unprivileged subordinate host ID, never the host's root account.
# Keep the real user mapped to itself for file ownership and guest credentials.
fhs_command=("$UNSHARE_BIN" --user --map-auto --map-current-user --setuid=0 --setgid=0 "$FHS_BIN")

run_in_term() {
  local title="$1"
  shift
  if command -v kitty >/dev/null 2>&1; then
    exec kitty --title "$title" "$@"
  elif command -v foot >/dev/null 2>&1; then
    exec foot --title "$title" "$@"
  elif command -v xterm >/dev/null 2>&1; then
    exec xterm -title "$title" -e "$@"
  else
    exec "$@"
  fi
}

installer=0
if [ "${1:-}" = --installer ]; then
  installer=1
  shift
fi
if [ "$installer" = 0 ] && [ $# -gt 0 ]; then
  exec "${fhs_command[@]}" "$@"
fi

if [ "$installer" = 0 ] && [ -x "$WORKSPACE/usr-local/bin/darling" ] &&
   { [ -e "$DPREFIX/Applications/Riot Client.app" ] || [ -d "$DPREFIX/Users/Shared/Riot Games/Riot Client.app" ]; }; then
  exec "${fhs_command[@]}" ./scripts/run.sh
fi

cat << 'EOF' > "$WORKSPACE/interactive-setup.sh"
#!/usr/bin/env bash
set -euo pipefail
export PATH="${DARLING_RUNNER_DIR:+$DARLING_RUNNER_DIR:}$(pwd)/usr-local/bin:/usr/local/bin:$PATH"
echo "League of Legends macOS runner via Darling (NixOS)"
echo "Workspace: $(pwd)"
echo "Prefix:    ${DPREFIX:-$HOME/.darling}"
echo "Darling runs in an unprivileged user namespace; no sudo or setuid installation."
if [ ! -x "$(pwd)/usr-local/bin/darling" ]; then
  echo "Building Darling requires approximately 40–50 GB disk space."
  read -r -p "Start the build? [Y/n] " REPLY
  case "$REPLY" in n|N) exit 0;; esac
  ./scripts/build.sh
  cmake --install build/darling-src/build
fi
# This is also required when a previous attempt installed only the base runtime.
if [ ! -f build/nix-runtime-ready ]; then
  ./scripts/install-runtime.sh
fi
if [ ! -d "${DPREFIX:-$HOME/.darling}/Users/Shared/Riot Games/Riot Client.app" ]; then
  read -r -p "Region [euw]: " REGION
  ./scripts/installer.sh "${REGION:-euw}"
fi
exec ./scripts/run.sh
EOF
chmod +x "$WORKSPACE/interactive-setup.sh"
run_in_term "League of Legends Setup (Darling)" "${fhs_command[@]}" "$WORKSPACE/interactive-setup.sh"
