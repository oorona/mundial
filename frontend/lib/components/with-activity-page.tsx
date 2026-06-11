'use client';

import React, { Suspense } from 'react';

/**
 * HOC for **Discord Activity** pages (Embedded App SDK iframe) served from the
 * `/activity/<plugin>` route group.
 *
 * Activity pages are NOT dashboard pages: they perform no `withPermission`
 * check (auth is the SDK handshake — see `lib/activity.ts` →
 * `authenticateActivity`) and render no platform chrome (`LayoutChrome` already
 * goes full-bleed for `/activity`). This wrapper only provides a Suspense
 * boundary so the page can use `useSearchParams`.
 *
 * The plugin validator recognises `export default withActivityPage(Page)` as
 * the sanctioned export for pages declared in a plugin's `activity_pages`
 * manifest section, and exempts those files from the `withPermission` rule
 * while permitting `@discord/embedded-app-sdk` imports.
 */
export function withActivityPage<P extends object>(Component: React.ComponentType<P>) {
    return function ActivityPage(props: P) {
        return (
            <Suspense fallback={null}>
                {/* Mobile only: push content below Discord's own exit/minimize controls at
                    the top of the Activity, so the first line of text isn't hidden behind
                    them. Desktop has its own top tab bar, so no extra space there. */}
                <div className="pt-[max(3.25rem,env(safe-area-inset-top))] md:pt-0">
                    <Component {...props} />
                </div>
            </Suspense>
        );
    };
}
