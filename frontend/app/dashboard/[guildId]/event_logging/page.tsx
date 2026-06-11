'use client';

import { useEffect, useState } from 'react';
import { FileText, CheckCircle, XCircle, AlertCircle, Hash, Settings } from 'lucide-react';
import Link from 'next/link';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';

interface Props {
  params: { guildId: string };
}

interface LoggingSettings {
  logging_enabled: boolean;
  logging_channel_id: string | null;
  logging_ignored_events: string[];
}

const ALL_EVENTS = [
  { key: 'on_message_delete', labelKey: 'eventLogging.events.messageDelete' },
  { key: 'on_message_edit',   labelKey: 'eventLogging.events.messageEdit' },
  { key: 'on_member_join',    labelKey: 'eventLogging.events.memberJoin' },
  { key: 'on_member_remove',  labelKey: 'eventLogging.events.memberLeave' },
];

function EventLoggingPage({ params }: Props) {
  const { t } = useTranslation();
  const { guildId } = params;

  const [settings, setSettings] = useState<LoggingSettings | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get(`/api/v1/guilds/${guildId}/event-logging/settings`)
      .then((data) => setSettings(data as LoggingSettings))
      .catch(() => setError(t('eventLogging.loadError')))
      .finally(() => setLoading(false));
  }, [guildId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[30vh]">
        <div className="w-6 h-6 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !settings) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive">
        <AlertCircle size={18} />
        <p>{error ?? t('eventLogging.loadError')}</p>
      </div>
    );
  }

  const activeEvents  = ALL_EVENTS.filter(e => !settings.logging_ignored_events.includes(e.key));
  const ignoredEvents = ALL_EVENTS.filter(e =>  settings.logging_ignored_events.includes(e.key));

  return (
    <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10">
            <FileText size={20} className="text-amber-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">{t('eventLogging.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('eventLogging.description')}</p>
          </div>
        </div>
        <Link
          href={`/dashboard/${guildId}/settings`}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Settings size={14} />
          {t('eventLogging.configureLink')}
        </Link>
      </div>

      {/* Status card */}
      <div className="rounded-lg border border-border bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          {t('eventLogging.statusSection')}
        </h2>
        <div className="flex flex-col gap-3">

          {/* Enabled / disabled */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-foreground">{t('eventLogging.enabledLabel')}</span>
            {settings.logging_enabled ? (
              <span className="flex items-center gap-1.5 text-sm font-medium text-green-400">
                <CheckCircle size={15} /> {t('eventLogging.statusActive')}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <XCircle size={15} /> {t('eventLogging.statusInactive')}
              </span>
            )}
          </div>

          {/* Log channel */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-foreground">{t('eventLogging.channelLabel')}</span>
            {settings.logging_channel_id ? (
              <span className="flex items-center gap-1 text-sm text-foreground">
                <Hash size={13} className="text-muted-foreground" />
                {settings.logging_channel_id}
              </span>
            ) : (
              <span className="text-sm text-muted-foreground">{t('eventLogging.noChannel')}</span>
            )}
          </div>
        </div>
      </div>

      {/* Monitored events */}
      <div className="rounded-lg border border-border bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          {t('eventLogging.eventsSection')}
        </h2>
        <div className="space-y-2">
          {activeEvents.map(ev => (
            <div key={ev.key} className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2">
              <span className="text-sm text-foreground">{t(ev.labelKey)}</span>
              <span className="flex items-center gap-1 text-xs font-medium text-green-400">
                <CheckCircle size={12} /> {t('eventLogging.eventActive')}
              </span>
            </div>
          ))}
          {ignoredEvents.map(ev => (
            <div key={ev.key} className="flex items-center justify-between rounded-md bg-muted/20 px-3 py-2 opacity-50">
              <span className="text-sm text-foreground">{t(ev.labelKey)}</span>
              <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                <XCircle size={12} /> {t('eventLogging.eventIgnored')}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Not configured warning */}
      {!settings.logging_enabled || !settings.logging_channel_id ? (
        <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-400">
          <AlertCircle size={16} />
          <span>{t('eventLogging.notConfiguredHint')}</span>
        </div>
      ) : null}

    </div>
  );
}

// Every dashboard page must be exported through withPermission — no bare exports.
export default withPermission(EventLoggingPage, PermissionLevel.AUTHORIZED);
