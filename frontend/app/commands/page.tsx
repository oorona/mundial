'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { RefreshCw, BookOpen, ChevronDown, ChevronRight } from 'lucide-react';

interface BotCommand {
    name: string;
    description: string;
    usage: string;
    cog: string;
    examples?: string[];
}

interface CommandsData {
    commands: BotCommand[];
    last_updated: string | null;
    total: number;
}

function CommandsPage() {
    const { user, loading: authLoading } = useAuth();
    const { t } = useTranslation();
    const [data, setData] = useState<CommandsData | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
    const [expandedCogs, setExpandedCogs] = useState<Set<string>>(new Set());

    const fetchCommands = async (): Promise<boolean> => {
        try {
            const result = await apiClient.getCommands();
            setData(result);
            const cogs = new Set(result.commands.map((c: BotCommand) => c.cog));
            setExpandedCogs(cogs);
            return true;
        } catch (err: any) {
            const status = err?.response?.status;
            const msg = err?.response?.data?.detail || err?.message || 'Unknown error';
            console.error('getCommands failed:', status, msg);
            setMessage({ type: 'error', text: `Failed to load commands (HTTP ${status ?? 'network error'}): ${msg}` });
            setData({ commands: [], last_updated: null, total: 0 });
            return false;
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!authLoading) {
            fetchCommands();
        }
    }, [authLoading]);

    const handleRefresh = async () => {
        setRefreshing(true);
        setMessage(null);
        try {
            await apiClient.refreshCommands();
        } catch (err: any) {
            const detail = err?.response?.data?.detail || err?.message;
            setMessage({ type: 'error', text: detail ? `${t('commands.refreshError')} ${detail}` : t('commands.refreshError') });
            setRefreshing(false);
            return;
        }
        const ok = await fetchCommands();
        setRefreshing(false);
        if (ok) {
            setMessage({ type: 'success', text: t('commands.refreshSuccess') });
        }
        // fetchCommands already set error message if !ok
    };

    const toggleCog = (cog: string) => {
        setExpandedCogs(prev => {
            const next = new Set(prev);
            if (next.has(cog)) {
                next.delete(cog);
            } else {
                next.add(cog);
            }
            return next;
        });
    };

    if (loading) {
        return (
            <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
                {[...Array(3)].map((_, i) => (
                    <div key={i} className="animate-pulse bg-card border border-border rounded-xl p-6 space-y-3">
                        <div className="h-5 bg-muted rounded w-1/4" />
                        <div className="h-3 bg-muted rounded w-3/4" />
                        <div className="h-3 bg-muted rounded w-1/2" />
                    </div>
                ))}
            </div>
        );
    }

    // Group commands by cog
    const commandsByCog: Record<string, BotCommand[]> = {};
    if (data?.commands) {
        for (const cmd of data.commands) {
            if (!commandsByCog[cmd.cog]) commandsByCog[cmd.cog] = [];
            commandsByCog[cmd.cog].push(cmd);
        }
    }
    const cogNames = Object.keys(commandsByCog).sort();

    const lastUpdatedText = data?.last_updated
        ? t('commands.lastUpdated', { date: new Date(data.last_updated).toLocaleString() })
        : t('commands.neverSynced');

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            {/* Header */}
            <div className="mb-8 flex flex-col md:flex-row md:items-start justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
                        <BookOpen className="text-primary" />
                        {t('commands.title')}
                    </h1>
                    <p className="text-muted-foreground mt-1">{t('commands.subtitle')}</p>
                    <p className="text-sm text-muted-foreground mt-2">{lastUpdatedText}</p>
                </div>

                {user?.is_admin && (
                    <button
                        type="button"
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 shrink-0"
                    >
                        <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
                        {refreshing ? t('commands.refreshing') : t('commands.refreshButton')}
                    </button>
                )}
            </div>

            {/* Message */}
            {message && (
                <div className={`mb-6 p-4 rounded-lg ${message.type === 'success' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}`}>
                    {message.text}
                </div>
            )}

            {/* Summary */}
            {data && data.total > 0 && (
                <p className="text-sm text-muted-foreground mb-6">
                    {t('commands.commandCount', { count: String(data.total) })}
                </p>
            )}

            {/* Empty state */}
            {(!data || data.total === 0) && (
                <div className="text-center py-20 bg-muted/20 rounded-xl border border-dashed border-border">
                    <BookOpen className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
                    <h3 className="text-lg font-medium mb-2 text-foreground">{t('commands.noCommands')}</h3>
                    <p className="text-muted-foreground text-sm">{t('commands.noCommandsHint')}</p>
                </div>
            )}

            {/* Commands grouped by cog */}
            {cogNames.length > 0 && (
                <div className="space-y-4">
                    {cogNames.map(cog => {
                        const isExpanded = expandedCogs.has(cog);
                        const cmds = commandsByCog[cog];
                        return (
                            <div key={cog} className="bg-card border border-border rounded-xl overflow-hidden">
                                {/* Cog header */}
                                <button
                                    type="button"
                                    onClick={() => toggleCog(cog)}
                                    className="w-full flex items-center justify-between px-6 py-4 hover:bg-muted/50 transition-colors text-left"
                                >
                                    <div className="flex items-center gap-3">
                                        <span className="font-semibold text-foreground">{cog}</span>
                                        <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                                            {t('commands.commandCount', { count: String(cmds.length) })}
                                        </span>
                                    </div>
                                    {isExpanded ? (
                                        <ChevronDown size={18} className="text-muted-foreground" />
                                    ) : (
                                        <ChevronRight size={18} className="text-muted-foreground" />
                                    )}
                                </button>

                                {/* Commands list */}
                                {isExpanded && (
                                    <div className="divide-y divide-border border-t border-border">
                                        {cmds.map(cmd => (
                                            <div key={cmd.name} className="px-6 py-4 space-y-2">
                                                <div className="flex items-start gap-3">
                                                    <code className="font-mono font-bold text-primary bg-primary/10 px-2 py-0.5 rounded text-sm shrink-0">
                                                        {cmd.name}
                                                    </code>
                                                    <p className="text-foreground text-sm">{cmd.description}</p>
                                                </div>

                                                <div className="ml-0 space-y-1 text-sm">
                                                    <div className="flex items-start gap-2">
                                                        <span className="text-muted-foreground font-medium shrink-0">
                                                            {t('commands.usageLabel')}:
                                                        </span>
                                                        <code className="font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded text-xs">
                                                            {cmd.usage}
                                                        </code>
                                                    </div>

                                                    {cmd.examples && cmd.examples.length > 0 && (
                                                        <div className="flex items-start gap-2">
                                                            <span className="text-muted-foreground font-medium shrink-0">
                                                                {t('commands.examplesLabel')}:
                                                            </span>
                                                            <div className="flex flex-wrap gap-1">
                                                                {cmd.examples.map((ex, i) => (
                                                                    <code key={i} className="font-mono text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">
                                                                        {ex}
                                                                    </code>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export default withPermission(CommandsPage, PermissionLevel.PUBLIC_DATA);
