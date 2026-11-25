# Maintainer: barsuk <barsuk228332@users.noreply.github.com>
pkgname=umulauncher
pkgver=0.1.0
pkgrel=1
pkgdesc='GTK4 launcher for Windows games on Linux powered by umu-launcher'
arch=('any')
url='https://github.com/barsuk228332/umu-launcher-gtk'
license=('GPL-3.0-or-later')
depends=(
  'python'
  'python-gobject'
  'gtk4'
  'libadwaita'
  'umu-launcher'
)
optdepends=(
  'gamescope: run games in a nested Wayland/X11 compositor'
  'mangohud: FPS and hardware overlay'
  'winetricks: install Windows components into a prefix'
  'xdg-utils: open folders from the UI'
)
makedepends=('gettext')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('b66b10c781eec37028c1e74772bce2158ed5980a94bdebe8e0c8f06414a04ce7')

build() {
  cd "$srcdir/umu-launcher-gtk-$pkgver"
  make i18n
}

package() {
  cd "$srcdir/umu-launcher-gtk-$pkgver"

  install -d "$pkgdir/usr/lib/$pkgname" "$pkgdir/usr/bin" \
    "$pkgdir/usr/share/applications" "$pkgdir/usr/share/licenses/$pkgname"

  cp -r umulauncher "$pkgdir/usr/lib/$pkgname/"
  find "$pkgdir/usr/lib/$pkgname" -name '__pycache__' -type d -prune -exec rm -rf {} +

  cat > "$pkgdir/usr/bin/$pkgname" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/lib/umulauncher${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m umulauncher "$@"
EOF
  chmod 755 "$pkgdir/usr/bin/$pkgname"

  install -Dm644 data/io.github.umulauncher.Umulauncher.desktop \
    "$pkgdir/usr/share/applications/io.github.umulauncher.Umulauncher.desktop"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
