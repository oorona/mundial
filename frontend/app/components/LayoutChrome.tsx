'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Header } from './Header';

// The public slug prefix is configurable (default /p). The browser URL keeps
// the configured prefix even though next.config rewrites it onto the canonical
// (public)/p route group, so chrome detection checks both.
const SLUG_PREFIX = process.env.NEXT_PUBLIC_SLUG_PREFIX || '/p';

function isChromeless(pathname: string): boolean {
    // Public landing + about — they have their own branding/CTAs; the platform header
    // there is just the bot name + theme toggle, which adds little (theme is auto-detected).
    if (pathname === '/welcome' || pathname === '/about') return true;
    // Discord Activity iframe — must be full-bleed, no platform header. Match the
    // activity ANYWHERE in the path, because inside Discord the Activity loads behind a
    // proxy prefix (e.g. "/.proxy/activity/inicio"), so a startsWith('/activity/') check
    // misses it and the platform header (with its own theme toggle) leaks into the iframe.
    if (pathname === '/activity' || pathname.includes('/activity')) return true;
    // Public per-server sites + project landing — render their own branding.
    if (pathname === '/p' || pathname.startsWith('/p/')) return true;
    if (SLUG_PREFIX !== '/p' && (pathname === SLUG_PREFIX || pathname.startsWith(SLUG_PREFIX + '/'))) {
        return true;
    }
    return false;
}

/**
 * Decides whether a route renders inside the platform chrome (header + padded
 * main) or full-bleed. Public-site and Activity routes are full-bleed; every
 * other route keeps the existing dashboard chrome.
 */
// Are we running inside the Discord Activity iframe? Discord serves it from a
// *.discordsays.com proxy origin and always appends a `frame_id` query param — and the
// path there may NOT contain "/activity", so path matching alone can't detect it. This
// is the authoritative signal; computed on the client after mount to avoid SSR mismatch.
function inDiscordActivity(): boolean {
    if (typeof window === 'undefined') return false;
    try {
        return window.location.hostname.endsWith('discordsays.com')
            || /[?&](frame_id|instance_id)=/.test(window.location.search);
    } catch {
        return false;
    }
}

export function LayoutChrome({ children }: { children: React.ReactNode }) {
    const pathname = usePathname() || '';
    // Start from the path-based check (SSR-safe), then refine on the client to also catch
    // the Discord Activity even when it loads behind a proxy path without "/activity".
    const [chromeless, setChromeless] = useState<boolean>(() => isChromeless(pathname));
    useEffect(() => {
        setChromeless(isChromeless(pathname) || inDiscordActivity());
    }, [pathname]);

    // IMPORTANT: keep `{children}` in the SAME tree position whether or not we show the
    // header. When the Activity flips chromeless→true after mount (Discord proxy detection),
    // a branch that returns a different structure would REMOUNT children — re-running the
    // one-time Discord SDK handshake and losing the guild session. Toggling only the Header
    // and the <main> padding keeps children mounted across the flip.
    return (
        <div className="flex flex-col min-h-screen bg-background">
            {!chromeless && <Header />}
            <main className={chromeless ? 'flex-1' : 'flex-1 overflow-y-auto p-4 md:p-8'}>{children}</main>
        </div>
    );
}
