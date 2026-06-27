# Telefon / Uzak Erişim (Tailscale)

Paneli telefondan veya evden uzaktayken açmanın **güvenli** yolu. Panelde kimlik
doğrulama (şifre) **yoktur**; bu yüzden portları doğrudan internete açmak yerine,
yalnızca **senin cihazlarının** eriştiği özel bir ağ (Tailscale VPN) kullanırız.

## Neden Tailscale
- **Hiçbir port internete açılmaz** → panel dışarıdan görünmez, kimse işlemlerine erişemez.
- **Her yerden çalışır** (mobil veri, başka WiFi).
- **Ücretsiz**, tek kullanıcı için ~5 dakikalık kurulum, bakım yok.
- Şifre sistemi/domain/HTTPS uğraşına gerek kalmaz.

## Kurulum

### 1) Sunucuda (panelin docker'la çalıştığı makine)
```bash
bash scripts/setup-tailscale.sh
```
Script Tailscale'i kurar, ağa bağlar ve erişeceğin adresi (`http://<tailscale-ip>:3000`)
yazar. İlk kezse tarayıcıda açılan linkle (Google/GitHub hesabı yeter) giriş yaparsın.

> Elle yapmak istersen:
> ```bash
> curl -fsSL https://tailscale.com/install.sh | sh
> sudo tailscale up
> tailscale ip -4        # erişim IP'si (ör. 100.92.14.3)
> ```

### 2) Telefonda
1. App Store / Google Play'den **Tailscale** uygulamasını kur.
2. **Sunucudakiyle aynı hesapla** giriş yap, bağlantıyı aç (toggle ON).
3. Tarayıcıda script'in yazdığı adresi aç: **`http://<tailscale-ip>:3000`**
4. iPhone: Safari → Paylaş → **Ana Ekrana Ekle** → uygulama gibi açılır.
   Android: Chrome menüsü → **Ana ekrana ekle**.

Bu kadar. API adresi (`:8000`) panel tarafından otomatik aynı host'tan çözülür —
ekstra ayar gerekmez (bkz. `frontend/lib/api.ts`).

## Güvenlik notları
- Tailscale IP'si (`100.x.x.x`) yalnızca senin tailnet'indeki cihazlardan erişilir;
  internete açık **değildir**.
- Docker portları `0.0.0.0`'da yayınlandığı için tailnet IP'si onlara ulaşır; ekstra
  port yönlendirme gerekmez.
- Sunucuda güvenlik duvarı (ufw) açıksa tailscale arayüzüne izin ver:
  ```bash
  sudo ufw allow in on tailscale0
  ```
- Bağlantıyı kapatmak: `sudo tailscale down` (tekrar açmak: `sudo tailscale up`).

## Ne zaman şifre/HTTPS gerekir
Tailscale tek başına yeterlidir (senin cihazların dışında kimse erişemez). Ancak
ileride paneli **bir domain'den herkese açık** sunmak ya da **başka birine** vermek
istersen, panele giriş şifresi (kimlik doğrulama) eklenmelidir — bu durumda söyle,
basit bir giriş koruması ekleyebiliriz.

## Gelişmiş (opsiyonel): tek HTTPS adresi
Tailscale "Serve" ile paneli tailnet içinde HTTPS'li tek bir adresten sunabilirsin.
Bu durumda API'yi de aynı host/porttan proxylemen ve `.env`'e
`NEXT_PUBLIC_API_URL=https://<makine>.<tailnet>.ts.net/api` verip frontend'i bir kez
yeniden derlemen gerekir. Çoğu kullanıcı için gerekmez; düz `:3000` erişimi yeterlidir.
