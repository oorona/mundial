'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/app/api-client';
import { Activity, Database, Server, CheckCircle, AlertCircle, RefreshCw, Clock } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

function SystemStatusPage() {
    const { t } = useTranslation();
    const { user, loading: authLoading } = useAuth();
    const [status, setStatus] = useState<any>({ backend: 'unknown', database: 'unknown', discord: 'unknown' });
    const [adminData, setAdminData] = useState<any>({ shards: [], db: null, frontend: [], backend: [] });
    const [loadingData, setLoadingData] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [refreshing, setRefreshing] = useState(false);

    const fetchData = async () => {
        setRefreshing(true);
        try {
            const [shards, db, frontend, backend] = await Promise.all([
                apiClient.getShards().catch(() => []),
                apiClient.getDbStatus().catch(() => null),
                apiClient.getFrontendStatus().catch(() => []),
                apiClient.getBackendStatus().catch(() => []),
            ]);
            setAdminData({ shards, db, frontend, backend });

            const backendStatus = backend && backend.length > 0 ? 'healthy' : 'degraded';
            const dbStatus = db && db.postgres?.status === 'connected' && db.redis?.status === 'connected' ? 'healthy' : 'issues';
            const discordStatus = shards && shards.length > 0 && shards.every((s: any) => s.status === 'READY') ? 'healthy' : 'degraded';
            setStatus({ backend: backendStatus, database: dbStatus, discord: discordStatus });

            setLastUpdated(new Date());
        } catch (e) {
            console.error("Failed to fetch system status", e);
        } finally {
            setLoadingData(false);
            setRefreshing(false);
        }
    };

    // Initial fetch
    useEffect(() => {
        if (!authLoading && user) {
            fetchData();
        }
    }, [authLoading, user]);

    // Polling interval (30s)
    useEffect(() => {
        if (!authLoading && user) {
            const intervalId = setInterval(fetchData, 30000);
            return () => clearInterval(intervalId);
        }
    }, [authLoading, user]);


    if (authLoading || (loadingData && !lastUpdated)) {
        return (
            <div className="flex items-center justify-center p-12">
                <div className="animate-pulse flex flex-col items-center">
                    <Activity className="h-8 w-8 text-primary mb-4 animate-bounce" />
                    <span className="text-muted-foreground">{t('status.analyzing')}</span>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
                        {t('status.title')}
                        <span className="relative flex h-3 w-3">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                        </span>
                    </h1>
                    <p className="text-muted-foreground mt-1">{t('status.subtitle')}</p>
                </div>

                <div className="flex items-center gap-4 text-sm text-muted-foreground bg-card p-2 rounded-lg border border-border shadow-sm">
                    {lastUpdated && (
                        <div className="flex items-center gap-2">
                            <Clock size={14} />
                            <span>{t('status.updatedAt', { time: lastUpdated.toLocaleTimeString() })}</span>
                        </div>
                    )}
                    <button
                        onClick={fetchData}
                        disabled={refreshing}
                        className={`p-2 hover:bg-muted rounded-full transition-all ${refreshing ? 'animate-spin text-primary' : 'hover:text-primary'}`}
                        title={t('status.refreshTitle')}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            {/* Overall Status Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <StatusCard
                    title={t('status.serviceBackend')}
                    status={status?.backend}
                    icon={Server}
                    description={t('status.serviceBackendDesc')}
                />
                <StatusCard
                    title={t('status.serviceDatabase')}
                    status={status?.database}
                    icon={Database}
                    description={t('status.serviceDatabaseDesc')}
                />
                <StatusCard
                    title={t('status.serviceDiscord')}
                    status={status?.discord}
                    icon={Activity}
                    description={t('status.serviceDiscordDesc')}
                />
            </div>

            {/* Detailed Infrastructure Views */}
            {adminData && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">

                    {/* Shards Section */}
                    <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
                        <div className="p-6 border-b border-border flex justify-between items-center bg-muted/20">
                            <div>
                                <h2 className="text-lg font-semibold flex items-center gap-2">
                                    <Activity className="text-blue-500" size={20} />
                                    {t('status.sectionShards')}
                                </h2>
                                <p className="text-sm text-muted-foreground">{t('status.shardSubtitle')}</p>
                            </div>
                            <div className="text-xs font-mono bg-background px-2 py-1 rounded border border-border">
                                {t('status.totalShards', { count: adminData.shards.length })}
                            </div>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="bg-muted/50 text-muted-foreground font-medium">
                                    <tr>
                                        <th className="px-6 py-3 text-left">{t('status.colId')}</th>
                                        <th className="px-6 py-3 text-left">{t('status.colStatus')}</th>
                                        <th className="px-6 py-3 text-left">{t('status.colLatency')}</th>
                                        <th className="px-6 py-3 text-left">{t('status.colGuilds')}</th>
                                        <th className="px-6 py-3 text-left">{t('status.colLastHeartbeat')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {adminData.shards.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-8 text-center text-muted-foreground">
                                                {t('status.noShards')}
                                            </td>
                                        </tr>
                                    ) : (
                                        adminData.shards.map((shard: any) => (
                                            <tr key={shard.shard_id} className="hover:bg-muted/30 transition-colors">
                                                <td className="px-6 py-4 font-mono font-medium">#{shard.shard_id}</td>
                                                <td className="px-6 py-4">
                                                    <Badge status={shard.status === 'READY' ? 'success' : 'error'}>
                                                        {shard.status}
                                                    </Badge>
                                                </td>
                                                <td className="px-6 py-4 font-mono">
                                                    {(shard.latency * 1000).toFixed(0)} ms
                                                </td>
                                                <td className="px-6 py-4">{shard.guild_count}</td>
                                                <td className="px-6 py-4 text-muted-foreground text-xs">
                                                    {new Date(shard.last_heartbeat).toLocaleString()}
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                        {/* Database Health */}
                        <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
                            <div className="p-6 border-b border-border bg-muted/20">
                                <h2 className="text-lg font-semibold flex items-center gap-2">
                                    <Database className="text-purple-500" size={20} />
                                    {t('status.sectionDataStore')}
                                </h2>
                            </div>
                            <div className="p-6 space-y-6">
                                {/* Postgres */}
                                <div>
                                    <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">{t('status.sectionPostgres')}</h3>
                                    <div className="grid grid-cols-2 gap-4">
                                        <MetricBox label={t('status.metricStatus')} value={adminData.db?.postgres?.status} status={adminData.db?.postgres?.status === 'connected' ? 'success' : 'error'} />
                                        <MetricBox label={t('status.metricVersion')} value={adminData.db?.postgres?.version?.split(' ')[0]} />
                                        <MetricBox label={t('status.metricConnections')} value={`${adminData.db?.postgres?.connections?.active || 0} active / ${adminData.db?.postgres?.connections?.idle || 0} idle`} />
                                        <MetricBox label={t('status.metricCacheHit')} value={adminData.db?.postgres?.cache_hit_ratio} />
                                    </div>
                                </div>
                                <div className="h-px bg-border my-4" />
                                {/* Redis */}
                                <div>
                                    <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">{t('status.sectionRedis')}</h3>
                                    <div className="grid grid-cols-2 gap-4">
                                        <MetricBox label={t('status.metricStatus')} value={adminData.db?.redis?.status} status={adminData.db?.redis?.status === 'connected' ? 'success' : 'error'} />
                                        <MetricBox label={t('status.metricMemory')} value={adminData.db?.redis?.info?.used_memory_human} />
                                        <MetricBox label={t('status.metricClients')} value={adminData.db?.redis?.info?.connected_clients} />
                                        <MetricBox label={t('status.metricUptime')} value={adminData.db?.redis?.info?.uptime_in_days ? `${adminData.db.redis.info.uptime_in_days} days` : undefined} />
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Infrastructure Nodes */}
                        <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden flex flex-col">
                            <div className="p-6 border-b border-border bg-muted/20">
                                <h2 className="text-lg font-semibold flex items-center gap-2">
                                    <Server className="text-orange-500" size={20} />
                                    {t('status.sectionNodes')}
                                </h2>
                            </div>
                            <div className="p-6 flex-1 overflow-y-auto max-h-[500px]">
                                <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">{t('status.sectionBackendInstances')}</h3>
                                <div className="space-y-3 mb-6">
                                    {adminData.backend.length === 0 ? <span className="text-muted-foreground text-sm italic">{t('status.noBackends')}</span> :
                                        adminData.backend.map((node: any) => (
                                            <NodeItem key={node.id} node={node} type="Backend" />
                                        ))
                                    }
                                </div>

                                <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">{t('status.sectionFrontendInstances')}</h3>
                                <div className="space-y-3">
                                    {adminData.frontend.length === 0 ? <span className="text-muted-foreground text-sm italic">{t('status.noFrontends')}</span> :
                                        adminData.frontend.map((node: any) => (
                                            <NodeItem key={node.id} node={node} type="Frontend" />
                                        ))
                                    }
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            )}
        </div>
    );
}

function StatusCard({ title, status, icon: Icon, description }: any) {
    const { t } = useTranslation();
    const isHealthy = status === 'healthy';
    const isDegraded = status === 'degraded';

    let colorClass = 'text-destructive';
    let bgClass = 'bg-destructive/10 border-destructive/30';
    let iconBgClass = 'bg-destructive/20';
    let statusText = t('status.statusIssues');

    if (isHealthy) {
        colorClass = 'text-green-500';
        bgClass = 'bg-green-500/10 border-green-500/30';
        iconBgClass = 'bg-green-500/20';
        statusText = t('status.statusOperational');
    } else if (isDegraded) {
        colorClass = 'text-yellow-500';
        bgClass = 'bg-yellow-500/10 border-yellow-500/30';
        iconBgClass = 'bg-yellow-500/20';
        statusText = t('status.statusDegraded');
    }

    return (
        <div className={`p-6 rounded-xl border ${bgClass} flex flex-col items-center text-center transition-all hover:scale-[1.02]`}>
            <div className={`p-3 rounded-full mb-4 ${iconBgClass} ${colorClass}`}>
                <Icon size={32} />
            </div>
            <h3 className="text-lg font-bold mb-1 text-foreground">{title}</h3>
            <p className="text-sm text-muted-foreground mb-4">{description}</p>
            <div className={`flex items-center gap-2 font-medium ${colorClass}`}>
                {isHealthy ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                {statusText}
            </div>
        </div>
    );
}

function Badge({ children, status }: { children: React.ReactNode, status: 'success' | 'error' | 'warning' }) {
    const colors = {
        success: 'bg-green-500/10 text-green-500 border-green-500/20',
        error: 'bg-destructive/10 text-destructive border-destructive/20',
        warning: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20',
    };

    return (
        <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${colors[status]}`}>
            {children}
        </span>
    );
}

function MetricBox({ label, value, status }: { label: string, value: string | number | undefined, status?: 'success' | 'error' }) {
    const { t } = useTranslation();
    const statusColor = status === 'success' ? 'text-green-500' : status === 'error' ? 'text-destructive' : 'text-foreground';
    return (
        <div className="bg-background border border-border p-3 rounded-lg">
            <div className="text-xs text-muted-foreground mb-1">{label}</div>
            <div className={`font-mono font-medium truncate ${statusColor}`} title={String(value)}>
                {value || t('status.naValue')}
            </div>
        </div>
    )
}

function NodeItem({ node, type }: any) {
    const { t } = useTranslation();
    return (
        <div className="flex items-center justify-between p-3 bg-background border border-border rounded-lg">
            <div className="flex items-center gap-3">
                <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                <div>
                    <div className="text-sm font-medium">{t('status.nodeType', { type })}</div>
                    <div className="text-xs text-muted-foreground font-mono">{node.id}</div>
                </div>
            </div>
            <div className="text-right">
                <div className="text-xs font-mono text-muted-foreground">{t('status.uptimeLabel')}</div>
                <div className="text-sm font-medium">{formatUptime(node.uptime)}</div>
            </div>
        </div>
    )
}

function formatUptime(seconds: number): string {
    if (!seconds) return '0s';

    const days = Math.floor(seconds / (3600 * 24));
    const hours = Math.floor((seconds % (3600 * 24)) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const parts = [];
    if (days > 0) parts.push(`${days}d`);
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);
    parts.push(`${secs}s`);

    return parts.join(' ');
}

export default withPermission(SystemStatusPage, PermissionLevel.DEVELOPER);
