'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';
import { Users, ChevronLeft, Loader2, Bot } from 'lucide-react';

interface Participant {
  user_id: string;
  username: string | null;
  predictions: number;
  points: number;
  exactos: number;
}
interface Pick {
  match_id: number;
  pred_home: number;
  pred_away: number;
  points: number;
  round: string | null;
  grp: string | null;
  kickoff_unix: number | null;
  finished: boolean;
  home_score: number | null;
  away_score: number | null;
  home: string | null;
  away: string | null;
}

const AI_USER_ID = '1';

function SubmissionsPage() {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';
  const params = useParams();
  const guildId = params?.guildId as string;

  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Participant | null>(null);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [picksLoading, setPicksLoading] = useState(false);

  useEffect(() => {
    if (!guildId) return;
    setLoading(true);
    apiClient.get<{ participants: Participant[] }>(`/guilds/${guildId}/predictions/participants`)
      .then((d) => setParticipants(d.participants || []))
      .catch(() => setParticipants([]))
      .finally(() => setLoading(false));
  }, [guildId]);

  const openUser = useCallback((p: Participant) => {
    setSelected(p);
    setPicks([]);
    setPicksLoading(true);
    apiClient.get<{ predictions: Pick[] }>(`/guilds/${guildId}/predictions/participant/${p.user_id}`)
      .then((d) => setPicks(d.predictions || []))
      .catch(() => setPicks([]))
      .finally(() => setPicksLoading(false));
  }, [guildId]);

  const isAI = (uid: string) => uid === AI_USER_ID;
  const name = (p: Participant) => p.username || `${t('submissions.player')} ${p.user_id.slice(-4)}`;
  const fmtDate = (u: number | null) =>
    u ? new Date(u * 1000).toLocaleDateString(locale, { month: 'short', day: 'numeric' }) : '—';

  // ── Detail: one participant's picks ────────────────────────────────────────
  if (selected) {
    return (
      <div className="mx-auto max-w-3xl space-y-5 p-4">
        <button onClick={() => setSelected(null)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-4 w-4" /> {t('submissions.back')}
        </button>
        <div className="flex items-center gap-3">
          {isAI(selected.user_id) ? <Bot className="h-7 w-7 text-fuchsia-500" /> : <Users className="h-7 w-7 text-amber-500" />}
          <div>
            <h1 className="text-2xl font-bold text-foreground">{name(selected)}</h1>
            <p className="text-sm text-muted-foreground">
              {t('submissions.summary', {
                points: String(selected.points),
                predictions: String(selected.predictions),
                exactos: String(selected.exactos),
              })}
            </p>
          </div>
        </div>

        {picksLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
        {!picksLoading && picks.length === 0 && (
          <p className="text-muted-foreground">{t('submissions.noPicks')}</p>
        )}

        <div className="space-y-2">
          {picks.map((p) => {
            const decided = p.finished && p.home_score !== null && p.away_score !== null;
            const exact = decided && p.pred_home === p.home_score && p.pred_away === p.away_score;
            return (
              <div key={p.match_id} className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
                <span className="w-12 shrink-0 text-xs text-muted-foreground">{fmtDate(p.kickoff_unix)}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground">
                    {p.home ?? '—'} <span className="text-muted-foreground">vs</span> {p.away ?? '—'}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('submissions.pick')}: <span className="font-semibold text-foreground">{p.pred_home}–{p.pred_away}</span>
                    {decided && <> · {t('submissions.result')}: {p.home_score}–{p.away_score}</>}
                  </div>
                </div>
                {exact && (
                  <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-600">
                    {t('submissions.exact')}
                  </span>
                )}
                <span className="w-12 shrink-0 text-right text-sm font-semibold text-foreground">
                  {p.points} <span className="text-xs font-normal text-muted-foreground">{t('submissions.pts')}</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ── List: all participants ─────────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4">
      <div className="flex items-center gap-3">
        <Users className="h-7 w-7 text-amber-500" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t('submissions.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('submissions.subtitle')}</p>
        </div>
      </div>

      {loading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
      {!loading && participants.length === 0 && (
        <p className="text-muted-foreground">{t('submissions.empty')}</p>
      )}

      <div className="space-y-2">
        {participants.map((p) => (
          <button key={p.user_id} onClick={() => openUser(p)}
            className="flex w-full items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition hover:border-amber-500/50">
            {isAI(p.user_id) ? <Bot className="h-5 w-5 shrink-0 text-fuchsia-500" /> : <Users className="h-5 w-5 shrink-0 text-muted-foreground" />}
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-foreground">{name(p)}</div>
              <div className="text-xs text-muted-foreground">
                {t('submissions.countLabel', { count: String(p.predictions) })} · {p.exactos} {t('submissions.exactPlural')}
              </div>
            </div>
            <span className="shrink-0 text-sm font-semibold text-foreground">
              {p.points} <span className="text-xs font-normal text-muted-foreground">{t('submissions.pts')}</span>
            </span>
            <ChevronLeft className="h-4 w-4 shrink-0 rotate-180 text-muted-foreground" />
          </button>
        ))}
      </div>
    </div>
  );
}

export default withPermission(SubmissionsPage, PermissionLevel.OWNER);
