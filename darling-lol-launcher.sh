#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${XDG_DATA_HOME:-$HOME/.local/share}/darling-lol"
SHARE_DIR="@SHARE_DIR@"
FHS_BIN="@FHS_BIN@"

mkdir -p "$WORKSPACE"

# Sync tooling scripts and upstream definitions into mutable user workspace
for item in docs patches research scripts tests tools upstream LICENSE NOTICE.md README.md requirements.txt; do
  if [ -e "$SHARE_DIR/$item" ]; then
    cp -rn "$SHARE_DIR/$item" "$WORKSPACE/" 2>/dev/null || true
  fi
done

cd "$WORKSPACE"

DARLING_PREFIX="${DPREFIX:-$HOME/.darling}"
DARLING_BIN="/usr/local/bin/darling"
RIOT_CLIENT="$DARLING_PREFIX/Applications/Riot Client.app"
SHARED_CLIENT="$DARLING_PREFIX/Users/Shared/Riot Games/Riot Client.app"

# Helper to find a suitable terminal emulator
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

# If arguments were provided directly, run them within FHS
if [ $# -gt 0 ]; then
  exec "$FHS_BIN" "$@"
fi

# Check if Darling & Riot client are already installed
if [ -e "$RIOT_CLIENT" ] || [ -d "$SHARED_CLIENT" ]; then
  exec "$FHS_BIN" ./scripts/run.sh
fi

# Otherwise, prompt the user in a terminal to run setup/installer
cat << 'EOF' > "$WORKSPACE/interactive-setup.sh"
#!/usr/bin/env bash
set -e
echo "=========================================================="
echo "   League of Legends macOS runner via Darling (NixOS)     "
echo "=========================================================="
echo ""
echo "Workspace: $(pwd)"
echo "Prefix:    ${DPREFIX:-$HOME/.darling}"
echo ""

if ! command -v darling >/dev/null 2>&1; then
  echo "Darling runtime is not yet built/installed."
  echo "Step 1 will build Darling with LoL patches."
  echo "Note: This clones Darling submodules and compiles (~50GB disk)."
  echo ""
  read -p "Would you like to start the build now? [Y/n] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    ./scripts/build.sh
    echo ""
    echo "Installing base runtime to /usr/local (requires sudo inside FHS)..."
    sudo cmake --install build/darling-src/build
    ./scripts/install-runtime.sh
  else
    echo "Aborted."
    exit 0
  fi
fi

if [ ! -d "${DPREFIX:-$HOME/.darling}/Users/Shared/Riot Games/Riot Client.app" ]; then
  echo ""
  echo "Step 2: Fetch and launch Riot Client installer"
  read -p "Enter region [default: euw]: " REGION
  REGION="${REGION:-euw}"
  ./scripts/installer.sh "$REGION"
fi

echo ""
echo "Setup complete! You can now launch League of Legends from your application menu."
read -p "Press Enter to exit..."
EOF
chmod +x "$WORKSPACE/interactive-setup.sh"

run_in_term "League of Legends Setup (Darling)" "$FHS_BIN" "$WORKSPACE/interactive-setup.sh"
