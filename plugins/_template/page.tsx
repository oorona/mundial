'use client';

import { useState, useEffect } from 'react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';

interface Props {
  params: { guildId: string };
}

function MyPluginPage({ params }: Props) {
  const { t } = useTranslation();
  const { guildId } = params;
  const [settings, setSettings] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get(`/api/v1/guilds/${guildId}/my-plugin/settings`)
      .then((data) => setSettings(data))
      .finally(() => setLoading(false));
  }, [guildId]);

  if (loading) {
    return <p className="text-muted-foreground">{t('common.loading')}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">
          {t('myPlugin.title')}
        </h1>
        <p className="text-muted-foreground">{t('myPlugin.description')}</p>
      </div>

      <div className="rounded-lg border border-border bg-card p-6">
        {/* Plugin UI goes here — use semantic design tokens only */}
        <p className="text-foreground">{t('myPlugin.comingSoon')}</p>
      </div>
    </div>
  );
}

// Every dashboard page must be exported through withPermission — no bare exports.
export default withPermission(MyPluginPage, PermissionLevel.AUTHORIZED);
