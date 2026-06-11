'use client';

import { useParams } from 'next/navigation';
import { useState, useEffect } from 'react';
import { apiClient } from '@/app/api-client';
import { usePlugins } from '@/app/plugins';
import { usePermissions } from '@/lib/hooks/use-permissions';
import { PermissionLevel } from '@/lib/permissions';
import { withPermission } from '@/lib/components/with-permission';

function PluginPage() {
    const params = useParams();
    const guildId = params.guildId as string;
    const pluginId = params.pluginId as string;
    const { plugins } = usePlugins();

    // Settings state
    const [settings, setSettings] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    const plugin = plugins.find(p => p.id === pluginId);

    useEffect(() => {
        const fetchSettings = async () => {
            if (!guildId) return;
            try {
                const data = await apiClient.getGuildSettings(guildId);
                setSettings(data.settings || {});
            } catch (err) {
                console.error("Failed to load settings for plugin", err);
                // Fallback to empty settings so page still loads (plugin handling)
                setSettings({});
            } finally {
                setLoading(false);
            }
        };
        fetchSettings();
    }, [guildId]);

    if (!plugin) {
        return (
            <div className="p-8 text-center text-gray-400">
                <h1 className="text-xl font-bold mb-2">Plugin Not Found</h1>
                <p>The plugin "{pluginId}" is not registered or does not exist.</p>
            </div>
        );
    }

    if (!plugin.pageComponent) {
        return (
            <div className="p-8 text-center text-gray-400">
                <h1 className="text-xl font-bold mb-2">No Settings Page</h1>
                <p>The plugin "{plugin.name}" does not have a dedicated page.</p>
            </div>
        );
    }

    // Permission Check
    // Default to AUTHORIZED (L3) if not specified for safety
    const requiredLevel = plugin.defaultPermissionLevel ?? PermissionLevel.AUTHORIZED;
    // We can't use the HOC here easily because we are inside the component rendering content dynamically.
    // So we use the hook.
    // Note: usePermissions hook internal logic handles fetching.
    const { hasAccess, loading: permLoading } = usePermissions(guildId);

    if (permLoading || loading) {
        return <div className="p-8 text-muted-foreground">Loading plugin...</div>;
    }

    if (!hasAccess(requiredLevel)) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-center text-muted-foreground">
                <div className="bg-destructive/10 p-4 rounded-full mb-4">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="48"
                        height="48"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="text-destructive"
                    >
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                    </svg>
                </div>
                <h1 className="text-xl font-bold mb-2 text-foreground">Access Denied</h1>
                <p>You do not have permission to access this plugin.</p>
                <p className="text-sm mt-2 font-mono">Required: {PermissionLevel[requiredLevel]}</p>
            </div>
        );
    }

    const PageComponent = plugin.pageComponent;

    // Pass settings to the component
    return <PageComponent guildId={guildId} settings={settings} />;
}

// Minimum outer guard; plugin-specific level is enforced by the inner usePermissions check
export default withPermission(PluginPage, PermissionLevel.AUTHORIZED);
