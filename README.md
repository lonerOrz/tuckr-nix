# Tuckr NixOS 集成

这个 Nix flake 提供了一个稳健且自动化的方案，用于在 NixOS 系统上管理多个用户的 dotfiles，核心使用 `tuckr` 进行管理，并通过 NixOS 模块和 systemd 服务实现自动化。

## 为什么用 Tuckr？

1. **约定大于配置**：遵循声明式管理理念，减少繁琐配置。
2. **支持查看链接状态**：可以随时了解哪些 dotfiles 已经成功链接。
3. **提供链接状态 JSON 输出**：便于进一步处理和自动化。

## 特性

- **多用户 dotfiles 管理**：轻松为 NixOS 系统上的每个用户配置和管理 `tuckr`。
- **自动冲突处理**：在发现已有文件或文件夹冲突时自动备份，然后尝试创建符号链接。
- **Systemd 集成**：操作与 systemd 服务紧密结合，系统启动或 rebuild 后自动处理 dotfiles 并保有日志。
- **可配置备份**：可指定自定义后缀用于备份文件和文件夹。
- **即时配置生效**：修改配置后，无需手动操作，系统 rebuild 后即可自动应用。

## 安装与使用

1. **在 `flake.nix` 中添加输入**：

```nix
{
  description = "你的 NixOS 配置";

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

2. **在 `configuration.nix` 中配置用户**：

```nims
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

    # 其他用户
    # anotheruser = { ... };
  };
}
```

3. **重建系统**：

```bash
sudo nixos-rebuild switch
```

重建后，`tuckr-auto-resolver-<username>` systemd 服务会自动激活，管理配置用户的 dotfiles。

## TODO

1. 声明式生成 dotfiles
2. 提供 nix store 支持
3. 增加自动化策略

## 贡献

欢迎贡献！可以提交 issue 或 pull request。

## 许可证

GPL-3.0-or-later

tuckr 二进制具体许可请参考 `tuckr.nix`
