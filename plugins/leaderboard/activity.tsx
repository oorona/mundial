'use client';

import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity, getActivityGuildId } from '@/lib/activity';
import { apiClient } from '@/app/api-client';
import { subscribeSSE } from '@/lib/streaming';

interface Row { position: number; user_id: string; username: string; points: number; exactos: number; aciertos: number; }
interface TodayMatch {
  id: number; home: string | null; away: string | null; home_code: string; away_code: string;
  finished: boolean; home_score: number | null; away_score: number | null; kickoff_unix: number | null;
}
interface TodayPlayer {
  user_id: string; username: string; points: number;
  picks: Record<string, { home: number; away: number; points: number }>;
}
interface TodayBoard { date: string; matches: TodayMatch[]; players: TodayPlayer[]; }

interface BreakdownGame {
  match_id: number; round_code: string; home: string | null; away: string | null;
  home_code: string; away_code: string; home_score: number; away_score: number;
  kickoff_unix: number | null; pred_home: number; pred_away: number; points: number;
}
interface Breakdown {
  user_id: string; username: string; total_points: number; games_scored: number;
  exactos: number; games: BreakdownGame[];
}

// Click a player on any standings list → audit every scored pick of theirs against
// the real result, with the per-game points summing to the leaderboard total. Stays
// in-page (Activity SDK can't navigate between /activity/* routes).
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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-2 sm:items-center" onClick={onClose}>
      <div className="flex max-h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate font-bold">{data?.username || fallbackName}</h2>
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
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted text-[11px] text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">{t('leaderboard.reconMatch')}</th>
                  <th className="px-2 py-1.5 text-center">{t('leaderboard.reconResult')}</th>
                  <th className="px-2 py-1.5 text-center">{t('leaderboard.reconPick')}</th>
                  <th className="px-2 py-1.5 text-right">{t('leaderboard.points')}</th>
                </tr>
              </thead>
              <tbody>
                {data.games.map((g) => {
                  const exact = g.pred_home === g.home_score && g.pred_away === g.away_score;
                  return (
                    <tr key={g.match_id} className="border-t border-border/60">
                      <td className="px-2 py-1.5"><span className="opacity-50">#{g.match_id}</span> {g.home_code}–{g.away_code}</td>
                      <td className="px-2 py-1.5 text-center font-semibold">{g.home_score}–{g.away_score}</td>
                      <td className={`px-2 py-1.5 text-center ${exact ? 'font-semibold text-emerald-500' : ''}`}>{g.pred_home}–{g.pred_away}</td>
                      <td className="px-2 py-1.5 text-right font-semibold tabular-nums">{g.points}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="sticky bottom-0 border-t-2 border-border bg-card">
                <tr>
                  <td className="px-2 py-2 font-semibold" colSpan={3}>
                    {t('leaderboard.reconTotal')} · {data.games_scored} {t('leaderboard.reconGames')} · {data.exactos} {t('leaderboard.exact')}
                  </td>
                  <td className="px-2 py-2 text-right text-sm font-bold tabular-nums">{data.total_points}</td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function LeaderboardActivity() {
  const { t } = useTranslation();
  const [guildId, setGuildId] = useState<string | null>(null);
  const [tab, setTab] = useState<'global' | 'today' | 'daily'>('global');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [today, setToday] = useState<TodayBoard | null>(null);
  const [reconUser, setReconUser] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    // Reuse the guild the hub captured (no re-handshake); else handshake; else
    // show the empty state rather than spinning on "loading" forever.
    const gid = getActivityGuildId();
    if (gid) { setGuildId(gid); return; }
    initActivity()
      .then((s) => { if (s?.guild_id) setGuildId(String(s.guild_id)); else setRows([]); })
      .catch(() => setRows([]));
  }, []);

  const load = useCallback(() => {
    if (!guildId) return;
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
    if (!guildId) return;
    load();
    const sub = subscribeSSE(`/guilds/${guildId}/leaderboard/stream`, () => load());
    return () => sub.close();
  }, [guildId, load]);

  return (
    <div className="min-h-screen bg-background p-4 text-foreground">
      <a href="/activity/inicio" className="mb-3 inline-block text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.navHome')}</a>
      <h1 className="mb-3 text-xl font-bold">{t('leaderboard.title')}</h1>
      <div className="mb-3 flex gap-2">
        {(['global', 'today', 'daily'] as const).map((k) => (
          <button key={k} onClick={() => setTab(k)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>
            {t(k === 'today' ? 'leaderboard.tabToday' : k === 'daily' ? 'leaderboard.tabDaily' : 'leaderboard.tabGlobal')}
          </button>
        ))}
      </div>
      {tab === 'today' ? (
        today === null ? <p className="text-muted-foreground">{t('common.loading')}</p>
        : today.matches.length === 0 ? <p className="text-muted-foreground">{t('leaderboard.todayEmpty')}</p>
        : today.players.length === 0 ? <p className="text-muted-foreground">{t('leaderboard.todayNoPicks')}</p>
        : (
          <div className="space-y-2">
            <div className="space-y-1">
              {today.matches.map((m) => (
                <div key={m.id} className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm">
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">#{m.id}</span>
                  <span className="min-w-0 flex-1 truncate">{m.home ?? '—'} <span className="text-muted-foreground">vs</span> {m.away ?? '—'}</span>
                  <span className="shrink-0 text-muted-foreground">
                    {m.kickoff_unix ? new Date(m.kickoff_unix * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '—'}
                  </span>
                  {m.finished && m.home_score !== null && m.away_score !== null && (
                    <span className="shrink-0 font-semibold text-emerald-500">
                      {t('leaderboard.final')} {m.home_score}–{m.away_score}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <ol className="space-y-1">
              {today.players.map((p) => (
                <li key={p.user_id} className="rounded-md border border-border bg-card px-3 py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{p.username}</span>
                    <span className="font-semibold">{p.points} pts</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {today.matches.map((m) => {
                      const pick = p.picks[String(m.id)];
                      const decided = m.finished && m.home_score !== null && m.away_score !== null;
                      const exact = !!pick && decided && pick.home === m.home_score && pick.away === m.away_score;
                      return (
                        <span key={m.id}
                          className={`rounded px-1.5 py-0.5 text-xs ${exact ? 'bg-emerald-500/15 font-semibold text-emerald-600' : 'bg-muted text-muted-foreground'}`}>
                          {m.home_code}–{m.away_code} {pick ? `${pick.home}–${pick.away}` : '—'}
                        </span>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted-foreground">{t('leaderboard.todayLegend')}</p>
          </div>
        )
      ) : (
        <>
          {rows === null && <p className="text-muted-foreground">{t('common.loading')}</p>}
          {rows && rows.length === 0 && <p className="text-muted-foreground">{t(tab === 'daily' ? 'leaderboard.dailyEmpty' : 'leaderboard.empty')}</p>}
          {rows && rows.length > 0 && (
            <ol className="space-y-1">
              {rows.map((r) => (
                <li key={r.user_id} className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm">
                  <button onClick={() => setReconUser({ id: r.user_id, name: r.username })}
                    className="flex min-w-0 items-center gap-3 text-left hover:text-primary">
                    <span className="w-6 shrink-0 text-muted-foreground">{r.position}</span>
                    <span className="truncate font-medium underline-offset-2 hover:underline">{r.username}</span>
                  </button>
                  <span className="flex shrink-0 items-center gap-3"><span className="font-semibold">{r.points} pts</span><span className="text-xs text-muted-foreground">{r.exactos} {t('leaderboard.exact')}</span></span>
                </li>
              ))}
            </ol>
          )}
          {rows && rows.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{t('leaderboard.reconHint')}</p>}
        </>
      )}
      {reconUser && guildId && (
        <ReconciliationModal guildId={guildId} userId={reconUser.id} fallbackName={reconUser.name}
          onClose={() => setReconUser(null)} />
      )}
    </div>
  );
}

export default withActivityPage(LeaderboardActivity);
