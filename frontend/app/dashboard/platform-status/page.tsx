'use client';

import { useCallback, useEffect, useState } from 'react';
import { Activity, RefreshCw, Server, Database, Cpu, Globe, Bot, Users, ShieldCheck } from 'lucide-react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

interface Component { status: string; [k: string]: any }
interface GuildRow {
    guild_id: string; name: string; slug?: string | null; owner_id?: string | null;
    member_count?: number | null; authorized_users: number;
}
interface Overview {
    components: { backend: Component; frontend: Component; database: Component; redis: Component; bot: Component };
    guilds: { total: number; limit?: number | null; list: GuildRow[]; snapshot_stale?: boolean };
    users: { total: number; active_sessions: number; by_permission: Record<string, number> };
    generated_at: number;
}

function dot(status: string) {
    const ok = status === 'up';
    const unknown = status === 'unknown';
    return (
        <span className={`inline-block w-2.5 h-2.5 rounded-full ${ok ? 'bg-green-500' : unknown ? 'bg-yellow-500' : 'bg-red-500'}`} />
    );
}

// Key metrics shown in a component's detail panel. Technical metric labels are
// kept as plain (universal) terms; the panel chrome is translated.
function detailRows(key: string, comp: Component): [string, string][] {
    const rows: [string, string][] = [['Status', comp.status]];
    if (comp.error) rows.push(['Error', String(comp.error)]);
    if (key === 'database') {
        if (comp.version) rows.push(['Version', comp.version]);
        if (comp.size) rows.push(['Size', comp.size]);
        if (comp.cache_hit_ratio) rows.push(['Cache hit ratio', comp.cache_hit_ratio]);
        if (comp.connections) rows.push(['Connections', `${comp.connections.active} active / ${comp.connections.idle} idle`]);
    } else if (key === 'redis') {
        if (comp.version) rows.push(['Version', comp.version]);
        if (comp.used_memory) rows.push(['Memory', comp.used_memory]);
        if (comp.connected_clients != null) rows.push(['Clients', String(comp.connected_clients)]);
        if (comp.uptime_days != null) rows.push(['Uptime (days)', String(comp.uptime_days)]);
    } else if (key === 'bot') {
        rows.push(['Shards', `${comp.ready_shards ?? 0}/${comp.shards ?? 0} ready`]);
        rows.push(['Guilds', String(comp.guild_count ?? 0)]);
        if (comp.avg_latency_ms != null) rows.push(['Avg latency', `${comp.avg_latency_ms}ms`]);
    } else if (key === 'backend' || key === 'frontend') {
        rows.push(['Instances', String(comp.instances ?? 0)]);
    }
    return rows;
}

