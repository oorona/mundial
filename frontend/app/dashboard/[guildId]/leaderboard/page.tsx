'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';
import { subscribeSSE } from '@/lib/streaming';

interface Row { position: number; user_id: string; username: string; points: number; exactos: number; aciertos: number; jugados: number; }
export interface TodayMatch {
  id: number; home: string | null; away: string | null; home_code: string; away_code: string;
  finished: boolean; home_score: number | null; away_score: number | null; kickoff_unix: number | null;
}
export interface TodayPlayer {
  user_id: string; username: string; points: number;
  picks: Record<string, { home: number; away: number; points: number }>;
}
export interface TodayBoard { date: string; matches: TodayMatch[]; players: TodayPlayer[]; }

interface BreakdownGame {
  match_id: number; round_code: string; home: string | null; away: string | null;
  home_code: string; away_code: string; home_score: number; away_score: number;
  kickoff_unix: number | null; pred_home: number; pred_away: number; points: number;
}
interface Breakdown {
  user_id: string; username: string; total_points: number; games_scored: number;
  exactos: number; games: BreakdownGame[];
}

function LeaderboardPage() {
  const { t } = useTranslation();
  const guildId = useParams().guildId as string;
  const [reconUser, setReconUser] = useState<{ id: string; name: string } | null>(null);
  const [tab, setTab] = useState<'global' | 'today' | 'daily'>('global');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [today, setToday] = useState<TodayBoard | null>(null);

  const load = useCallback(() => {
    if (tab === 'today') {
      setToday(null);
      apiClient.get<TodayBoard>(`/guilds/${guildId}/leaderboard/today`)
        .then(setToday)
        .catch(() => setToday({ date: '', matches: [], players: [] }));
      return;
    }
    const path = tab === 'daily' ? `/guilds/${guildId}/leaderboard/daily` : `/guilds/${guildId}/leaderboard`;
    setRows(null);
    apiClient.get<{ standings: Row[] }>(path).then((d) => setRows(d.standings)).catch(() => setRows([]));
  }, [guildId, tab]);

  useEffect(() => {
    load();
    const sub = subscribeSSE(`/guilds/${guildId}/leaderboard/stream`, () => load());
    return () => sub.close();
  }, [guildId, load]);

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('leaderboard.title')}</h1>
        <p className="text-muted-foreground">
          {tab === 'today' ? t('leaderboard.todayTitle') : tab === 'daily' ? t('leaderboard.dailyTitle') : t('leaderboard.description')}
        </p>
      </div>
      <div className="flex gap-2">
        {(['global', 'today', 'daily'] as const).map((k) => (
          <button key={k} onClick={() => setTab(k)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>
            {t(k === 'today' ? 'leaderboard.tabToday' : k === 'daily' ? 'leaderboard.tabDaily' : 'leaderboard.tabGlobal')}
          </button>
        ))}
      </div>
      {tab === 'today'
        ? <TodayPicksBoard data={today} />
        : <LeaderboardTable rows={rows} emptyText={t(tab === 'daily' ? 'leaderboard.dailyEmpty' : 'leaderboard.empty')}
            onUser={(id, name) => setReconUser({ id, name })} />}
      {reconUser && (
        <ReconciliationModal guildId={guildId} userId={reconUser.id} fallbackName={reconUser.name}
          onClose={() => setReconUser(null)} />
      )}
    </div>
  );
}

