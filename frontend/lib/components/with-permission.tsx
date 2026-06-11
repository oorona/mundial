'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ChevronLeft } from 'lucide-react';
import { usePermissions } from '../hooks/use-permissions';
import { PermissionLevel } from '../permissions';
import { useAuth } from '@/lib/auth-context';
import { useTranslation } from '@/lib/i18n';

export function withPermission<P extends object>(
    Component: React.ComponentType<P>,
    requiredLevel: PermissionLevel
) {
    return function WithPermissionComponent(props: P) {
        const params = useParams();
        const router = useRouter();
        const guildId = params?.guildId as string | undefined;

        // Use hook
        const { hasAccess, loading, error } = usePermissions(guildId);
        const { user, loading: authLoading } = useAuth();
        const { t } = useTranslation();

        useEffect(() => {
            if (!loading && !authLoading) {
                // If level is public, we are fine.
                if (requiredLevel <= PermissionLevel.PUBLIC_DATA) return;

                // If user not logged in and L2+ required -> Redirect Login
                if (!user) {
                    router.push('/login');
                    return;
                }

                // If logged in but no access -> Redirect Access Denied
                if (!hasAccess(requiredLevel)) {
                    // Check if it was an error (403) or just level mismatch
                    // API returns 403 if totally denied.
                    // If we have "LEVEL_2" but need "AUTHORIZED", hasAccess returns false.
                    router.push('/access-denied');
                }
            }
        }, [loading, authLoading, hasAccess, requiredLevel, router, user]);

        if (loading || authLoading) {
            return (
                <div className="min-h-screen flex items-center justify-center bg-gray-900 text-white">
                    <div className="animate-pulse">{t('common.checkingPermissions')}</div>
                </div>
            );
        }

        // If we have access, render
        // Note: useEffect handles redirect, but we might render briefly.
        // If we want strict guard, return null if no access.
        if (requiredLevel > PermissionLevel.PUBLIC_DATA && !user) return null;
        if (requiredLevel > PermissionLevel.PUBLIC_DATA && !hasAccess(requiredLevel)) return null;

        return (
            <div>
                <div className="max-w-7xl mx-auto px-4 md:px-8 pt-4 pb-0">
                    <Link
                        href="/"
                        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors group"
                    >
                        <ChevronLeft size={15} className="group-hover:-translate-x-0.5 transition-transform" />
                        {t('common.dashboard')}
                    </Link>
                </div>
                {/* Suspense boundary lets inner pages use useSearchParams safely */}
                <Suspense fallback={null}>
                    <Component {...props} />
                </Suspense>
            </div>
        );
    };
}
