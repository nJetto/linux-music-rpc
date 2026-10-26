# Maintainer: nJetto
pkgname=linux-music-rpc
pkgver=1.0.0
pkgrel=1
pkgdesc="MPRIS to Discord Rich Presence bridge for Linux"
arch=('any')
url="https://github.com/nJetto/linux-music-rpc"
license=('MIT')
depends=('python' 'playerctl')
optdepends=('discord: Discord desktop client')
options=('!strip' '!debug')
source=()

package() {
  local libdir="$pkgdir/usr/lib/$pkgname"

  install -d "$libdir"
  cp -a "$startdir/music_rpc" "$libdir/"
  find "$libdir" -type d -name __pycache__ -prune -exec rm -rf {} +

  install -Dm755 "$startdir/packaging/launcher" "$pkgdir/usr/bin/$pkgname"
  install -Dm644 "$startdir/packaging/linux-music-rpc.service" \
    "$pkgdir/usr/lib/systemd/user/$pkgname.service"
  install -Dm644 "$startdir/music_rpc/config.example.ini" \
    "$pkgdir/usr/share/doc/$pkgname/config.example.ini"
  install -Dm644 "$startdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 "$startdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
