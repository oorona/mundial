import { NextRequest, NextResponse } from 'next/server';

// Configurable public-site prefix (default /p), mirrored from next.config.
const SLUG_PREFIX = (process.env.NEXT_PUBLIC_SLUG_PREFIX || '/p').replace(/\/+$/, '') || '/p';

// Paths that must always be accessible regardless of setup state. The public
// site surface (/p or the configured prefix) and the Discord Activity iframe
// (/activity) render their own state and must never be bounced to /setup —
// in particular an Activity loaded inside Discord cannot follow a redirect.
const ALWAYS_ALLOWED = ['/setup', '/_next', '/favicon', '/api/', '/activity', '/p', SLUG_PREFIX];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Never intercept static assets, Next.js internals, or API routes
  if (ALWAYS_ALLOWED.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  try {
    // Call the backend health/setup-state endpoint via the internal Next.js proxy.
    // INTERNAL_API_URL is set server-side in Docker; in the browser it's empty (relative).
    const internalBase = process.env.INTERNAL_API_URL || '';
    const res = await fetch(`${internalBase}/api/v1/setup/state`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    });

    if (res.ok) {
      const data = await res.json();

      // Setup not complete → redirect everything to /setup
      if (data.setup_mode === true && pathname !== '/setup') {
        return NextResponse.redirect(new URL('/setup', request.url));
      }

      // Setup complete → don't let anyone sit on /setup page
      if (data.setup_mode === false && pathname === '/setup') {
        return NextResponse.redirect(new URL('/', request.url));
      }
    }
  } catch {
    // If the backend is unreachable (e.g., still starting), allow through —
    // the page itself will handle the degraded state.
  }

  return NextResponse.next();
}

export const config = {
  // Run on all page routes, skip static files and API routes
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
