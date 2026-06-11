'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';

interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; home: MatchSide; away: MatchSide;
  finished: boolean; kickoff_unix: number | null;
  stadium: { city: string | null; country: string | null } | null;
}

function Flag({ team }: { team: TeamBrief | null }) {
  if (!team?.flag_url) return <span className="text-muted-foreground">—</span>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={team.flag_url} alt={team.name ?? ''} className="inline-block h-4 w-6 rounded-sm object-cover align-middle" />;
}

function FixturesPage() {
  const { t } = useTranslation();
  const guildId = useParams().guildId as string;
  const [matches, setMatches] = useState<MatchBrief[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today')
      .then((d) => { setMatches(d.matches.filter((m) => !m.finished).slice(0, 12)); setError(false); })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const sideName = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? t('fixturesActivity.tbd');
  const localTime = (u: number | null) => { try { return u ? new Date(u * 1000).toLocaleString() : ''; } catch { return ''; } };

  // Country name links to its full stats on the World Cup page (same view everywhere).
  const TeamLink = ({ side }: { side: MatchSide }) =>
    side.team?.id
      ? <Link href={`/dashboard/${guildId}/worldcup?team=${side.team.id}`} className="hover:underline">{sideName(side)}</Link>
      : <span>{sideName(side)}</span>;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('fixturesActivity.title')}</h1>
        <p className="text-muted-foreground">{t('fixturesActivity.description')}</p>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        {t('fixturesActivity.launchHint')}
      </div>

      <div>
        <h2 className="mb-2 font-semibold text-foreground">{t('fixturesActivity.upcoming')}</h2>
        {loading && <p className="text-muted-foreground">{t('common.loading')}</p>}
        {error && !loading && <p className="text-destructive">{t('fixturesActivity.error')}</p>}
        {!loading && !error && matches && matches.length === 0 && (
          <p className="text-muted-foreground">{t('fixturesActivity.noMatches')}</p>
        )}
        <div className="space-y-2">
          {(matches ?? []).map((m) => (
            <div key={m.id} className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground">
              <span className="flex items-center gap-2"><Flag team={m.home.team} /> <TeamLink side={m.home} /></span>
              <span className="text-muted-foreground">{localTime(m.kickoff_unix) || t('fixturesActivity.vs')}</span>
              <span className="flex items-center gap-2"><TeamLink side={m.away} /> <Flag team={m.away.team} /></span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default withPermission(FixturesPage, PermissionLevel.USER);