// Click a player → audit every scored pick against the real result; the per-game
// points sum to the leaderboard total, so the standings can be reconciled by hand.
function ReconciliationModal({ guildId, userId, fallbackName, onClose }:
  { guildId: string; userId: string; fallbackName: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [data, setData] = useState<Breakdown | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    apiClient.get<Breakdown>(`/guilds/${guildId}/leaderboard/user/${userId}`)
      .then(setData).catch(() => setError(true));
  }, [guildId, userId]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-bold text-foreground">{data?.username || fallbackName}</h2>
            <p className="text-xs text-muted-foreground">{t('leaderboard.reconTitle')}</p>
          </div>
          <button onClick={onClose} aria-label="close"
            className="ml-2 shrink-0 rounded px-2 py-1 text-muted-foreground hover:text-foreground">✕</button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {error ? <p className="p-4 text-sm text-muted-foreground">{t('fixturesActivity.error')}</p>
          : data === null ? <p className="p-4 text-sm text-muted-foreground">{t('common.loading')}</p>
          : data.games.length === 0 ? <p className="p-4 text-sm text-muted-foreground">{t('leaderboard.reconEmpty')}</p>
          : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">{t('leaderboard.reconMatch')}</th>
                  <th className="px-3 py-2 text-center">{t('leaderboard.reconResult')}</th>
                  <th className="px-3 py-2 text-center">{t('leaderboard.reconPick')}</th>
                  <th className="px-3 py-2 text-right">{t('leaderboard.points')}</th>
                </tr>
              </thead>
              <tbody>
                {data.games.map((g) => {
                  const exact = g.pred_home === g.home_score && g.pred_away === g.away_score;
                  return (
                    <tr key={g.match_id} className="border-t border-border text-foreground">
                      <td className="px-3 py-2"><span className="opacity-50">#{g.match_id}</span> {g.home_code}–{g.away_code}</td>
                      <td className="px-3 py-2 text-center font-semibold">{g.home_score}–{g.away_score}</td>
                      <td className={`px-3 py-2 text-center ${exact ? 'font-semibold text-emerald-600' : ''}`}>{g.pred_home}–{g.pred_away}</td>
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{g.points}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="sticky bottom-0 border-t-2 border-border bg-card text-foreground">
                <tr>
                  <td className="px-3 py-2.5 font-semibold" colSpan={3}>
                    {t('leaderboard.reconTotal')} · {data.games_scored} {t('leaderboard.reconGames')} · {data.exactos} {t('leaderboard.exact')}
                  </td>
                  <td className="px-3 py-2.5 text-right text-base font-bold tabular-nums">{data.total_points}</td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// Today's picks board: one row per participant, one column per match, each cell
// the exact scoreline that player predicted (highlighted when it hit exactly).
export function TodayPicksBoard({ data }: { data: TodayBoard | null }) {
  const { t } = useTranslation();
  if (data === null) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (data.matches.length === 0) return <p className="text-muted-foreground">{t('leaderboard.todayEmpty')}</p>;
  if (data.players.length === 0) return <p className="text-muted-foreground">{t('leaderboard.todayNoPicks')}</p>;
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        {data.matches.map((m) => (
          <div key={m.id} className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-1.5 text-sm">
            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">#{m.id}</span>
            <span className="min-w-0 flex-1 truncate text-foreground">
              {m.home ?? '—'} <span className="text-muted-foreground">vs</span> {m.away ?? '—'}
            </span>
            <span className="shrink-0 text-muted-foreground">
              {m.kickoff_unix
                ? new Date(m.kickoff_unix * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
                : '—'}
            </span>
            {m.finished && m.home_score !== null && m.away_score !== null && (
              <span className="shrink-0 font-semibold text-emerald-600">
                {t('leaderboard.final')} {m.home_score}–{m.away_score}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">{t('leaderboard.player')}</th>
              {data.matches.map((m) => (
                <th key={m.id} className="whitespace-nowrap px-3 py-2 text-center">
                  <span className="opacity-70">#{m.id}</span> {m.home_code}–{m.away_code}
                </th>
              ))}
              <th className="px-3 py-2 text-right">{t('leaderboard.points')}</th>
            </tr>
          </thead>
          <tbody>
            {data.matches.some((m) => m.finished && m.home_score !== null && m.away_score !== null) && (
              <tr className="border-t border-border bg-muted/40 text-foreground">
                <td className="whitespace-nowrap px-3 py-2 font-semibold">{t('leaderboard.todayResult')}</td>
                {data.matches.map((m) => (
                  <td key={m.id} className="px-3 py-2 text-center font-semibold">
                    {m.finished && m.home_score !== null && m.away_score !== null
                      ? `${m.home_score}–${m.away_score}`
                      : <span className="font-normal text-muted-foreground">—</span>}
                  </td>
                ))}
                <td className="px-3 py-2" />
              </tr>
            )}
            {data.players.map((p) => (
              <tr key={p.user_id} className="border-t border-border text-foreground">
                <td className="whitespace-nowrap px-3 py-2">{p.username}</td>
                {data.matches.map((m) => {
                  const pick = p.picks[String(m.id)];
                  const decided = m.finished && m.home_score !== null && m.away_score !== null;
                  const exact = !!pick && decided && pick.home === m.home_score && pick.away === m.away_score;
                  return (
                    <td key={m.id} className="px-3 py-2 text-center">
                      {pick
                        ? <span className={exact ? 'rounded bg-emerald-500/15 px-1.5 py-0.5 font-semibold text-emerald-600' : ''}>
                            {pick.home}–{pick.away}
                          </span>
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-right font-semibold">{p.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{t('leaderboard.todayLegend')}</p>
    </div>
  );
}

export function LeaderboardTable({ rows, emptyText, onUser }:
  { rows: Row[] | null; emptyText?: string; onUser?: (id: string, name: string) => void }) {
  const { t } = useTranslation();
  if (rows === null) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (rows.length === 0) return <p className="text-muted-foreground">{emptyText ?? t('leaderboard.empty')}</p>;
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">{t('leaderboard.position')}</th>
            <th className="px-3 py-2 text-left">{t('leaderboard.player')}</th>
            <th className="px-3 py-2 text-right">{t('leaderboard.points')}</th>
            <th className="px-3 py-2 text-right">{t('leaderboard.exact')}</th>
            <th className="px-3 py-2 text-right">{t('leaderboard.correct')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.user_id} className="border-t border-border text-foreground">
              <td className="px-3 py-2">{r.position}</td>
              <td className="px-3 py-2">
                {onUser
                  ? <button onClick={() => onUser(r.user_id, r.username)}
                      className="text-left font-medium text-primary underline-offset-2 hover:underline">{r.username}</button>
                  : r.username}
              </td>
              <td className="px-3 py-2 text-right font-semibold">{r.points}</td>
              <td className="px-3 py-2 text-right">{r.exactos}</td>
              <td className="px-3 py-2 text-right">{r.aciertos}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default withPermission(LeaderboardPage, PermissionLevel.USER);
