'use client';

import React, { Suspense } from 'react';

/**
 * HOC for **public** pages (Level 0 / PUBLIC) served from the `(public)` route
 * group — per-server slug sites and the generic project landing page.
 *
 * Unlike `withPermission`, it performs NO authentication check and renders NO
 * "back to dashboard" breadcrumb: a public site is not a dashboard page. It
 * simply wraps the page in a Suspense boundary so it can use `useSearchParams`.
 *
 * The plugin validator recognises `export default withPublicPage(Page)` as the
 * sanctioned export for pages declared in a plugin's `public_pages` manifest
 * section (they are exempt from the `withPermission` requirement).
 */
export function withPublicPage<P extends object>(Component: React.ComponentType<P>) {
    return function PublicPage(props: P) {
        return (
            <Suspense fallback={null}>
                <Component {...props} />
            </Suspense>
        );
    };
}
