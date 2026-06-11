// Configurable public-site URL prefix. The canonical route group lives at
// `(public)/p` (served at /p); operators may expose it under a different prefix
// (e.g. /s or /sites) by setting NEXT_PUBLIC_SLUG_PREFIX — we then rewrite that
// prefix onto the canonical /p routes. Default keeps everything at /p.
const SLUG_PREFIX = (process.env.NEXT_PUBLIC_SLUG_PREFIX || '/p').replace(/\/+$/, '') || '/p';

// Backend host for the SSR/proxy rewrite. Shared Docker networks host a `backend`
// service per app, so the bare `backend` name clashes — use the unique per-app host
// from INTERNAL_API_URL (docker-compose sets http://${APP_NAME}-backend:8000).
const INTERNAL_API = process.env.INTERNAL_API_URL || 'http://backend:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
    // instrumentationHook is enabled by default in Next.js 16 — no config needed
    // Prevents Next.js from 308-redirecting /api/v1/foo/ → /api/v1/foo before
    // the rewrite proxy can handle it. Without this, FastAPI's trailing-slash
    // redirect sends the browser to http://backend:8000/... (internal hostname).
    skipTrailingSlashRedirect: true,
    async rewrites() {
        const rewrites = [
            {
                source: '/api/v1/:path*',
                destination: `${INTERNAL_API}/api/v1/:path*` // Proxy to Backend Service (unique per-app host)
            }
        ];
        // Map a custom public prefix onto the canonical /p route group.
        if (SLUG_PREFIX !== '/p') {
            rewrites.push(
                { source: SLUG_PREFIX, destination: '/p' },
                { source: `${SLUG_PREFIX}/:path*`, destination: '/p/:path*' }
            );
        }
        return rewrites;
    },
    async redirects() {
        // Discord launches the Activity at the mapped ROOT url and appends its own
        // query params (frame_id, instance_id, channel_id, …). Root `/` is the
        // dashboard (not framable), so send Discord's iframe to the Activity hub.
        // This is a server-side redirect — it runs before any framing/CSP applies,
        // and the destination /activity/* carries the frame-ancestors CSP below.
        // Discord's query params are preserved automatically for the SDK handshake.
        return [
            {
                source: '/',
                has: [{ type: 'query', key: 'frame_id' }],
                destination: '/activity/inicio',
                permanent: false,
            },
        ];
    },
    async headers() {
        // Discord Embedded App SDK Activities load the page inside an iframe on
        // discord.com. Scope a permissive frame-ancestors CSP to the /activity
        // route group ONLY and omit X-Frame-Options there (its ALLOW-FROM form
        // is deprecated/ignored; frame-ancestors is authoritative). Every other
        // route keeps the framework's default (no framing).
        return [
            {
                source: '/activity/:path*',
                headers: [
                    {
                        key: 'Content-Security-Policy',
                        value: 'frame-ancestors https://discord.com https://*.discord.com',
                    },
                    {
                        // Activity HTML is rebuilt every deploy (new JS chunk hashes).
                        // Without this, Next serves it with s-maxage=1y and Discord/CDN
                        // caches the old shell forever — new code never reaches the client.
                        key: 'Cache-Control',
                        value: 'no-store, must-revalidate',
                    },
                ],
            },
        ];
    }
};

export default nextConfig;
