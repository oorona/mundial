'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';
import { Users, ChevronLeft, ChevronDown, Loader2, Bot, CalendarDays } from 'lucide-react';

interface DaySummary {
  day: string; // YYYY-MM-DD (CDMX match day)
  matches: number;
  players: number;
  predictions: number;
  points: number;
}
interface DayMatch {
  match_id: number;
  kickoff_unix: number | null;
  finished: boolean;
  home_score: number | null;
  away_score: number | null;
  home: string | null;
  away: string | null;
}
interface DayUser {
  user_id: string;
  username: string | null;
  predictions: number;
  points: number;
  exactos: number;
}
interface DayPick {
  user_id: string;
  match_id: number;
  pred_home: number;
  pred_away: number;
  points: number;
}
interface DayDetail {
  day: string;
  matches: DayMatch[];
  users: DayUser[];
  picks: DayPick[];
}

const AI_USER_ID = '1';

function DailyScoresPage() {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';
  const params = useParams();
  const guildId = params?.guildId as string;

  const [days, setDays] = useState<DaySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<DaySummary | null>(null);
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    setLoading(true);
    apiClient.get<{ days: DaySummary[] }>(`/guilds/${guildId}/predictions/days`)
      .then((d) => setDays(d.days || []))
      .catch(() => setDays([]))
      .finally(() => setLoading(false));
  }, [guildId]);

  const openDay = useCallback((d: DaySummary) => {
    setSelected(d);
    setDetail(null);
    setExpanded(null);
    setDetailLoading(true);
    apiClient.get<DayDetail>(`/guilds/${guildId}/predictions/day/${d.day}`)
      .then((r) => setDetail(r))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [guildId]);

  const isAI = (uid: string) => uid === AI_USER_ID;
  const name = (u: DayUser) => u.username || `${t('dailyScores.player')} ${u.user_id.slice(-4)}`;
  // Noon avoids the date shifting a day in browsers west of UTC.
  const fmtDay = (day: string) =>
    new Date(`${day}T12:00:00`).toLocaleDateString(locale, { weekday: 'long', month: 'long', day: 'numeric' });
  const fmtTime = (u: number | null) =>
    u ? new Date(u * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }) : '—';

  // ── Detail: everyone's scores for one day ──────────────────────────────────
  if (selected) {
    const matchById = new Map((detail?.matches ?? []).map((m) => [m.match_id, m]));
    const picksByUser = new Map<string, DayPick[]>();
    for (const p of detail?.picks ?? []) {
      const list = picksByUser.get(p.user_id) ?? [];
      list.push(p);
      picksByUser.set(p.user_id, list);
    }
    return (
      <div className="mx-auto max-w-3xl space-y-5 p-4">
        <button onClick={() => setSelected(null)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-4 w-4" /> {t('dailyScores.back')}
        </button>
        <div className="flex items-center gap-3">
          <CalendarDays className="h-7 w-7 text-rose-500" />
          <div>
            <h1 className="text-2xl font-bold capitalize text-foreground">{fmtDay(selected.day)}</h1>
            <p className="text-sm text-muted-foreground">
              {t('dailyScores.daySummary', {
                players: String(selected.players),
                predictions: String(selected.predictions),
              })}
            </p>
          </div>
        </div>

        {detailLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}

        {detail && detail.matches.length > 0 && (
          <div>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {t('dailyScores.matchesTitle')}
            </h2>
            <div className="space-y-1">
              {detail.matches.map((m) => (
                <div key={m.match_id} className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-2">
                  <span className="w-12 shrink-0 text-xs text-muted-foreground">{fmtTime(m.kickoff_unix)}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                    {m.home ?? '—'} <span className="text-muted-foreground">vs</span> {m.away ?? '—'}
                  </span>
                  <span className="shrink-0 text-sm font-semibold text-foreground">
                    {m.finished && m.home_score !== null && m.away_score !== null
                      ? `${m.home_score}–${m.away_score}`
                      : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {detail && detail.users.length === 0 && !detailLoading && (
          <p className="text-muted-foreground">{t('dailyScores.noPicks')}</p>
        )}

        {detail && detail.users.length > 0 && (
          <div>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {t('dailyScores.scoresTitle')}
            </h2>
            <div className="space-y-2">
              {detail.users.map((u, i) => {
                const open = expanded === u.user_id;
                const picks = picksByUser.get(u.user_id) ?? [];
                return (
                  <div key={u.user_id} className="rounded-lg border border-border bg-card">
                    <button onClick={() => setExpanded(open ? null : u.user_id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:border-rose-500/50">
                      <span className="w-6 shrink-0 text-sm font-semibold text-muted-foreground">{i + 1}</span>
                      {isAI(u.user_id) ? <Bot className="h-5 w-5 shrink-0 text-fuchsia-500" /> : <Users className="h-5 w-5 shrink-0 text-muted-foreground" />}
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-foreground">{name(u)}</div>
                        <div className="text-xs text-muted-foreground">
                          {t('dailyScores.countLabel', { count: String(u.predictions) })} · {u.exactos} {t('dailyScores.exactPlural')}
                        </div>
                      </div>
                      <span className="shrink-0 text-sm font-semibold text-foreground">
                        {u.points} <span className="text-xs font-normal text-muted-foreground">{t('dailyScores.pts')}</span>
                      </span>
                      <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition ${open ? 'rotate-180' : ''}`} />
                    </button>
                    {open && (
                      <div className="space-y-1 border-t border-border px-4 py-2">
                        {picks.map((p) => {
                          const m = matchById.get(p.match_id);
                          const decided = m?.finished && m.home_score !== null && m.away_score !== null;
                          const exact = decided && p.pred_home === m!.home_score && p.pred_away === m!.away_score;
                          return (
                            <div key={p.match_id} className="flex items-center gap-3 py-1 text-sm">
                              <span className="min-w-0 flex-1 truncate text-foreground">
                                {m?.home ?? '—'} <span className="text-muted-foreground">vs</span> {m?.away ?? '—'}
                              </span>
                              <span className="shrink-0 text-xs text-muted-foreground">
                                {t('dailyScores.pick')}: <span className="font-semibold text-foreground">{p.pred_home}–{p.pred_away}</span>
                                {decided && <> · {t('dailyScores.result')}: {m!.home_score}–{m!.away_score}</>}
                              </span>
                              {exact && (
                                <span className="shrink-0 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-600">
                                  {t('dailyScores.exact')}
                                </span>
                              )}
                              <span className="w-10 shrink-0 text-right font-semibold text-foreground">
                                {p.points} <span className="text-xs font-normal text-muted-foreground">{t('dailyScores.pts')}</span>
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── List: all match days with predictions ──────────────────────────────────
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4">
      <div className="flex items-center gap-3">
        <CalendarDays className="h-7 w-7 text-rose-500" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t('dailyScores.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('dailyScores.subtitle')}</p>
        </div>
      </div>

      {loading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
      {!loading && days.length === 0 && (
        <p className="text-muted-foreground">{t('dailyScores.empty')}</p>
      )}

      <div className="space-y-2">
        {days.map((d) => (
          <button key={d.day} onClick={() => openDay(d)}
            className="flex w-full items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition hover:border-rose-500/50">
            <CalendarDays className="h-5 w-5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium capitalize text-foreground">{fmtDay(d.day)}</div>
              <div className="text-xs text-muted-foreground">
                {t('dailyScores.matchesLabel', { count: String(d.matches) })} · {t('dailyScores.playersLabel', { count: String(d.players) })} · {t('dailyScores.predictionsLabel', { count: String(d.predictions) })}
              </div>
            </div>
            <span className="shrink-0 text-sm font-semibold text-foreground">
              {d.points} <span className="text-xs font-normal text-muted-foreground">{t('dailyScores.pts')}</span>
            </span>
            <ChevronLeft className="h-4 w-4 shrink-0 rotate-180 text-muted-foreground" />
          </button>
        ))}
      </div>
    </div>
  );
}

export default withPermission(DailyScoresPage, PermissionLevel.OWNER);
