'use client';

import { useCallback, useEffect, useState } from 'react';
import { Terminal, RefreshCw, Play, Square, RotateCw, Lock, CheckCircle2, AlertTriangle } from 'lucide-react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

interface CogState {
    available: string[];
    loaded: string[];
    protected: string[];
    descriptions?: Record<string, string>;
    stale?: boolean;
}

interface CogResult {
    ok: boolean | null;
    action?: string;
    extension?: string;
    message?: string;
    queued?: boolean;
}

type Action = 'load' | 'unload' | 'reload';

function CogManagerPage() {
    const { t } = useTranslation();
    const [state, setState] = useState<CogState | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState<string | null>(null);
    const [result, setResult] = useState<CogResult | null>(null);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            setState(await apiClient.get<CogState>('/bot/cogs'));
        } catch {
            setState(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    const run = async (action: Action, extension: string) => {
        setBusy(`${action}:${extension}`);
        setResult(null);
        try {
            const res = await apiClient.post<CogResult>('/bot/cogs', { action, extension });
            setResult(res);
        } catch {
            setResult({ ok: false, message: t('cogs.requestFailed') });
        } finally {
            setBusy(null);
            await refresh();
        }
    };

    const loaded = new Set(state?.loaded ?? []);
    const isProtected = (ext: string) => (state?.protected ?? []).includes(ext);
    const cogs = state?.available ?? [];

    return (
        <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold mb-2 text-foreground flex items-center gap-2">
                        <Terminal className="text-primary" /> {t('cogs.title')}
                    </h1>
                    <p className="text-muted-foreground">{t('cogs.subtitle')}</p>
                </div>
                <button
                    onClick={refresh}
                    className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:opacity-90 text-foreground text-sm"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> {t('cogs.refresh')}
                </button>
            </div>

            {state?.stale && (
                <div className="flex items-center gap-3 p-4 rounded-lg bg-yellow-500/10 text-yellow-600 border border-yellow-500/30">
                    <AlertTriangle className="w-5 h-5 shrink-0" /> {t('cogs.stale')}
                </div>
            )}

            {result && (
                <div className={`flex items-center gap-3 p-4 rounded-lg border ${
                    result.ok ? 'bg-green-500/10 text-green-600 border-green-500/30'
                              : result.queued ? 'bg-blue-500/10 text-blue-600 border-blue-500/30'
                              : 'bg-red-500/10 text-red-600 border-red-500/30'
                }`}>
                    {result.ok ? <CheckCircle2 className="w-5 h-5 shrink-0" /> : <AlertTriangle className="w-5 h-5 shrink-0" />}
                    <span className="font-mono text-sm">{result.message}</span>
                </div>
            )}

            <div className="bg-card rounded-xl border border-border divide-y divide-border">
                {loading && cogs.length === 0 && (
                    <div className="p-6 text-muted-foreground">{t('cogs.loading')}</div>
                )}
                {!loading && cogs.length === 0 && (
                    <div className="p-6 text-muted-foreground">{t('cogs.empty')}</div>
                )}
                {cogs.map((ext) => {
                    const on = loaded.has(ext);
                    const prot = isProtected(ext);
                    const rowBusy = busy?.endsWith(`:${ext}`);
                    const desc = state?.descriptions?.[ext];
                    return (
                        <div key={ext} className="flex items-center justify-between gap-4 px-5 py-3">
                            <div className="flex items-start gap-3 min-w-0">
                                <span className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${on ? 'bg-green-500' : 'bg-muted-foreground/40'}`} />
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-mono text-sm text-foreground truncate">{ext}</span>
                                        {prot && (
                                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                                <Lock className="w-3 h-3" /> {t('cogs.protected')}
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                                        {desc || (on ? t('cogs.noDescription') : t('cogs.loadForDetails'))}
                                    </p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                {on ? (
                                    <>
                                        <button
                                            disabled={prot || !!rowBusy}
                                            onClick={() => run('reload', ext)}
                                            className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-secondary hover:opacity-90 text-foreground disabled:opacity-40"
                                        >
                                            <RotateCw className="w-3.5 h-3.5" /> {t('cogs.reload')}
                                        </button>
                                        <button
                                            disabled={prot || !!rowBusy}
                                            onClick={() => run('unload', ext)}
                                            className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-red-500/10 text-red-600 hover:opacity-90 disabled:opacity-40"
                                        >
                                            <Square className="w-3.5 h-3.5" /> {t('cogs.unload')}
                                        </button>
                                    </>
                                ) : (
                                    <button
                                        disabled={prot || !!rowBusy}
                                        onClick={() => run('load', ext)}
                                        className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-green-500/10 text-green-600 hover:opacity-90 disabled:opacity-40"
                                    >
                                        <Play className="w-3.5 h-3.5" /> {t('cogs.load')}
                                    </button>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default withPermission(CogManagerPage, PermissionLevel.DEVELOPER);
