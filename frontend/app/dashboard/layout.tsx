'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { registerPlugins } from '../plugins/registry';

// Initialize plugins
registerPlugins();

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const { user, loading } = useAuth();
    const router = useRouter();

    // Global auth check removed - relying on per-page 'withPermission' guards.

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background text-foreground">
                Loading...
            </div>
        );
    }

    return <>{children}</>;
}
