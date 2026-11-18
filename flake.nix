{
  description = "music-Ai — AI と一緒に曲を作る・替え歌を作るツールキット";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # 実行に必要な Python ライブラリ（requirements.txt に対応）。
      # imageio-ffmpeg は使わず、ffmpeg 本体を PATH に置く（audio_io.py が PATH の ffmpeg も探す）。
      # demucs（ボーカル分離・任意）は torch が大きいので含めない。
      pythonFor = pkgs: pkgs.python3.withPackages (ps: [
        ps.numpy
        ps.pyyaml
        ps.yt-dlp
      ]);

      # 外部コマンド: ffmpeg（MP3 書き出し・音声取り込み）、git（バージョン履歴）
      runtimeToolsFor = pkgs: [
        pkgs.ffmpeg
        pkgs.git
      ];
    in
    {
      packages = forAllSystems (pkgs: rec {
        default = musicai;

        # ソースを Nix ストアに置き、`musicai` コマンドで動かす。
        # ストアは書き込めないので、曲などの保存先は MUSICAI_HOME（既定: ~/.local/share/music-ai）にする。
        musicai = pkgs.stdenvNoCC.mkDerivation {
          pname = "music-ai";
          version = "0.1.0";
          src = self;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;

          installPhase = ''
            runHook preInstall
            mkdir -p $out/share/music-ai $out/bin
            cp -r musicai schemas songs specs lyrics prompts $out/share/music-ai/
            makeWrapper ${pythonFor pkgs}/bin/python $out/bin/musicai \
              --add-flags "-m musicai" \
              --set PYTHONPATH $out/share/music-ai \
              --prefix PATH : ${pkgs.lib.makeBinPath (runtimeToolsFor pkgs)} \
              --run 'export MUSICAI_HOME="''${MUSICAI_HOME:-''${XDG_DATA_HOME:-$HOME/.local/share}/music-ai}"' \
              --run 'mkdir -p "$MUSICAI_HOME"' \
              --run '[ -d "$MUSICAI_HOME/.git" ] || git init -q "$MUSICAI_HOME" >/dev/null 2>&1 || true'
            runHook postInstall
          '';

          meta = {
            description = "AI と一緒に曲を作る・替え歌を作るツールキット（ブラウザで操作するアプリ付き）";
            license = pkgs.lib.licenses.mit;
            mainProgram = "musicai";
            platforms = systems;
          };
        };
      });

      apps = forAllSystems (pkgs: {
        # nix run .          → musicai コマンド（例: nix run . -- validate songs）
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.musicai}/bin/musicai";
          meta.description = "musicai コマンド";
        };
        # nix run .#app      → アプリ（ブラウザ画面）を起動
        app = {
          type = "app";
          program = "${pkgs.writeShellScript "musicai-app" ''
            exec ${self.packages.${pkgs.stdenv.hostPlatform.system}.musicai}/bin/musicai app "$@"
          ''}";
          meta.description = "アプリ（ブラウザ画面）を起動";
        };
        # nix run .#mcp      → AI アプリ向けの MCP サーバ（標準入出力）
        mcp = {
          type = "app";
          program = "${pkgs.writeShellScript "musicai-mcp" ''
            exec ${self.packages.${pkgs.stdenv.hostPlatform.system}.musicai}/bin/musicai mcp "$@"
          ''}";
          meta.description = "MCP サーバ（標準入出力）";
        };
      });

      # nix develop: チェックアウトしたフォルダで、python -m musicai … をそのまま動かせる開発環境
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [ (pythonFor pkgs) ] ++ runtimeToolsFor pkgs;
          shellHook = ''
            echo "music-Ai 開発環境: python -m musicai app / python -m unittest discover -s tests"
          '';
        };
      });

      # nix flake check: 全テストを、ビルド用のサンドボックスの中で実行する
      checks = forAllSystems (pkgs: {
        tests =
          pkgs.runCommand "music-ai-tests"
            {
              nativeBuildInputs = [ (pythonFor pkgs) ] ++ runtimeToolsFor pkgs;
            }
            ''
              cp -r ${self} src
              chmod -R u+w src
              cd src
              export HOME=$TMPDIR
              python -m unittest discover -s tests
              touch $out
            '';
      });
    };
}
