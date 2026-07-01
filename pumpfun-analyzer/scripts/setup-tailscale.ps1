# Altay Analysis Bot — Tailscale ile guvenli telefon/uzak erisim (WINDOWS).
#
# Sen Windows + Docker Desktop kullaniyorsun; bu script Tailscale'i WINDOWS host'una
# kurar (Docker/WSL icine DEGIL). Panele internete port acmadan, yalnizca senin
# cihazlarinin eristigi ozel ag (VPN) ile telefondan baglanirsin.
#
# PowerShell'de calistir (gerekirse Yonetici olarak):
#   powershell -ExecutionPolicy Bypass -File scripts\setup-tailscale.ps1
#
# Sonra telefonuna Tailscale uygulamasini kurup AYNI hesapla giris yap; script'in
# yazdigi http://<tailscale-ip>:3000 adresinden panele gir.

$ErrorActionPreference = "Stop"
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "3000" }
$BackendPort  = if ($env:BACKEND_PORT)  { $env:BACKEND_PORT }  else { "8000" }
$ts = "C:\Program Files\Tailscale\tailscale.exe"

function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }

# 1) Tailscale kurulu mu? Degilse resmi kurulumu indir ve calistir.
if (-not (Test-Path $ts)) {
  Say "Tailscale kuruluyor (resmi kurulum)..."
  $exe = Join-Path $env:TEMP "tailscale-setup.exe"
  Invoke-WebRequest -Uri "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe" -OutFile $exe
  Say "Kurulum baslatiliyor (Yonetici izni isteyebilir)... Bitince devam edilecek."
  Start-Process -FilePath $exe -Wait
} else {
  Say "Tailscale zaten kurulu - atlaniyor."
}

if (-not (Test-Path $ts)) {
  Write-Host "Kurulum bulunamadi. Tailscale'i elle kur: https://tailscale.com/download/windows" -ForegroundColor Yellow
  exit 1
}

# 2) Aga baglan (ilk kezse tarayicida giris linki acilir).
Say "Tailscale agina baglaniliyor... (ilk kezse acilan tarayici ile giris yap)"
& $ts up

# 3) Guvenlik duvari: 3000/8000 portlarina gelen baglantilara izin ver. Bu, Windows
#    + Docker Desktop'ta telefonun "adresi acmiyor" sorununun ana sebebidir.
Say "Guvenlik duvari kurallari ekleniyor (port $FrontendPort / $BackendPort)..."
try {
  Get-NetFirewallRule -DisplayName "Altay Bot*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName "Altay Bot Panel $FrontendPort" -Direction Inbound -LocalPort $FrontendPort -Protocol TCP -Action Allow -Profile Any -ErrorAction Stop | Out-Null
  New-NetFirewallRule -DisplayName "Altay Bot API $BackendPort"   -Direction Inbound -LocalPort $BackendPort  -Protocol TCP -Action Allow -Profile Any -ErrorAction Stop | Out-Null
  Write-Host "Guvenlik duvari kurallari eklendi." -ForegroundColor Green
} catch {
  Write-Host "Guvenlik duvari kurali EKLENEMEDI - bu script'i YONETICI olarak calistir," -ForegroundColor Yellow
  Write-Host "veya elle ekle (Yonetici PowerShell):" -ForegroundColor Yellow
  Write-Host "  New-NetFirewallRule -DisplayName 'Altay Bot Panel' -Direction Inbound -LocalPort $FrontendPort -Protocol TCP -Action Allow" -ForegroundColor Yellow
  Write-Host "  New-NetFirewallRule -DisplayName 'Altay Bot API'   -Direction Inbound -LocalPort $BackendPort  -Protocol TCP -Action Allow" -ForegroundColor Yellow
}

# 4) Erisim adresini yazdir.
$ip = (& $ts ip -4 | Select-Object -First 1)
if (-not $ip) {
  Write-Host "Tailscale IP alinamadi. Tailscale uygulamasindan baglantiyi kontrol et." -ForegroundColor Yellow
  exit 1
}

Say "HAZIR! Telefonundan (Tailscale uygulamasi acikken) su adrese gir:"
Write-Host "`n   http://$($ip):$FrontendPort   <- PANEL`n" -ForegroundColor Green
Write-Host "   (API otomatik http://$($ip):$BackendPort'e gider - ekstra ayar yok)`n"

Write-Host @"
Sonraki adimlar:
  1) Telefonuna App Store / Play'den "Tailscale" kur, AYNI hesapla giris yap, baglantiyi ac.
  2) Telefon tarayicisinda http://$($ip):$FrontendPort adresini ac.
  3) iPhone: Safari -> Paylas -> "Ana Ekrana Ekle" = uygulama gibi acilir.

Notlar:
  - Bu IP yalnizca SENIN cihazlarindan erisilir; internete acik DEGIL.
  - Docker Desktop portlari Windows host'una yayinlar; Tailscale IP'si onlara ulasir.
  - Telefon baglanamazsa: Docker Desktop calisiyor mu + Windows Guvenlik Duvari
    Tailscale'e izin veriyor mu kontrol et.
  - Baglantiyi kapatmak: Tailscale uygulamasindan "Disconnect".
"@
