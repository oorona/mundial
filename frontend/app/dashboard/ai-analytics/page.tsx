"use client";

import { useEffect, useState } from 'react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { Trash2, X } from 'lucide-react';

interface TokenBreakdown {
    tokens?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    thoughts_tokens?: number;
    cached_tokens?: number;
}

interface LLMStats {
    total_cost: number;
    total_tokens: number;
    total_prompt_tokens?: number;
    total_completion_tokens?: number;
    total_thoughts_tokens?: number;
    total_cached_tokens?: number;
    by_provider: ({ provider: string; cost: number; requests: number } & TokenBreakdown)[];
    by_model: ({ provider: string; model: string; cost: number; requests: number } & TokenBreakdown)[];
    by_guild: ({ guild_id: string | null; guild_name: string; cost: number; requests: number } & TokenBreakdown)[];
    recent_logs: any[];
}

const num = (n?: number) => (n ?? 0).toLocaleString();

type PurgeMode = 'all' | 'older_than' | 'date_range';

function PurgeModal({ onClose, onPurged }: { onClose: () => void; onPurged: () => void }) {
    const { t } = useTranslation();
    const [mode, setMode] = useState<PurgeMode>('all');
    const [days, setDays] = useState('30');
    const [before, setBefore] = useState('');
    const [after, setAfter] = useState('');
    const [purging, setPurging] = useState(false);
    const [result, setResult] = useState<string | null>(null);
    const [purgeError, setPurgeError] = useState<string | null>(null);

    const handlePurge = async () => {
        setPurging(true);
        setResult(null);
        setPurgeError(null);
        try {
            const params: { older_than_days?: number; before?: string; after?: string } = {};
            if (mode === 'older_than') params.older_than_days = parseInt(days, 10);
            if (mode === 'date_range') {
                if (before) params.before = before;
                if (after) params.after = after;
            }
            const data = await apiClient.purgeLLMUsage(params);
            setResult(
                t('aiAnalytics.purgeSuccess')
                    .replace('{count}', String(data.deleted))
                    .replace('{summaries}', String(data.summaries_deleted))
            );
            onPurged();
        } catch {
            setPurgeError(t('aiAnalytics.purgeError'));
        } finally {
            setPurging(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-foreground">{t('aiAnalytics.purgeTitle')}</h2>
                    <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <p className="text-sm text-red-400">{t('aiAnalytics.purgeWarning')}</p>

                <div className="space-y-2">
                    {(['all', 'older_than', 'date_range'] as PurgeMode[]).map((m) => (
                        <label key={m} className="flex items-center gap-2 cursor-pointer">
                            <input type="radio" name="purge-mode" value={m} checked={mode === m} onChange={() => setMode(m)} />
                            <span className="text-sm text-foreground">
                                {m === 'all' && t('aiAnalytics.purgeAll')}
                                {m === 'older_than' && t('aiAnalytics.purgeOlderThan')}
                                {m === 'date_range' && t('aiAnalytics.purgeDateRange')}
                            </span>
                        </label>
                    ))}
                </div>

                {mode === 'older_than' && (
                    <div className="flex items-center gap-2">
                        <input type="number" min="1" value={days} onChange={(e) => setDays(e.target.value)}
                            className="w-24 px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm" />
                        <span className="text-sm text-muted-foreground">{t('aiAnalytics.purgeDays')}</span>
                    </div>
                )}

                {mode === 'date_range' && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground w-16">{t('aiAnalytics.purgeAfter')}</span>
                            <input type="date" value={after} onChange={(e) => setAfter(e.target.value)}
                                className="px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm" />
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground w-16">{t('aiAnalytics.purgeBefore')}</span>
                            <input type="date" value={before} onChange={(e) => setBefore(e.target.value)}
                                className="px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm" />
                        </div>
                    </div>
                )}

                {result && <p className="text-sm text-green-400">{result}</p>}
                {purgeError && <p className="text-sm text-red-400">{purgeError}</p>}

                <div className="flex justify-end gap-2 pt-2">
                    <button onClick={onClose}
                        className="px-4 py-2 text-sm rounded-md border border-border text-foreground hover:bg-muted transition-colors">
                        {t('common.cancel')}
                    </button>
                    <button onClick={handlePurge} disabled={purging}
                        className="px-4 py-2 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white font-medium transition-colors disabled:opacity-50">
                        {purging ? t('aiAnalytics.purging') : t('aiAnalytics.purgeConfirm')}
                    </button>
                </div>
            </div>
        </div>
    );
}

function AIAnalyticsPage() {
    const { t } = useTranslation();
    const [stats, setStats] = useState<LLMStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [showPurge, setShowPurge] = useState(false);

    useEffect(() => {
        loadStats();
    }, []);

    const loadStats = async () => {
        try {
            setLoading(true);
            const data = await apiClient.getLLMStats();
            setStats(data);
        } catch (err) {
            console.error("Failed to load stats", err);
            setError(t('aiAnalytics.loadError'));
        } finally {
            setLoading(false);
        }
    };

    if (loading) return <div className="p-8 text-foreground">{t('aiAnalytics.loading')}</div>;
    if (error) return <div className="p-8 text-red-500">{error}</div>;
    if (!stats) return <div className="p-8 text-foreground">{t('aiAnalytics.noData')}</div>;

    const totalRequests = stats.by_provider.reduce((acc, curr) => acc + curr.requests, 0);

    return (
        <>
        {showPurge && <PurgeModal onClose={() => setShowPurge(false)} onPurged={() => { setShowPurge(false); loadStats(); }} />}
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="flex items-start justify-between mb-6">
                <h1 className="text-3xl font-bold">{t('aiAnalytics.title')}</h1>
                <button
                    onClick={() => setShowPurge(true)}
                    className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-red-600/10 hover:bg-red-600/20 text-red-400 border border-red-600/30 transition-colors"
                >
                    <Trash2 className="w-4 h-4" />
                    {t('aiAnalytics.purgeButton')}
                </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div className="bg-card rounded-lg p-6 border border-border shadow-md">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">{t('aiAnalytics.statTotalTokens')}</h3>
                    <div className="text-2xl font-bold text-foreground">{stats.total_tokens.toLocaleString()}</div>
                    <div className="mt-2 text-xs text-muted-foreground space-y-0.5">
                        <div>{t('aiAnalytics.statInputTokens')}: {num(stats.total_prompt_tokens)}</div>
                        <div>{t('aiAnalytics.statOutputTokens')}: {num(stats.total_completion_tokens)}</div>
                        <div>{t('aiAnalytics.statThinkingTokens')}: {num(stats.total_thoughts_tokens)}</div>
                        <div>{t('aiAnalytics.statCachedTokens')}: {num(stats.total_cached_tokens)}</div>
                    </div>
                </div>
                <div className="bg-card rounded-lg p-6 border border-border shadow-md">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">{t('aiAnalytics.statEstimatedCost')}</h3>
                    <div className="text-2xl font-bold text-foreground">${(stats.total_cost ?? 0).toFixed(4)}</div>
                </div>
                <div className="bg-card rounded-lg p-6 border border-border shadow-md">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">{t('aiAnalytics.statTotalRequests')}</h3>
                    <div className="text-2xl font-bold text-foreground">{totalRequests}</div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="bg-card rounded-lg border border-border shadow-md overflow-hidden">
                    <div className="p-6 border-b border-border">
                        <h3 className="text-lg font-medium">{t('aiAnalytics.sectionByProvider')}</h3>
                    </div>
                    <div className="p-0">
                        <table className="w-full">
                            <thead className="bg-muted/30">
                                <tr>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colProvider')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colRequests')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colInputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colOutputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colCachedTokens')}</th>
                                    <th className="text-right p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colCost')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {stats.by_provider.map((p) => (
                                    <tr key={p.provider} className="border-t border-border hover:bg-muted/30 transition-colors">
                                        <td className="p-4 font-medium capitalize text-foreground">{p.provider}</td>
                                        <td className="p-4 text-foreground">{p.requests}</td>
                                        <td className="p-4 text-foreground">{num(p.prompt_tokens)}</td>
                                        <td className="p-4 text-foreground">{num((p.completion_tokens ?? 0) + (p.thoughts_tokens ?? 0))}</td>
                                        <td className="p-4 text-foreground">{num(p.cached_tokens)}</td>
                                        <td className="p-4 text-right text-foreground">${p.cost.toFixed(4)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="bg-card rounded-lg border border-border shadow-md overflow-hidden">
                    <div className="p-6 border-b border-border">
                        <h3 className="text-lg font-medium">{t('aiAnalytics.sectionByModel')}</h3>
                    </div>
                    <div className="p-0 overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-muted/30">
                                <tr>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colProvider')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colModel')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colRequests')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colInputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colOutputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colThinkingTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colCachedTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colTokens')}</th>
                                    <th className="text-right p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colCost')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(stats.by_model ?? []).map((m) => (
                                    <tr key={`${m.provider}:${m.model}`} className="border-t border-border hover:bg-muted/30 transition-colors">
                                        <td className="p-4 font-medium capitalize text-foreground">{m.provider}</td>
                                        <td className="p-4 font-mono text-sm text-foreground">{m.model}</td>
                                        <td className="p-4 text-foreground">{m.requests}</td>
                                        <td className="p-4 text-foreground">{num(m.prompt_tokens)}</td>
                                        <td className="p-4 text-foreground">{num(m.completion_tokens)}</td>
                                        <td className="p-4 text-foreground">{num(m.thoughts_tokens)}</td>
                                        <td className="p-4 text-foreground">{num(m.cached_tokens)}</td>
                                        <td className="p-4 text-foreground">{num(m.tokens)}</td>
                                        <td className="p-4 text-right text-foreground">${(m.cost ?? 0).toFixed(4)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="bg-card rounded-lg border border-border shadow-md overflow-hidden">
                    <div className="p-6 border-b border-border">
                        <h3 className="text-lg font-medium">{t('aiAnalytics.sectionByGuild')}</h3>
                    </div>
                    <div className="p-0 overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-muted/30">
                                <tr>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colServer')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colRequests')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colInputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colOutputTokens')}</th>
                                    <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colTokens')}</th>
                                    <th className="text-right p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colCost')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(stats.by_guild ?? []).map((g) => (
                                    <tr key={g.guild_id ?? 'system'} className="border-t border-border hover:bg-muted/30 transition-colors">
                                        <td className="p-4 text-foreground">
                                            {g.guild_name}
                                            {g.guild_id && <span className="ml-2 font-mono text-xs text-muted-foreground">{g.guild_id}</span>}
                                        </td>
                                        <td className="p-4 text-foreground">{g.requests}</td>
                                        <td className="p-4 text-foreground">{num(g.prompt_tokens)}</td>
                                        <td className="p-4 text-foreground">{num((g.completion_tokens ?? 0) + (g.thoughts_tokens ?? 0))}</td>
                                        <td className="p-4 text-foreground">{num(g.tokens)}</td>
                                        <td className="p-4 text-right text-foreground">${(g.cost ?? 0).toFixed(4)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div className="bg-card rounded-lg border border-border shadow-md overflow-hidden">
                <div className="p-6 border-b border-border">
                    <h3 className="text-lg font-medium">{t('aiAnalytics.sectionRecentLogs')}</h3>
                </div>
                <div className="p-0 overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-muted/30">
                            <tr>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colTime')}</th>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colUser')}</th>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colProvider')}</th>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colModel')}</th>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colTokens')}</th>
                                <th className="text-left p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colType')}</th>
                                <th className="text-right p-4 text-sm font-medium text-muted-foreground">{t('aiAnalytics.colLatency')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stats.recent_logs.map((log) => (
                                <tr key={log.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                                    <td className="p-4 text-sm whitespace-nowrap text-foreground">{new Date(log.timestamp).toLocaleString()}</td>
                                    <td className="p-4 text-sm text-foreground">{log.user_id}</td>
                                    <td className="p-4 text-sm capitalize text-foreground">{log.provider}</td>
                                    <td className="p-4 text-sm text-foreground">{log.model}</td>
                                    <td className="p-4 text-sm text-foreground">{log.tokens}</td>
                                    <td className="p-4 text-sm">
                                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-900 text-indigo-100 border border-indigo-700">
                                            {log.request_type}
                                        </span>
                                    </td>
                                    <td className="p-4 text-sm text-right text-foreground">{(log.latency || 0).toFixed(2)}s</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        </>
    );
}

export default withPermission(AIAnalyticsPage, PermissionLevel.DEVELOPER);
