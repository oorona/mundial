'use client';

import Link from 'next/link';
import { ShieldAlert } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { useTranslation } from '@/lib/i18n';

function AccessDeniedContent() {
    const searchParams = useSearchParams();
    const error = searchParams.get('error');
    const { t } = useTranslation();

    const message = error === 'access_denied'
        ? t('accessDenied.cancelledMsg')
        : t('accessDenied.noPermissionMsg');

    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-background text-foreground p-4">
            <div className="flex flex-col items-center max-w-md text-center space-y-6">
                <div className="rounded-full bg-destructive/10 p-6">
                    <ShieldAlert className="h-16 w-16 text-destructive" />
                </div>

                <h1 className="text-3xl font-bold tracking-tight">{t('accessDenied.title')}</h1>

                <p className="text-muted-foreground text-lg">{message}</p>

                {error && error !== 'access_denied' && (
                    <p className="text-destructive text-sm font-mono bg-destructive/10 px-3 py-2 rounded-lg">
                        {t('accessDenied.errorLabel', { error })}
                    </p>
                )}

                <div className="flex gap-4 pt-4">
                    <Link
                        href="/"
                        className="rounded-xl bg-secondary hover:bg-secondary/80 px-6 py-2.5 text-sm font-semibold text-secondary-foreground transition-colors border border-border"
                    >
                        {t('accessDenied.returnHome')}
                    </Link>
                    <Link
                        href="/login"
                        className="rounded-xl bg-primary hover:bg-primary/90 px-6 py-2.5 text-sm font-semibold text-primary-foreground transition-colors"
                    >
                        {t('accessDenied.tryAgain')}
                    </Link>
                </div>
            </div>
        </div>
    );
}

export default function AccessDeniedPage() {
    return (
        <Suspense fallback={<div>{/* loading */}</div>}>
            <AccessDeniedContent />
        </Suspense>
    );
}