function PlatformStatusPage() {
    const { t } = useTranslation();
    const [data, setData] = useState<Overview | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(false);
    const [selected, setSelected] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            setData(await apiClient.getPlatformOverview());
            setError(false);
        } catch {
            setError(true);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const c = data?.components;
    const componentCards = c ? [
        { key: 'backend', icon: Server, comp: c.backend, detail: `${c.backend.instances ?? 0} ${t('platformStatus.instances')}` },
        { key: 'frontend', icon: Globe, comp: c.frontend, detail: `${c.frontend.instances ?? 0} ${t('platformStatus.instances')}` },
        { key: 'database', icon: Database, comp: c.database, detail: c.database.version || '' },
        { key: 'redis', icon: Cpu, comp: c.redis, detail: c.redis.version ? `v${c.redis.version}` : '' },
        { key: 'bot', icon: Bot, comp: c.bot, detail: `${c.bot.ready_shards ?? 0}/${c.bot.shards ?? 0} ${t('platformStatus.shardsReady')} · ${c.bot.guild_count ?? 0} ${t('platformStatus.guilds')}` },
    ] : [];

    return (
        <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold mb-2 text-foreground flex items-center gap-2">
                        <Activity className="text-primary" /> {t('platformStatus.title')}
                    </h1>
                    <p className="text-muted-foreground">{t('platformStatus.subtitle')}</p>
                </div>
                <button onClick={load} className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:opacity-90 text-foreground text-sm">
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> {t('platformStatus.refresh')}
                </button>
            </div>

            {error && (
                <div className="p-4 rounded-lg bg-red-500/10 text-red-600 border border-red-500/30">{t('platformStatus.loadError')}</div>
            )}

            {/* Components */}
            <div>
                <h2 className="text-lg font-semibold mb-3 text-foreground">{t('platformStatus.components')}</h2>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                    {componentCards.map(({ key, icon: Icon, comp, detail }) => (
                        <button
                            key={key}
                            type="button"
                            onClick={() => setSelected(selected === key ? null : key)}
                            className={`text-left bg-card border rounded-xl p-4 transition-colors hover:border-primary/50 ${selected === key ? 'border-primary ring-1 ring-primary' : 'border-border'}`}
                            title={t('platformStatus.clickForDetail')}
                        >
                            <div className="flex items-center justify-between mb-2">
                                <Icon className="w-5 h-5 text-muted-foreground" />
                                {dot(comp.status)}
                            </div>
                            <div className="font-medium text-foreground">{t(`platformStatus.comp_${key}`)}</div>
                            <div className="text-xs text-muted-foreground capitalize">{comp.status}</div>
                            {detail && <div className="text-xs text-muted-foreground mt-1 truncate" title={detail}>{detail}</div>}
                        </button>
                    ))}
                </div>

                {/* Detail panel for the selected component */}
                {selected && c && (c as any)[selected] && (
                    <div className="mt-4 bg-card border border-border rounded-xl p-5">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="font-semibold text-foreground">
                                {t(`platformStatus.comp_${selected}`)} · {t('platformStatus.detail')}
                            </h3>
                            <button type="button" onClick={() => setSelected(null)} className="text-sm text-muted-foreground hover:text-foreground">
                                {t('platformStatus.close')}
                            </button>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-2">
                            {detailRows(selected, (c as any)[selected]).map(([k, v]) => (
                                <div key={k}>
                                    <div className="text-xs text-muted-foreground">{k}</div>
                                    <div className="text-sm text-foreground font-mono break-all">{v}</div>
                                </div>
                            ))}
                        </div>

                        {selected === 'bot' && Array.isArray((c as any).bot.shard_list) && (c as any).bot.shard_list.length > 0 && (
                            <div className="overflow-x-auto mt-3">
                                <table className="w-full text-sm">
                                    <thead className="bg-muted/30">
                                        <tr>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Shard</th>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Status</th>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Latency</th>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Guilds</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(c as any).bot.shard_list.map((s: any) => (
                                            <tr key={s.shard_id} className="border-t border-border">
                                                <td className="p-2 text-foreground">#{s.shard_id}</td>
                                                <td className="p-2 text-foreground">{s.status}</td>
                                                <td className="p-2 text-foreground">{s.latency != null ? `${Math.round(s.latency)}ms` : '—'}</td>
                                                <td className="p-2 text-foreground">{s.guild_count ?? '—'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {(selected === 'backend' || selected === 'frontend') && Array.isArray((c as any)[selected].instance_list) && (c as any)[selected].instance_list.length > 0 && (
                            <div className="overflow-x-auto mt-3">
                                <table className="w-full text-sm">
                                    <thead className="bg-muted/30">
                                        <tr>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Instance</th>
                                            <th className="text-left p-2 text-xs font-medium text-muted-foreground">Uptime (s)</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(c as any)[selected].instance_list.map((inst: any) => (
                                            <tr key={inst.id} className="border-t border-border">
                                                <td className="p-2 font-mono text-xs text-foreground">{inst.id}</td>
                                                <td className="p-2 text-foreground">{inst.uptime != null ? Math.round(inst.uptime) : '—'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Totals */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-card border border-border rounded-xl p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-1"><Server className="w-4 h-4" /> {t('platformStatus.totalGuilds')}</div>
                    <div className="text-2xl font-bold text-foreground">
                        {data?.guilds.total ?? '—'}
                        {data?.guilds.limit != null && (
                            <span className="text-base font-normal text-muted-foreground"> / {data.guilds.limit}</span>
                        )}
                    </div>
                    {data?.guilds.limit != null ? (
                        (data.guilds.total / data.guilds.limit) >= 0.9 ? (
                            <div className="mt-1 text-xs font-medium text-amber-500">{t('platformStatus.serverCapNear')}</div>
                        ) : (
                            <div className="mt-1 text-xs text-muted-foreground">{t('platformStatus.serverCap', { max: String(data.guilds.limit) })}</div>
                        )
                    ) : (
                        <div className="mt-1 text-xs text-muted-foreground">{t('platformStatus.serverCapNone')}</div>
                    )}
                </div>
                <div className="bg-card border border-border rounded-xl p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-1"><Users className="w-4 h-4" /> {t('platformStatus.totalUsers')}</div>
                    <div className="text-2xl font-bold text-foreground">{data?.users.total ?? '—'}</div>
                </div>
                <div className="bg-card border border-border rounded-xl p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-1"><ShieldCheck className="w-4 h-4" /> {t('platformStatus.activeSessions')}</div>
                    <div className="text-2xl font-bold text-foreground">{data?.users.active_sessions ?? '—'}</div>
                </div>
                <div className="bg-card border border-border rounded-xl p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-1"><Bot className="w-4 h-4" /> {t('platformStatus.botGuilds')}</div>
                    <div className="text-2xl font-bold text-foreground">{data?.components.bot.guild_count ?? '—'}</div>
                </div>
            </div>

            {/* Per-guild */}
            {data?.guilds.snapshot_stale && (
                <div className="flex items-center gap-3 p-3 rounded-lg bg-yellow-500/10 text-yellow-600 border border-yellow-500/30 text-sm">
                    {t('platformStatus.snapshotStale')}
                </div>
            )}
            <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="p-4 border-b border-border font-semibold text-foreground">{t('platformStatus.byGuild')}</div>
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-muted/30">
                            <tr>
                                <th className="text-left p-3 text-sm font-medium text-muted-foreground">{t('platformStatus.colServer')}</th>
                                <th className="text-left p-3 text-sm font-medium text-muted-foreground">{t('platformStatus.colMembers')}</th>
                                <th className="text-left p-3 text-sm font-medium text-muted-foreground">{t('platformStatus.colDashUsers')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(data?.guilds.list ?? []).map((g) => (
                                <tr key={g.guild_id} className="border-t border-border hover:bg-muted/30 transition-colors">
                                    <td className="p-3 text-foreground">
                                        {g.name}
                                        {g.slug && <span className="ml-2 font-mono text-xs text-muted-foreground">/{g.slug}</span>}
                                    </td>
                                    <td className="p-3 text-foreground">{g.member_count ?? '—'}</td>
                                    <td className="p-3 text-foreground">{g.authorized_users}</td>
                                </tr>
                            ))}
                            {data && data.guilds.list.length === 0 && (
                                <tr><td colSpan={3} className="p-4 text-center text-muted-foreground text-sm">{t('platformStatus.noGuilds')}</td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

export default withPermission(PlatformStatusPage, PermissionLevel.DEVELOPER);
