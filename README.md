# Tuckr NixOS Integration

This Nix flake provides a robust and automated solution for managing dotfiles for multiple users on NixOS systems. It is centered around `tuckr` and leverages NixOS modules and systemd services for automation.

## Why Tuckr?

1. **Convention over configuration**: Follows a declarative management philosophy, reducing tedious configuration.
2. **Link status visibility**: You can easily check which dotfiles have been successfully linked.
3. **JSON output for link status**: Useful for further processing and automation.

## Features

- **Multi-user dotfiles management**: Easily configure and manage `tuckr` for each user on NixOS.
- **Automatic conflict handling**: Existing files or directories are automatically backed up before attempting to create symbolic links.
- **Systemd integration**: Works closely with systemd services, automatically handling dotfiles with logs after system boot or rebuild.
- **Configurable backups**: Custom suffixes can be specified for backup files and directories.
- **Instant configuration application**: Changes take effect automatically after a system rebuild—no manual intervention needed.

## Installation and Usage

1. **Add the input to your `flake.nix`**:

```nix
{
  description = "Your NixOS configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    tuckr-nix.url = "github:lonerOrz/tuckr-nix";
  };

  outputs = { self, nixpkgs, tuckr-nix, ... }: {
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ./configuration.nix
        tuckr-nix.tuckrModules.tuckr
      ];
    };
  };
}
```

2. **Configure users in `configuration.nix`**:

```nix
{ config, pkgs, lib, ... }:

{
  tuckr.enable = true;

  tuckr.users = {
    loner = {
      enable = true;
      dotPath = "~/.config/tuckr";
      backupSuffix = "bakup";
      group = {
        fzf.enable = true;
        nvim.enable = false;
      };
    };

    # Other users
    # anotheruser = { ... };
  };
}
```

3. **Rebuild the system**:

```bash
sudo nixos-rebuild switch
```

After rebuilding, the `tuckr-auto-resolver-<username>` systemd service will automatically activate and manage the configured users' dotfiles.

## TODO

1. Declarative generation of dotfiles
2. Support for Nix store
3. Additional automation strategies
4. Git integration

## Contributing

Contributions are welcome! You can submit issues or pull requests.

## License

GPL-3.0-or-later

For the specific license of the tuckr binary, please refer to `tuckr.nix`.
