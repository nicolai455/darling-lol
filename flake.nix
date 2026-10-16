{
  description = "Darling League of Legends - experimental macOS LoL runner on Linux via Darling";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # Python environment with dependencies required by tooling
      pythonEnv = pkgs.python3.withPackages (
        ps: with ps; [
          requests
          urllib3
          websocket-client
          pillow
        ]
      );

      # Common runtime libraries needed by Darling, Vulkan, X11, Audio, and graphics
      buildDeps = with pkgs; [
        # Build tools & compilers
        cmake
        gnumake
        ninja
        pkg-config
        clang
        lld
        llvm
        llvm.dev
        llvmPackages.clang-unwrapped
        bison
        flex
        git
        git-lfs
        curl
        unzip
        file
        patchelf

        # System & core libraries
        glibc
        glibc.dev
        glibc.static
        zlib
        zlib.dev
        libffi
        libffi.dev
        libbsd
        libbsd.dev
        libmd
        libmd.dev
        libcap
        libelf
        fuse
        systemdLibs # libudev
        dbus
        libxml2
        openssl
        libedit

        # Graphics & Display
        libGL
        libGLU
        mesa
        vulkan-headers
        vulkan-loader
        vulkan-tools
        cairo
        freetype
        fontconfig
        libpng
        libpng.dev
        libjpeg
        libjpeg.dev
        libtiff
        giflib
        ffmpeg

        # X11 & input
        xorgproto
        libx11
        libxext
        libxrandr
        libxcursor
        libxinerama
        libxcomposite
        libxdamage
        libxfixes
        libxi
        libxrender
        libxtst
        libxcb
        xcbutil
        xcbutilwm
        xcbutilimage
        xcbutilkeysyms
        xcbutilrenderutil
        libxkbfile
        libxkbcommon

        # Audio
        pulseaudio
        libpulseaudio
        alsa-lib

        # Python
        pythonEnv
      ];

      # FHS environment for building and running Darling and League of Legends.
      # Darling requires root/multitasking mount & namespace semantics, /usr/local layout,
      # and dynamically compiled overlays. An FHS environment provides the standard standard
      # filesystem hierarchies (/usr/include, /usr/lib, /usr/bin) and native dynamic linker.
      darlingLolFhs = pkgs.buildFHSEnv {
        name = "darling-lol-fhs";
        targetPkgs = pkgs: buildDeps;
        multiPkgs = pkgs: [ pkgs.glibc ];

        extraOutputsToInstall = [ "dev" "out" ];

        extraBwrapArgs = [
          "--bind-try" (''$'' + ''{HOME}/.local/share/darling-lol/usr-local'') "/usr-local"
        ];

        extraBuildCommands = ''
          mkdir -p bin usr/bin
          rm -f bin/clang bin/clang++ usr/bin/clang usr/bin/clang++
          ln -sfn /usr-local $out/usr/local
          cat << 'EOF' > usr/bin/clang
#!/usr/bin/env bash
is_darwin=0
for a in "$@"; do
  if [[ "$a" == *darwin* ]] || [[ "$a" == *apple* ]] || [[ "$a" == *macosx* ]]; then
    is_darwin=1
    break
  fi
done
if [[ "$is_darwin" -eq 1 ]]; then
  exec ${pkgs.llvmPackages.clang-unwrapped}/bin/clang "$@"
else
  exec ${pkgs.clang}/bin/clang -idirafter /usr/include "$@"
fi
EOF
          chmod +x usr/bin/clang

          cat << 'EOF' > usr/bin/clang++
#!/usr/bin/env bash
is_darwin=0
for a in "$@"; do
  if [[ "$a" == *darwin* ]] || [[ "$a" == *apple* ]] || [[ "$a" == *macosx* ]]; then
    is_darwin=1
    break
  fi
done
if [[ "$is_darwin" -eq 1 ]]; then
  exec ${pkgs.llvmPackages.clang-unwrapped}/bin/clang++ "$@"
else
  exec ${pkgs.clang}/bin/clang++ -idirafter /usr/include "$@"
fi
EOF
          chmod +x usr/bin/clang++
          cp -f usr/bin/clang bin/clang
          cp -f usr/bin/clang++ bin/clang++
        '';

        profile = ''
          export DPREFIX="''${DPREFIX:-$HOME/.darling}"
          export LC_ALL=C.UTF-8
          export LANG=C.UTF-8
          export PATH="/usr/local/bin:''${PATH:-}"
          export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/share/pkgconfig:/usr/lib/pkgconfig:/usr/lib64/pkgconfig:/usr/share/pkgconfig:''${PKG_CONFIG_PATH:-}"
          export CMAKE_PREFIX_PATH="/usr/local:/usr:/usr/lib/cmake/llvm:''${CMAKE_PREFIX_PATH:-}"
          unset NIX_LDFLAGS NIX_CFLAGS_COMPILE NIX_HARDENING_ENABLE CPATH LIBRARY_PATH
        '';

        runScript = pkgs.writeShellScript "darling-lol-run" ''
          if [ $# -eq 0 ]; then
            exec bash
          else
            exec "$@"
          fi
        '';
      };

      # Wrapper script package to run scripts directly
      darlingLol = pkgs.stdenv.mkDerivation {
        pname = "darling-lol";
        version = "0.1.0";
        src = ./.;

        nativeBuildInputs = [
          pkgs.makeWrapper
        ];

        installPhase = ''
          runHook preInstall

          mkdir -p $out/bin $out/share/darling-lol $out/share/icons/hicolor/scalable/apps $out/share/icons/hicolor/128x128/apps $out/share/pixmaps $out/share/applications
          cp -r * $out/share/darling-lol/
          cp darling-lol.svg $out/share/icons/hicolor/scalable/apps/darling-lol.svg
          cp darling-lol.png $out/share/icons/hicolor/128x128/apps/darling-lol.png
          cp darling-lol.png $out/share/pixmaps/darling-lol.png
          cp darling-lol.svg $out/share/pixmaps/darling-lol.svg

          # Install configured launcher
          substitute ./darling-lol-launcher.sh $out/bin/darling-lol \
            --replace-fail "@SHARE_DIR@" "$out/share/darling-lol" \
            --replace-fail "@FHS_BIN@" "${darlingLolFhs}/bin/darling-lol-fhs"
          chmod +x $out/bin/darling-lol

          makeWrapper ${darlingLolFhs}/bin/darling-lol-fhs $out/bin/darling-lol-shell \
            --add-flags "--"

          makeWrapper ${darlingLolFhs}/bin/darling-lol-fhs $out/bin/darling-lol-build \
            --run "cd \''${XDG_DATA_HOME:-\$HOME/.local/share}/darling-lol" \
            --add-flags "./scripts/build.sh"

          cat << 'DESKTOP_EOF' > $out/share/applications/darling-lol.desktop
[Desktop Entry]
Categories=Game;
Comment=Play League of Legends macOS client on Linux via Darling
Exec=darling-lol
GenericName=MOBA Game
Icon=darling-lol
Keywords=League;LoL;Riot;Darling;
Name=League of Legends
StartupWMClass=RiotClientServices
Terminal=false
Type=Application
Version=1.5
DESKTOP_EOF

          runHook postInstall
        '';

        meta = with pkgs.lib; {
          description = "Tooling and patches to run macOS League of Legends on Linux with Darling";
          homepage = "https://github.com/lucannez64/darling-lol";
          license = licenses.gpl3Only;
          platforms = [ "x86_64-linux" ];
        };
      };
    in
    {
      packages.${system} = {
        darling-lol = darlingLol;
        darling-lol-fhs = darlingLolFhs;
        default = darlingLol;
      };

      apps.${system} = {
        default = {
          type = "app";
          program = "${darlingLol}/bin/darling-lol";
        };
        shell = {
          type = "app";
          program = "${darlingLolFhs}/bin/darling-lol-fhs";
        };
        installer = {
          type = "app";
          program = "${darlingLol}/bin/darling-lol-installer";
        };
        build = {
          type = "app";
          program = "${darlingLol}/bin/darling-lol-build";
        };
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = buildDeps ++ [ darlingLolFhs ];
        shellHook = ''
          echo "Darling LoL build & development environment loaded."
          echo "Tip: Run 'darling-lol-fhs' to enter the FHS build sandbox if standard paths (/usr/include, /usr/lib) are needed."
        '';
      };
    };
}
