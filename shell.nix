let pkgs = import <nixpkgs> { };
in
let
  python = pkgs.python39;
  pythonWithPackages = python.withPackages (ps: [ ps.pyside2 ]);
in
pkgs.mkShell {
  buildInputs = [ pkgs.qt5.full ];
  nativeBuildInputs = [ pythonWithPackages ];
  shellHook = ''
    exec zsh
  '';
}
