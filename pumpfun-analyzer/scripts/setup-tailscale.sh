#!/usr/bin/env bash
#
# Altay Analysis Bot — Tailscale ile güvenli telefon/uzak erişim kurulumu.
#
# Tailscale, panele İNTERNETE PORT AÇMADAN, yalnızca senin cihazlarının (telefon,
# dizüstü) eriştiği özel bir ağ (VPN) kurar. Panelde şifre olmadığı için en güvenli
# uzak erişim yöntemi budur.
#
# Bu script SUNUCUDA (panelin docker'la çalıştığı makinede) çalıştırılır:
#   bash scripts/setup-tailscale.sh
#
# Sonra telefonuna Tailscale uygulamasını kurup AYNI hesapla giriş yap; script'in
# yazdığı http://<tailscale-ip>:3000 adresinden panele gir.
#
set -euo pipefail

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

say() { printf "\n\033[1;36m%s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m%s\033[0m\n" "$*"; }

# sudo gerekiyorsa otomatik kullan (root değilsek)
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else
    warn "root değilsin ve sudo yok. Lütfen root olarak çalıştır."; exit 1
  fi
fi

# 1) Tailscale kurulu mu? Değilse resmi script ile kur.
if ! command -v tailscale >/dev/null 2>&1; then
  say "Tailscale kuruluyor (resmi kurulum script'i)…"
  curl -fsSL https://tailscale.com/install.sh | $SUDO sh
else
  say "Tailscale zaten kurulu — atlanıyor."
fi

# 2) Ağa bağlan. İlk kez ise tarayıcıda açılacak bir giriş linki basar.
say "Tailscale ağına bağlanılıyor… (ilk kezse aşağıdaki linkle giriş yap)"
$SUDO tailscale up

# 3) Erişim adresini yazdır.
TS_IP="$($SUDO tailscale ip -4 2>/dev/null | head -n1 || true)"
if [ -z "${TS_IP}" ]; then
  warn "Tailscale IP alınamadı. 'tailscale status' ile bağlantıyı kontrol et."
  exit 1
fi

say "✅ Hazır! Telefonundan (Tailscale uygulaması açıkken) şu adrese gir:"
printf "\n   \033[1;32mhttp://%s:%s\033[0m   ← PANEL\n" "$TS_IP" "$FRONTEND_PORT"
printf "   (API otomatik http://%s:%s'e gider — ekstra ayar yok)\n\n" "$TS_IP" "$BACKEND_PORT"

cat <<EOF
Sonraki adımlar:
  1) Telefonuna App Store / Play'den "Tailscale" kur, AYNI hesapla giriş yap, bağlantıyı aç.
  2) Telefon tarayıcısında yukarıdaki http://${TS_IP}:${FRONTEND_PORT} adresini aç.
  3) iPhone: Safari → Paylaş → "Ana Ekrana Ekle" = uygulama gibi açılır.

Notlar:
  • Bu IP yalnızca SENİN tailnet'indeki cihazlardan erişilir; internete açık DEĞİL.
  • Docker portları 0.0.0.0'da yayınlandığından tailnet IP'si onlara ulaşır.
  • Sunucuda güvenlik duvarı (ufw) varsa tailscale arayüzüne izin ver:
        ${SUDO} ufw allow in on tailscale0
  • Bağlantıyı kapatmak için:  ${SUDO} tailscale down
EOF
