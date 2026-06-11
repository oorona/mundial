'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { Clock, User, Activity, Trash2, X } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { usePermissions } from '@/lib/hooks/use-permissions';

interface AuditLog {
    id: number;
    guild_id: number;
    user_id: number;
    username?: string;
    action: string;
    details: Record<string, any>;
    created_at: string;
}

type PurgeMode = 'all' | 'older_than' | 'date_range';

function PurgeModal({
    guildId,
    onClose,
    onPurged,
}: {
    guildId: string;
    onClose: () => void;
    onPurged: () => void;
}) {
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
            const data = await apiClient.purgeAuditLogs(guildId, params);
            setResult(t('auditLogs.purgeSuccess').replace('{count}', String(data.deleted)));
            onPurged();
        } catch {
            setPurgeError(t('auditLogs.purgeError'));
        } finally {
            setPurging(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-foreground">{t('auditLogs.purgeTitle')}</h2>
                    <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <p className="text-sm text-red-400">{t('auditLogs.purgeWarning')}</p>

                <div className="space-y-2">
                    {(['all', 'older_than', 'date_range'] as PurgeMode[]).map((m) => (
                        <label key={m} className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="radio"
                                name="purge-mode"
                                value={m}
                                checked={mode === m}
                                onChange={() => setMode(m)}
                            />
                            <span className="text-sm text-foreground">
                                {m === 'all' && t('auditLogs.purgeAll')}
                                {m === 'older_than' && t('auditLogs.purgeOlderThan')}
                                {m === 'date_range' && t('auditLogs.purgeDateRange')}
                            </span>
                        </label>
                    ))}
                </div>

                {mode === 'older_than' && (
                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            min="1"
                            value={days}
                            onChange={(e) => setDays(e.target.value)}
                            className="w-24 px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm"
                        />
                        <span className="text-sm text-muted-foreground">{t('auditLogs.purgeDays')}</span>
                    </div>
                )}

                {mode === 'date_range' && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground w-16">{t('auditLogs.purgeAfter')}</span>
                            <input
                                type="date"
                                value={after}
                                onChange={(e) => setAfter(e.target.value)}
                                className="px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground w-16">{t('auditLogs.purgeBefore')}</span>
                            <input
                                type="date"
                                value={before}
                                onChange={(e) => setBefore(e.target.value)}
                                className="px-3 py-1.5 rounded-md border border-border bg-background text-foreground text-sm"
                            />
                        </div>
                    </div>
                )}

                {result && <p className="text-sm text-green-400">{result}</p>}
                {purgeError && <p className="text-sm text-red-400">{purgeError}</p>}

                <div className="flex justify-end gap-2 pt-2">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm rounded-md border border-border text-foreground hover:bg-muted transition-colors"
                    >
                        {t('common.cancel')}
                    </button>
                    <button
                        onClick={handlePurge}
                        disabled={purging}
                        className="px-4 py-2 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white font-medium transition-colors disabled:opacity-50"
                    >
                        {purging ? t('auditLogs.purging') : t('auditLogs.purgeConfirm')}
                    </button>
                </div>
            </div>
        </div>
    );
}

function AuditLogsPage() {
    const { t } = useTranslation();
    const params = useParams();
    const guildId = params.guildId as string;
    const { permissionLevel } = usePermissions();

    const [logs, setLogs] = useState<AuditLog[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [showPurge, setShowPurge] = useState(false);

    const fetchLogs = async () => {
        try {
            setLoading(true);
            const data = await apiClient.getAuditLogs(guildId);
            setLogs(data);
        } catch (err: any) {
            setError(err.response?.data?.detail || t('auditLogs.loadError'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (guildId) {
            fetchLogs();
        }
    }, [guildId]);

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleString();
    };

    const formatDetails = (details: Record<string, any>) => {
        if (!details || Object.keys(details).length === 0) return null;
        return JSON.stringify(details, null, 2);
    };

    if (loading) {
        return <div className="p-8 text-muted-foreground">{t('auditLogs.loading')}</div>;
    }

    if (error) {
        return <div className="p-8 text-red-400">{error}</div>;
    }

    const canPurge = permissionLevel >= PermissionLevel.OWNER;

    return (
        <>
        {showPurge && (
            <PurgeModal
                guildId={guildId}
                onClose={() => setShowPurge(false)}
                onPurged={() => { setShowPurge(false); fetchLogs(); }}
            />
        )}
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="mb-8 flex items-start justify-between">
                <div>
                    <h1 className="text-3xl font-bold mb-2 text-foreground">{t('auditLogs.title')}</h1>
                    <p className="text-muted-foreground">{t('auditLogs.subtitle')}</p>
                </div>
                {canPurge && (
                    <button
                        onClick={() => setShowPurge(true)}
                        className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-red-600/10 hover:bg-red-600/20 text-red-400 border border-red-600/30 transition-colors"
                    >
                        <Trash2 className="w-4 h-4" />
                        {t('auditLogs.purgeButton')}
                    </button>
                )}
            </div>

            <div className="bg-card rounded-xl border border-border overflow-hidden shadow-sm">
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="bg-muted/50 border-b border-border">
                                <th className="p-4 font-medium text-muted-foreground">{t('auditLogs.colAction')}</th>
                                <th className="p-4 font-medium text-muted-foreground">{t('auditLogs.colUser')}</th>
                                <th className="p-4 font-medium text-muted-foreground">{t('auditLogs.colDetails')}</th>
                                <th className="p-4 font-medium text-muted-foreground">{t('auditLogs.colTime')}</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {logs.length === 0 ? (
                                <tr>
                                    <td colSpan={4} className="p-8 text-center text-muted-foreground">
                                        {t('auditLogs.noLogs')}
                                    </td>
                                </tr>
                            ) : (
                                logs.map((log) => (
                                    <tr key={log.id} className="hover:bg-muted/30 transition-colors">
                                        <td className="p-4">
                                            <div className="flex items-center gap-2">
                                                <Activity className="w-4 h-4 text-primary" />
                                                <span className="font-medium text-foreground">{log.action}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <div className="flex items-center gap-2 text-muted-foreground">
                                                <User className="w-4 h-4" />
                                                <span className="text-sm">{log.username ?? String(log.user_id)}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            {formatDetails(log.details) ? (
                                                <pre className="text-xs text-muted-foreground font-mono bg-muted/50 p-2 rounded max-w-md overflow-x-auto scrollbar-thin">
                                                    {formatDetails(log.details)}
                                                </pre>
                                            ) : (
                                                <span className="text-xs text-muted-foreground/50 italic">—</span>
                                            )}
                                        </td>
                                        <td className="p-4 text-muted-foreground text-sm whitespace-nowrap">
                                            <div className="flex items-center gap-2">
                                                <Clock className="w-4 h-4" />
                                                {formatDate(log.created_at)}
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        </>
    );
}

export default withPermission(AuditLogsPage, PermissionLevel.AUTHORIZED);
