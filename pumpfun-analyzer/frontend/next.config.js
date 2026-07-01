/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Tarayıcı API'yi AYNI kökenden (panelin açıldığı host:port) ister: `/api/*`.
  // Next.js sunucusu bunu docker ağı üzerinden backend'e proxy'ler. Böylece panel
  // hangi adresten açılırsa açılsın (localhost, LAN, Tailscale, herhangi bir port)
  // ayrı bir :8000 portuna / localhost'a gerek kalmadan veri gelir.
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN || "http://backend:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
module.exports = nextConfig;
