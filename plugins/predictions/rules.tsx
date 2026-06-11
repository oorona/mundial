'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity, getActivityGuildId } from '@/lib/activity';
import { apiClient } from '@/app/api-client';

interface Rules {
  weight_exact: number; weight_diff: number; weight_tendency: number;
  knockout_multiplier: number; lock_lead_minutes: number;
}
const DEFAULTS: Rules = { weight_exact: 4, weight_diff: 3, weight_tendency: 2, knockout_multiplier: 2, lock_lead_minutes: 0 };

function RulesActivity() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<Rules>(DEFAULTS);

  useEffect(() => {
    const load = (id: string) =>
      apiClient.get<Rules>(`/guilds/${id}/predictions/rules`).then(setRules).catch(() => setRules(DEFAULTS));
    const gid = getActivityGuildId();
    if (gid) { load(gid); return; }
    initActivity()
      .then((s) => (s?.guild_id ? load(String(s.guild_id)) : setRules(DEFAULTS)))
      .catch(() => setRules(DEFAULTS));
  }, []);

  const Row = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-center justify-between border-b border-border py-2 last:border-0">
      <span>{label}</span><span className="font-semibold">{value}</span>
    </div>
  );

  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <a href="/activity/inicio" className="mb-3 inline-block text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.navHome')}</a>
      <h1 className="mb-1 text-xl font-bold">{t('predictions.rulesTitle')}</h1>
      <p className="mb-4 text-sm text-muted-foreground">{t('predictions.rulesIntro')}</p>
      <div className="mx-auto max-w-md rounded-lg border border-border bg-card p-4 text-sm">
        <Row label={t('predictions.ruleParticipation')} value="1 pt" />
        <Row label={t('predictions.ruleExact')} value={`+${rules.weight_exact}`} />
        <Row label={t('predictions.ruleDiff')} value={`+${rules.weight_diff}`} />
        <Row label={t('predictions.ruleTendency')} value={`+${rules.weight_tendency}`} />
        <Row label={t('predictions.ruleKnockout')} value={`×${rules.knockout_multiplier}`} />
      </div>
      <p className="mx-auto mt-3 max-w-md text-xs text-muted-foreground">{t('predictions.lockNote')}</p>
    </div>
  );
}

export default withActivityPage(RulesActivity);
