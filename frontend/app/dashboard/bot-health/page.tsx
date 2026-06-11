'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/app/api-client';
import { Activity, Database, Server, CheckCircle, AlertCircle, RefreshCw, Clock } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

type ServiceStatus = 'healthy' | 'degraded' | 'unknown';

interface HealthStatus {
    backend: ServiceStatus;
    database: ServiceStatus;
    discord: ServiceStatus;
}

function BotHealthPage() {
    const { t } = useTranslation();
    const { user, loading: authLoading } = useAuth();
    const [status, setStatus] = useState<HealthStatus>({ backend: 'unknown', database: 'unknown', discord: 'unknown' });
    const [loadingData, setLoadingData] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [refreshing, setRefreshing] = useState(false);

    const fetchData = async () => {
        setRefreshing(true);
        try {
            const health = await apiClient.healthCheck().catch(() => null);
            if (health && health.status === 'ok') {
                setStatus({ backend: 'healthy', database: 'healthy', discord: 'healthy' });
            } else {
                setStatus({ backend: 'degraded', database: 'unknown', discord: 'unknown' });
            }
            setLastUpdated(new Date());
        } catch {
            // leave status as-is
        } finally {
            setLoadingData(false);
            setRefreshing(false);
        }
    };

    useEffect(() => {
        if (!authLoading && user) fetchData();
    }, [authLoading, user]);

    // Poll every 30s
    useEffect(() => {
        if (!authLoading && user) {
            const id = setInterval(fetchData, 30000);
            return () => clearInterval(id);
        }
    }, [authLoading, user]);

    if (authLoading || (loadingData && !lastUpdated)) {
        return (
            <div className="flex items-center justify-center p-12">
                <div className="animate-pulse flex flex-col items-center">
                    <Activity className="h-8 w-8 text-primary mb-4 animate-bounce" />
                    <span className="text-muted-foreground">{t('botHealth.checking')}</span>
                </div>
            </div>
        );
    }

    const allHealthy = status.backend === 'healthy' && status.database === 'healthy' && status.discord === 'healthy';

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
                        {t('botHealth.title')}
                        <span className="relative flex h-3 w-3">
                            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${allHealthy ? 'bg-green-400' : 'bg-yellow-400'}`} />
                            <span className={`relative inline-flex rounded-full h-3 w-3 ${allHealthy ? 'bg-green-500' : 'bg-yellow-500'}`} />
                        </span>
                    </h1>
                    <p className="text-muted-foreground mt-1">{t('botHealth.subtitle')}</p>
                </div>

                <div className="flex items-center gap-4 text-sm text-muted-foreground bg-card p-2 rounded-lg border border-border shadow-sm">
                    {lastUpdated && (
                        <div className="flex items-center gap-2">
                            <Clock size={14} />
                            <span>{t('botHealth.updatedAt', { time: lastUpdated.toLocaleTimeString() })}</span>
                        </div>
                    )}
                    <button
                        onClick={fetchData}
                        disabled={refreshing}
                        className={`p-2 hover:bg-muted rounded-full transition-all ${refreshing ? 'animate-spin text-primary' : 'hover:text-primary'}`}
                        title={t('botHealth.refreshTitle')}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <StatusCard title={t('botHealth.serviceBackend')}  status={status.backend}  icon={Server}   description={t('botHealth.serviceBackendDesc')} />
                <StatusCard title={t('botHealth.serviceDatabase')} status={status.database} icon={Database} description={t('botHealth.serviceDatabaseDesc')} />
                <StatusCard title={t('botHealth.serviceDiscord')}  status={status.discord}  icon={Activity} description={t('botHealth.serviceDiscordDesc')} />
            </div>

            <p className="text-xs text-center text-muted-foreground">
                {t('botHealth.autoRefresh')}
            </p>
        </div>
    );
}

function StatusCard({ title, status, icon: Icon, description }: { title: string; status: ServiceStatus; icon: any; description: string }) {
    const { t } = useTranslation();
    const isHealthy  = status === 'healthy';
    const isDegraded = status === 'degraded';

    const colorClass  = isHealthy ? 'text-green-500'  : isDegraded ? 'text-yellow-500'  : 'text-destructive';
    const bgClass     = isHealthy ? 'bg-green-500/10 border-green-500/30'   : isDegraded ? 'bg-yellow-500/10 border-yellow-500/30'   : 'bg-destructive/10 border-destructive/30';
    const iconBgClass = isHealthy ? 'bg-green-500/20' : isDegraded ? 'bg-yellow-500/20' : 'bg-destructive/20';
    const statusText  = isHealthy ? t('botHealth.statusOperational') : isDegraded ? t('botHealth.statusDegraded') : t('botHealth.statusIssues');

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

export default withPermission(BotHealthPage, PermissionLevel.AUTHORIZED);
