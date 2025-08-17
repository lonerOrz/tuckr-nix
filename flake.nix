{
  description = "Reusable NixOS module for multi-user tuckr management";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      imports = [
        inputs.treefmt-nix.flakeModule
      ];

      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          system,
          ...
        }:
        let
          lib = pkgs.lib;
        in
        {
          packages = {
            default = pkgs.tuckr;
          };

          nixosModules = {
            tuckrModule = import ./module.nix { inherit pkgs; };
          };

          devShells.default = pkgs.mkShell {
            inputsFrom = [ self'.packages.default ];
            packages = with pkgs; [
              # Rust
              cargo
              rustc
              rust-analyzer
              rustfmt
              clippy
              cargo-watch
              cargo-criterion
              # python
              python3
            ];
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs = {
              rustfmt.enable = true;
              alejandra.enable = true;
            };
          };
        };
    };
}
