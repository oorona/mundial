'use client';

import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity, getActivityGuildId } from '@/lib/activity';
import { apiClient } from '@/app/api-client';
import { subscribeSSE } from '@/lib/streaming';

interface TeamBrief { name: string | null; flag_url: string | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; home: MatchSide; away: MatchSide;
  home_score: number | null; away_score: number | null;
  finished: boolean; time_elapsed: string | null; kickoff_unix: number | null;
}

function inWindow(m: MatchBrief): boolean {
  if (!m.kickoff_unix) return false;
  const now = Math.floor(Date.now() / 1000);
  return m.kickoff_unix - 300 <= now && now <= m.kickoff_unix + 3 * 3600;
}

function LiveActivity() {
  const { t } = useTranslation();
  const [guildId, setGuildId] = useState<string | null>(null);
  const [matches, setMatches] = useState<MatchBrief[]>([]);

  useEffect(() => {
    const gid = getActivityGuildId();
    if (gid) { setGuildId(gid); return; }
    initActivity().then((s) => setGuildId(s?.guild_id ? String(s.guild_id) : '')).catch(() => setGuildId(''));
  }, []);

  const load = useCallback(() => {
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today').then((d) => setMatches(d.matches)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    if (!guildId) return;
    const sub = subscribeSSE(`/guilds/${guildId}/live-tracker/stream`, () => load());
    return () => sub.close();
  }, [guildId, load]);

  const live = matches.filter(inWindow);
  const sideName = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? '';

  return (
    <div className="min-h-screen bg-background p-4 text-foreground">
      <a href="/activity/inicio" className="mb-3 inline-block text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.navHome')}</a>
      <h1 className="mb-3 text-xl font-bold">{t('liveTracker.title')}</h1>
      {live.length === 0 && <p className="text-muted-foreground">{t('liveTracker.noLive')}</p>}
      <div className="space-y-2">
        {live.map((m) => (
          <div key={m.id} className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm">
            <span>{sideName(m.home)}</span>
            <span className="font-bold">{m.home_score ?? 0}–{m.away_score ?? 0}</span>
            <span>{sideName(m.away)}</span>
            <span className="ml-2 text-xs text-muted-foreground">{m.finished ? t('liveTracker.final') : (m.time_elapsed || t('liveTracker.live'))}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default withActivityPage(LiveActivity);
