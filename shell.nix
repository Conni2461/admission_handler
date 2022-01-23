let pkgs = import <nixpkgs> { };
in
let
  packageOverrides = pkgs.callPackage ./python-packages.nix { };
python = pkgs.python39.override {
    packageOverrides = self: super: (
      (packageOverrides self super) // {
        pyside2 = super.pyside2;
      }
    );
  };
  pythonWithPackages = python.withPackages (ps: [ ps.Louie ps.pyside2 ]);
in
pkgs.mkShell {
  buildInputs = [ pkgs.qt5.full ];
  nativeBuildInputs = [ pythonWithPackages ];
  shellHook = ''
    exec zsh
  '';
}
