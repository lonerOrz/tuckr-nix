# module.nix
{
  config,
  lib,
  pkgs,
  ...
}:

with lib;

let
  cfg = config.tuckr;

  # 设置环境变量来运行tuckr
  userTuckrActivatorScript = pkgs.writeShellScript "user-tuckr-activator" ''
    tuckr_bin_path="$1"
    dot_path_raw="$2"
    backup_suffix="$3"
    disabled_groups_csv="$4"

    if [[ "$dot_path_raw" == "~"* ]]; then
      export TUCKR_HOME="$HOME/${dot_path_raw: 1}"
    else
      export TUCKR_HOME="$dot_path_raw"
    fi
    export TUCKR_TARGET="$HOME"
    export TUCKR_BACKUP_SUFFIX="$backup_suffix"
    export TUCKR_DISABLED_GROUPS="$disabled_groups_csv"

    echo "Running tuckr for user $$USER:"
    echo "  TUCKR_HOME: $$TUCKR_HOME"
    echo "  TUCKR_TARGET: $$TUCKR_TARGET"
    echo "  TUCKR_BACKUP_SUFFIX: $$TUCKR_BACKUP_SUFFIX"
    echo "  TUCKR_DISABLED_GROUPS: $$TUCKR_DISABLED_GROUPS"
    echo "  tuckr binary: $$tuckr_bin_path"

    PYTHON_ARGS=()
    PYTHON_ARGS+=(--suffix "$backup_suffix")
    if [[ -n "$disabled_groups_csv" ]]; then
      IFS=',' read -ra groups <<< "$disabled_groups_csv"
      for g in "$${groups[@]}"; do
        PYTHON_ARGS+=(--exclude "$$g")
      done
    fi

    if [ -x "$tuckr_bin_path" ]; then
      "$tuckr_bin_path" status --json | "${pkgs.python3}/bin/python3" "$${cfg.autoResolveScript}" "$${PYTHON_ARGS[@]}"
      if [ $$? -ne 0 ]; then
        echo "Error: tuckr auto-resolution failed for user $$USER." >&2
      fi
    else
      echo "Error: tuckr binary not found or not executable at $$tuckr_bin_path for user $$USER." >&2
      exit 1
    fi
  '';

in
{
  options.tuckr = {
    enable = mkEnableOption "Enable multi-user tuckr management";

    autoResolveScript = mkOption {
      type = types.path;
      default = /etc/nixos/tuckr_auto_resolve.py;
      description = "Absolute path to the tuckr_auto_resolve.py script.";
    };

    users = mkOption {
      type = types.attrsOf (
        types.submodule (_: {
          options = {
            enable = mkEnableOption "Enable tuckr for this user";

            dotPath = mkOption {
              type = types.str;
              description = "TUCKR_HOME path for this user (e.g., ~/.config/tuckr)";
            };

            backupSuffix = mkOption {
              type = types.str;
              default = "bak";
              description = "Backup suffix for tuckr.";
            };

            group = mkOption {
              type = types.attrsOf (
                types.submodule (_: {
                  options = {
                    enable = mkEnableOption "Enable this group for tuckr";
                  };
                })
              );
              default = { };
            };
          };
        })
      );
      default = { };
      description = "Per-user tuckr configuration";
    };
  };

  config = mkIf cfg.enable {
    systemd.user.services."tuckr-auto-resolver@" = {
      description = "Tuckr Auto Resolver for %i";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.coreutils}/bin/true";
      };
    };

    system.activationScripts.postRebuildTuckr = lib.mkAfter ''
      echo "Activating multi-user tuckr management..."
      ${lib.concatStringsSep "\n" (
        lib.mapAttrsToList (
          username: userConfig:
          lib.optionalString userConuserTuckrActivatorScriptfig.enable ''
                      echo "  Enabling linger for user ${username}..."
                      ${pkgs.loginctl}/bin/loginctl enable-linger ${username} || true

                      echo "  Preparing systemd user service override for ${username}..."
                      override_dir="/run/systemd/user/tuckr-auto-resolver@${username}.service.d"
                      override_file="$override_dir/override.conf"
                      ${pkgs.sudo}/bin/sudo -u ${username} ${pkgs.coreutils}/bin/mkdir -p "$override_dir"

                      exec_start_cmd="${userTuckrActivatorScript} \
                        ${lib.escapeShellArg "${userConfig.package}/bin/tuckr"} \
                        ${lib.escapeShellArg userConfig.dotPath} \
                        ${lib.escapeShellArg userConfig.backupSuffix} \
                        ${
                          lib.escapeShellArg (
                            lib.concatStringsSep "," (
                              builtins.attrValues (lib.mapAttrs (_: v: if v.enable then _ else "") userConfig.group)
                            )
                          )
                        }"

                      ${pkgs.sudo}/bin/sudo -u ${username} ${pkgs.coreutils}/bin/tee "$override_file" > /dev/null <<EOF
            [Service]
            ExecStart=
            ExecStart=${exec_start_cmd}
            EOF

                      ${pkgs.sudo}/bin/sudo -u ${username} ${pkgs.systemd}/bin/systemctl --user daemon-reload
                      ${pkgs.sudo}/bin/sudo -u ${username} ${pkgs.systemd}/bin/systemctl --user start tuckr-auto-resolver@${username}.service
          ''
        ) cfg.users
      )}
      echo "Multi-user tuckr management activation complete."
    '';
  };
}
