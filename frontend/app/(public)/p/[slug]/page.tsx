'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { useTranslation } from '@/lib/i18n';
import { withPublicPage } from '@/lib/components/with-public-page';

interface PublicSite {
    slug: string;
    id: string;
    name: string;
    icon: string | null;
    features: string[];
}

// Baseline public per-server site shell (Level 0 / PUBLIC_DATA), keyed on the
// configurable slug prefix (default /p/<slug>). Plugins extend this surface by
// installing public pages into this route group (see the plugin `public_pages`
// manifest section). No login is required and no platform chrome is rendered.
function PublicSitePage() {
    const { t } = useTranslation();
    const slug = String(useParams().slug || '');
    const [site, setSite] = useState<PublicSite | null>(null);
    const [error, setError] = useState(false);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!slug) return;
        apiClient
            .getPublicSite(slug)
            .then(setSite)
            .catch(() => setError(true))
            .finally(() => setLoading(false));
    }, [slug]);

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center text-muted-foreground">
                {t('publicSite.loading')}
            </div>
        );
    }

    if (error || !site) {
        return (
            <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
                <h1 className="text-2xl font-bold">{t('publicSite.notFound')}</h1>
                <p className="mt-2 text-muted-foreground">{t('publicSite.notFoundDesc')}</p>
            </div>
        );
    }

    return (
        <div className="min-h-screen">
            <header className="border-b border-border bg-card/50 backdrop-blur-sm">
                <div className="container mx-auto px-4 h-16 flex items-center gap-3">
                    {site.icon && (
                        <img src={site.icon} alt={site.name} className="w-9 h-9 rounded-full" />
                    )}
                    <h1 className="text-xl font-bold">{site.name}</h1>
                </div>
            </header>
            <main className="container mx-auto px-4 py-8">
                {/* Plugin public pages render their content under this shell. */}
            </main>
        </div>
    );
}

export default withPublicPage(PublicSitePage);
