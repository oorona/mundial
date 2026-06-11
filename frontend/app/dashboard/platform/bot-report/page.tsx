'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/app/api-client';
import { Terminal, Radio, Shield, Clock } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

interface BotReport {
    commands: Array<{
        name: string;
        description: string;
        type: string;
    }>;
    listeners: Array<{
        event: string;
        cog: string;
    }>;
    permissions: {
        guild_permissions_example: Record<string, boolean>;
        intents: Record<string, boolean>;
    };
    timestamp: number;
}

function BotReportPage() {
    const { t } = useTranslation();
    const [report, setReport] = useState<BotReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dbStatus, setDbStatus] = useState<any>(null);

    useEffect(() => {
        loadReport();
    }, []);

    const loadReport = async () => {
        try {
            setLoading(true);
            const [botData, dbData] = await Promise.all([
                apiClient.getBotReport(),
                apiClient.getDbStatus()
            ]);
            setReport(botData);
            setDbStatus(dbData);
        } catch (err) {
            console.error(err);
            setError(t('botReport.loadError'));
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return <div className="p-8 text-center text-muted-foreground">{t('botReport.loading')}</div>;
    }

    if (error) {
        return <div className="p-8 text-center text-red-500">{error}</div>;
    }

    if (!report) {
        return <div className="p-8 text-center text-muted-foreground">{t('botReport.noReport')}</div>;
    }

    return (
        <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
            <div className="flex items-center justify-between border-b border-border pb-6">
                <div>
                    <h1 className="text-3xl font-bold text-foreground mb-2">{t('botReport.title')}</h1>
                    <p className="text-muted-foreground">{t('botReport.subtitle')}</p>
                </div>
                <div className="flex items-center space-x-2 text-sm text-muted-foreground">
                    <Clock size={16} />
                    <span>{t('botReport.lastUpdated', { time: new Date(report.timestamp * 1000).toLocaleString() })}</span>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Commands Column */}
                <div className="bg-card rounded-lg p-6 border border-border shadow-sm">

                    <div className="flex items-center space-x-2 mb-4">
                        <Terminal className="text-blue-500" size={24} />
                        <h2 className="text-xl font-semibold text-foreground">{t('botReport.sectionCommands')}</h2>
                    </div>
                    <div className="space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar">
                        {report.commands.map((cmd) => (
                            <div key={cmd.name} className="p-3 bg-secondary/50 rounded-md border border-border">
                                <div className="font-mono text-blue-500 font-bold">/{cmd.name}</div>
                                <div className="text-sm text-muted-foreground mt-1">{cmd.description || t('botReport.noDescription')}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Events Column */}
                <div className="bg-card rounded-lg p-6 border border-border shadow-sm">
                    <div className="flex items-center space-x-2 mb-4">
                        <Radio className="text-green-500" size={24} />
                        <h2 className="text-xl font-semibold text-foreground">{t('botReport.sectionListeners')}</h2>
                    </div>
                    <div className="space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar">
                        {report.listeners.map((listener, idx) => (
                            <div key={idx} className="p-3 bg-secondary/50 rounded-md border border-border flex justify-between items-center">
                                <div className="font-mono text-green-500">{listener.event}</div>
                                <div className="text-xs px-2 py-1 bg-background rounded text-muted-foreground border border-border">{listener.cog}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Permissions Column */}
                <div className="bg-card rounded-lg p-6 border border-border shadow-sm">
                    <div className="flex items-center space-x-2 mb-4">
                        <Shield className="text-purple-500" size={24} />
                        <h2 className="text-xl font-semibold text-foreground">{t('botReport.sectionPermissions')}</h2>
                    </div>

                    <div className="space-y-6 max-h-[600px] overflow-y-auto custom-scrollbar">
                        <div>
                            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t('botReport.subsectionIntents')}</h3>
                            <div className="grid grid-cols-1 gap-2">
                                {Object.entries(report.permissions.intents || {}).map(([intent, enabled]) => (
                                    <div key={intent} className="flex justify-between items-center px-3 py-2 bg-secondary/50 rounded border border-border">
                                        <span className="font-mono text-sm text-foreground">{intent}</span>
                                        <span className={`w-2 h-2 rounded-full ${enabled ? 'bg-green-500' : 'bg-red-500'}`} />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div>
                            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t('botReport.subsectionBotPerms')}</h3>
                            <div className="grid grid-cols-1 gap-2">
                                {Object.entries(report.permissions.guild_permissions_example || {}).map(([perm, enabled]) => (
                                    <div key={perm} className="flex justify-between items-center px-3 py-2 bg-secondary/50 rounded border border-border">
                                        <span className="font-mono text-sm text-foreground">{perm}</span>
                                        <span className={`w-2 h-2 rounded-full ${enabled ? 'bg-green-500' : 'bg-red-500'}`} />
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default withPermission(BotReportPage, PermissionLevel.DEVELOPER);
