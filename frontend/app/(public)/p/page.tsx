'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/app/api-client';
import { useTranslation } from '@/lib/i18n';
import { withPublicPage } from '@/lib/components/with-public-page';

interface ProjectInfo {
    name?: string;
    description?: string;
    slug_prefix?: string;
}

// Generic, project-wide public landing page (Level 0). Not guild-scoped.
// Lives at the configured public prefix root (default /p).
function ProjectLandingPage() {
    const { t } = useTranslation();
    const [info, setInfo] = useState<ProjectInfo | null>(null);

    useEffect(() => {
        apiClient.getProjectInfo().then(setInfo).catch(() => setInfo({}));
    }, []);

    return (
        <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
            <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-indigo-500 to-purple-500 bg-clip-text text-transparent">
                {info?.name || ''}
            </h1>
            <p className="mt-4 max-w-xl text-muted-foreground">
                {info?.description || t('publicSite.projectTagline')}
            </p>
        </div>
    );
}

export default withPublicPage(ProjectLandingPage);
