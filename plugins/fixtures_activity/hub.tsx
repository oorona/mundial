'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity } from '@/lib/activity';
import { apiClient } from '@/app/api-client';
import { NorthAmericaMap } from '@/lib/na-map';
import { BracketBoard } from '@/lib/bracket';
import { subscribeSSE } from '@/lib/streaming';
import { AnalysisMarkdown } from '@/lib/markdown';
import { useTheme } from 'next-themes';
import { Radio, Home, Target, Trophy, LayoutGrid, Swords, MapPin, Moon, Sun } from 'lucide-react';

// Discord's mobile iframe doesn't reliably expose the OS `prefers-color-scheme`, so
// these let users flip light/dark manually. One lives in the desktop top bar, one in the
// mobile bottom bar.
function useThemeToggle() {
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = mounted && resolvedTheme === 'dark';
  return { isDark, toggle: () => setTheme(isDark ? 'light' : 'dark') };
}

// Bottom-bar variant (mobile): icon + label, matches the nav tabs.
function ThemeNavButton() {
  const { t } = useTranslation();
  const { isDark, toggle } = useThemeToggle();
  return (
    <button onClick={toggle} aria-label={t('fixturesActivity.navTheme')}
      className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium text-muted-foreground transition hover:text-foreground">
      {isDark ? <Sun className="h-5 w-5" aria-hidden="true" /> : <Moon className="h-5 w-5" aria-hidden="true" />}
      <span className="leading-none">{t('fixturesActivity.navTheme')}</span>
    </button>
  );
}

// Top-bar variant (desktop): compact icon button.
function ThemeTopButton() {
  const { t } = useTranslation();
  const { isDark, toggle } = useThemeToggle();
  return (
    <button onClick={toggle} aria-label={t('fixturesActivity.navTheme')}
      className="rounded-md p-2 text-muted-foreground transition hover:bg-muted hover:text-foreground">
      {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
    </button>
  );
}

// ── Types ────────────────────────────────────────────────────────────────────
interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; fifa_code?: string | null; }
interface StandingRow { position: number; team: TeamBrief | null; mp: number; w: number; d: number; l: number; gf: number; ga: number; gd: number; pts: number; }
interface Stadium { id: number; name: string; city: string | null; country: string | null; capacity: number | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; round: string; group: string | null;
  home: MatchSide; away: MatchSide;
  home_score: number | null; away_score: number | null;
  home_pens?: number | null; away_pens?: number | null;
  finished: boolean; time_elapsed?: string | null; kickoff_unix: number | null; stadium?: Stadium | null;
}
interface FeedEvent { type: string; text?: string; home?: string; away?: string; ts?: number; }
interface Group { group: string; standings: StandingRow[]; }
interface TeamDetail {
  team: TeamBrief & { coach?: string; nickname?: string; confederation?: string; wc_appearances?: number; wc_first_year?: number; wc_best_result?: string; fifa_ranking?: number; wikipedia_url?: string };
  players: { id: number; name: string; position: string | null }[];
  matches: MatchBrief[];
}
interface OpenResponse { enabled: boolean; open_match_ids: number[]; picks: Record<string, { home: number; away: number; points: number }>; }
interface Rules { weight_exact: number; weight_diff: number; weight_tendency: number; knockout_multiplier: number; lock_lead_minutes: number; }
interface Section { key: string; title: string; matches: MatchBrief[]; predictableIds: Set<number>; total: number; done: number; }
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

const GROUP_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
const KO_ROUNDS = ['r32', 'r16', 'qf', 'sf', 'third', 'final'];

// Calendar-day key (YYYY-MM-DD) in Mexico City time (fixed UTC-6), so the by-day
// prediction grouping matches the CDMX daily-leaderboard window exactly.
const cdmxDayKey = (unix: number | null | undefined): string => {
  const d = new Date(((unix ?? 0) - 6 * 3600) * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
};

const CITY_COORDS: Record<string, [number, number]> = {
  'mexico': [19.43, -99.13], 'guadalajara': [20.67, -103.35], 'monterrey': [25.69, -100.32],
  'toronto': [43.65, -79.38], 'vancouver': [49.28, -123.12], 'atlanta': [33.75, -84.39],
  'boston': [42.09, -71.26], 'foxborough': [42.09, -71.26], 'dallas': [32.75, -97.08],
  'arlington': [32.75, -97.08], 'houston': [29.76, -95.37], 'kansas': [39.10, -94.58],
  'angeles': [33.95, -118.34], 'inglewood': [33.95, -118.34], 'miami': [25.96, -80.24],
  'york': [40.81, -74.07], 'jersey': [40.81, -74.07], 'rutherford': [40.81, -74.07],
  'philadelphia': [39.90, -75.17], 'francisco': [37.40, -121.97], 'santa clara': [37.40, -121.97],
  'bay area': [37.40, -121.97], 'seattle': [47.59, -122.33],
};
const LON_MIN = -128, LON_MAX = -66, LAT_MIN = 14, LAT_MAX = 54;
function project(lat: number, lon: number): [number, number] {
  const x = ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * 100;
  const y = ((LAT_MAX - lat) / (LAT_MAX - LAT_MIN)) * 100;
  return [Math.max(2, Math.min(98, x)), Math.max(4, Math.min(96, y))];
}
function coordsFor(city: string | null): [number, number] | null {
  if (!city) return null;
  const c = city.toLowerCase();
  for (const key of Object.keys(CITY_COORDS)) if (c.includes(key)) return CITY_COORDS[key];
  return null;
}


function Flag({ team, size = 'h-4 w-6' }: { team: TeamBrief | null; size?: string }) {
  if (!team?.flag_url) return <span className="text-muted-foreground">—</span>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={team.flag_url} alt={team.name ?? ''} className={`inline-block ${size} rounded-sm object-cover align-middle`} />;
}
function Bar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return <div className="h-2 w-full overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>;
}
function MiniGlobe() {
  return (
    <svg viewBox="0 0 64 64" className="h-8 w-8 text-sky-500" aria-hidden="true">
      <circle cx="32" cy="32" r="28" className="fill-sky-500/10 stroke-current" strokeWidth="2" />
      <ellipse cx="32" cy="32" rx="12" ry="28" className="fill-none stroke-current" strokeWidth="1" opacity="0.5" />
      <line x1="4" y1="32" x2="60" y2="32" className="stroke-current" strokeWidth="1" opacity="0.5" />
    </svg>
  );
}
function useFetch<T>(path: string): { data: T | null; loading: boolean; error: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    apiClient.get<T>(path).then((d) => { if (active) { setData(d); setError(false); } })
      .catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path]);
  return { data, loading, error };
}
function localTime(unix: number | null): string { if (!unix) return ''; try { return new Date(unix * 1000).toLocaleString(); } catch { return ''; } }
function sideName(s: MatchSide, tbd: string): string { return s.resolved && s.team ? (s.team.name ?? '') : (s.label ?? tbd); }

function BackBar({ onBack, label }: { onBack: () => void; label: string }) {
  const { t } = useTranslation();
  return <button onClick={onBack} className="mb-3 text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.back')} · {label}</button>;
}
function MatchRow({ m, onClick }: { m: MatchBrief; onClick: () => void }) {
  const { t } = useTranslation();
  const tbd = t('fixturesActivity.tbd');
  return (
    <button onClick={onClick} className="flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm hover:border-primary">
      <span className="flex flex-1 items-center gap-2"><Flag team={m.home.team} /> <span className="truncate">{sideName(m.home, tbd)}</span></span>
      <span className="px-2 font-semibold">{m.finished && m.home_score !== null ? `${m.home_score}–${m.away_score}` : (m.kickoff_unix ? localTime(m.kickoff_unix) : t('fixturesActivity.vs'))}</span>
      <span className="flex flex-1 items-center justify-end gap-2"><span className="truncate">{sideName(m.away, tbd)}</span> <Flag team={m.away.team} /></span>
    </button>
  );
}
function Stat({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <div className="rounded-md border border-border bg-card px-3 py-2"><p className="text-xs text-muted-foreground">{label}</p><p className="font-medium text-foreground">{value ?? '—'}</p></div>;
}

// ── World Cup sub-views (public reference data — no session needed) ─────────────
function GroupsHome({ onOpenGroup }: { onOpenGroup: (l: string) => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<{ groups: Group[] }>('/worldcup/groups');
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {data.groups.map((g) => (
        <button key={g.group} onClick={() => onOpenGroup(g.group)} className="rounded-lg border border-border bg-card p-3 text-left hover:border-primary">
          <h2 className="mb-2 font-semibold text-foreground">{t('fixturesActivity.group')} {g.group}</h2>
          <ul className="space-y-1 text-sm">
            {g.standings.map((r) => (
              <li key={r.position} className="flex items-center gap-2"><span className="w-4 text-muted-foreground">{r.position}</span><Flag team={r.team} /> <span className="flex-1 truncate">{r.team?.name ?? '—'}</span><span className="font-semibold">{r.pts}</span></li>
            ))}
          </ul>
        </button>
      ))}
    </div>
  );
}
function GroupView({ letter, onTeam, onMatch, onBack }: { letter: string; onTeam: (id: number) => void; onMatch: (id: number) => void; onBack: () => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<{ standings: StandingRow[]; matches: MatchBrief[] }>(`/worldcup/groups/${letter}`);
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  return (
    <div>
      <BackBar onBack={onBack} label={`${t('fixturesActivity.group')} ${letter}`} />
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-xs text-muted-foreground"><tr><th className="px-2 py-1 text-left">{t('fixturesActivity.colTeam')}</th><th>{t('worldcupData.colPlayed')}</th><th>{t('worldcupData.colGD')}</th><th>{t('worldcupData.colPts')}</th></tr></thead>
          <tbody>
            {data.standings.map((r) => (
              <tr key={r.position} className="cursor-pointer border-t border-border hover:bg-muted" onClick={() => r.team?.id && onTeam(r.team.id)}>
                <td className="px-2 py-1.5"><Flag team={r.team} /> <span className="align-middle">{r.team?.name ?? '—'}</span></td>
                <td className="text-center">{r.mp}</td><td className="text-center">{r.gd > 0 ? `+${r.gd}` : r.gd}</td><td className="text-center font-semibold">{r.pts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="mb-2 mt-4 font-semibold text-foreground">{t('fixturesActivity.matches')}</h3>
      <div className="space-y-2">{data.matches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}</div>
    </div>
  );
}
function TeamView({ id, onMatch, onBack }: { id: number; onMatch: (id: number) => void; onBack: () => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<TeamDetail>(`/worldcup/teams/${id}`);
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  const tm = data.team;
  const byPos = (pos: string) => data.players.filter((p) => (p.position ?? '') === pos);
  return (
    <div>
      <BackBar onBack={onBack} label={tm.name ?? ''} />
      <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4">
        <Flag team={tm} size="h-10 w-16" />
        <div className="flex-1"><h2 className="text-xl font-bold text-foreground">{tm.name}</h2><p className="text-sm text-muted-foreground">{tm.nickname} {tm.confederation ? `· ${tm.confederation}` : ''}</p></div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <Stat label={t('fixturesActivity.coach')} value={tm.coach} />
        <Stat label={t('fixturesActivity.ranking')} value={tm.fifa_ranking ? `#${tm.fifa_ranking}` : null} />
        <Stat label={t('fixturesActivity.appearances')} value={tm.wc_appearances} />
        <Stat label={t('fixturesActivity.firstWc')} value={tm.wc_first_year} />
        <Stat label={t('fixturesActivity.bestResult')} value={tm.wc_best_result} />
      </div>
      <h3 className="mb-2 mt-4 font-semibold text-foreground">{t('fixturesActivity.matches')}</h3>
      <div className="space-y-2">{data.matches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}</div>
      <h3 className="mb-2 mt-4 font-semibold text-foreground">{t('fixturesActivity.squad')}</h3>
      {['Goalkeeper', 'Defender', 'Midfielder', 'Forward'].map((pos) => (
        byPos(pos).length > 0 && (
          <div key={pos} className="mb-2"><p className="text-xs uppercase text-muted-foreground">{t(`fixturesActivity.pos_${pos}` as never) || pos}</p><p className="text-sm text-foreground">{byPos(pos).map((p) => p.name).join(', ')}</p></div>
        )
      ))}
    </div>
  );
}
// AI player's written analysis attached to a match — public, reasoning only (no score).
function MatchAnalysis({ id }: { id: number }) {
  const { t } = useTranslation();
  const { data } = useFetch<{ status: string; analysis?: string }>(`/ai-player/public/analysis/${id}`);
  const [open, setOpen] = useState(false);
  if (!data || data.status !== 'done' || !data.analysis) return null;
  return (
    <div className="mt-4 rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/5 p-4 text-left">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 text-sm font-semibold text-fuchsia-600">
        <span>🤖 {t('aiPlayer.publicTitle')}</span>
        <span className="text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="mt-2">
          <AnalysisMarkdown content={data.analysis} />
        </div>
      )}
    </div>
  );
}

function MatchView({ id, onTeam, onBack }: { id: number; onTeam: (id: number) => void; onBack: () => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<{ match: MatchBrief }>(`/worldcup/matches/${id}`);
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  const m = data.match; const tbd = t('fixturesActivity.tbd');
  return (
    <div>
      <BackBar onBack={onBack} label={t('fixturesActivity.match')} />
      <div className="rounded-lg border border-border bg-card p-5 text-center">
        <div className="flex items-center justify-around">
          <button className="flex flex-col items-center gap-2" onClick={() => m.home.team?.id && onTeam(m.home.team.id)}><Flag team={m.home.team} size="h-12 w-20" /><span className="font-semibold text-foreground">{sideName(m.home, tbd)}</span></button>
          <div className="text-3xl font-bold text-foreground">{m.finished && m.home_score !== null ? `${m.home_score} – ${m.away_score}` : t('fixturesActivity.vs')}{m.home_pens != null && m.away_pens != null && <div className="text-sm text-muted-foreground">{t('fixturesActivity.pens')} {m.home_pens}–{m.away_pens}</div>}</div>
          <button className="flex flex-col items-center gap-2" onClick={() => m.away.team?.id && onTeam(m.away.team.id)}><Flag team={m.away.team} size="h-12 w-20" /><span className="font-semibold text-foreground">{sideName(m.away, tbd)}</span></button>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">{m.kickoff_unix ? localTime(m.kickoff_unix) : ''} {m.stadium?.city ? `· ${m.stadium.city}, ${m.stadium.country}` : ''}</p>
        {m.stadium && <div className="mt-3 flex items-center justify-center gap-2 text-xs text-muted-foreground"><MiniGlobe /><span>{m.stadium.name}</span></div>}
      </div>
      <MatchAnalysis id={id} />
    </div>
  );
}
function VenuesView({ onMatch }: { onMatch: (id: number) => void }) {
  const { t } = useTranslation();
  const { data } = useFetch<{ stadiums: Stadium[] }>('/worldcup/stadiums');
  const { data: today } = useFetch<{ matches: MatchBrief[] }>('/worldcup/today');
  const [city, setCity] = useState<string | null>(null);
  const dots = useMemo(() => (data?.stadiums ?? []).map((s) => ({ s, xy: coordsFor(s.city) })), [data]);
  const selStadium = useMemo(() => (data?.stadiums ?? []).find((s) => s.city === city) ?? null, [data, city]);
  const cityMatches = useMemo(() => (today?.matches ?? []).filter((m) => m.stadium?.city && city && m.stadium.city === city), [today, city]);
  return (
    <div>
      <h2 className="mb-3 flex items-center gap-2 font-semibold text-foreground"><MiniGlobe /> {t('fixturesActivity.venuesTitle')}</h2>
      <div className="relative mb-4 aspect-[1.3/1] w-full max-w-xl overflow-hidden rounded-lg border border-border bg-sky-500/10">
        <NorthAmericaMap />
        {dots.map(({ s, xy }) => xy && (
          <button key={s.id} onClick={() => setCity(s.city)} style={{ left: `${project(xy[0], xy[1])[0]}%`, top: `${project(xy[0], xy[1])[1]}%` }}
            className={`group absolute -translate-x-1/2 -translate-y-full transition ${city === s.city ? 'z-20' : 'z-10 hover:z-20'}`}>
            <svg width="18" height="24" viewBox="0 0 24 32" aria-hidden="true"
              className={`origin-bottom drop-shadow transition group-hover:scale-110 ${city === s.city ? 'scale-110 text-primary' : 'text-rose-600'}`}>
              <path d="M12 0C5.7 0 .6 5.1.6 11.4.6 20 12 32 12 32s11.4-12 11.4-20.6C23.4 5.1 18.3 0 12 0z" fill="currentColor" stroke="#fff" strokeWidth="1.6" />
              <circle cx="12" cy="11.4" r="4.2" fill="#fff" />
            </svg>
            <span className={`absolute left-1/2 top-full mt-0.5 -translate-x-1/2 whitespace-nowrap rounded px-1 text-[9px] font-semibold leading-tight shadow-sm ${city === s.city ? 'bg-primary text-primary-foreground' : 'bg-white/85 text-slate-700 group-hover:bg-white'}`}>{s.city}</span>
          </button>
        ))}
      </div>
      {!city && <p className="text-sm text-muted-foreground">{t('fixturesActivity.pickCity')}</p>}
      {city && (
        <div>
          <div className="mb-2 flex items-baseline justify-between"><h3 className="font-semibold text-foreground">{city}</h3>{selStadium && <span className="text-xs text-muted-foreground">{selStadium.name}{selStadium.capacity ? ` · ${selStadium.capacity.toLocaleString()}` : ''}</span>}</div>
          <div className="space-y-2">{cityMatches.length === 0 && <p className="text-sm text-muted-foreground">{t('fixturesActivity.noCityMatches')}</p>}{cityMatches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}</div>
        </div>
      )}
    </div>
  );
}

function RulesLabel({ rules }: { rules: Rules | null }) {
  const { t } = useTranslation();
  const r = rules ?? { weight_exact: 4, weight_diff: 3, weight_tendency: 2, knockout_multiplier: 2, lock_lead_minutes: 0 };
  const R = ({ label, value }: { label: string; value: string }) => (<div className="flex items-center justify-between border-b border-border py-2 last:border-0"><span className="text-muted-foreground">{label}</span><span className="font-semibold text-foreground">{value}</span></div>);
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold text-foreground">{t('predictions.rulesTitle')}</h2>
      <p className="mb-2 text-xs text-muted-foreground">{t('predictions.rulesIntro')}</p>
      <div className="text-sm"><R label={t('predictions.ruleParticipation')} value="1 pt" /><R label={t('predictions.ruleExact')} value={`+${r.weight_exact}`} /><R label={t('predictions.ruleDiff')} value={`+${r.weight_diff}`} /><R label={t('predictions.ruleTendency')} value={`+${r.weight_tendency}`} /><R label={t('predictions.ruleKnockout')} value={`×${r.knockout_multiplier}`} /></div>
      <p className="mt-2 text-xs text-muted-foreground">{t('predictions.lockNote')}</p>
    </div>
  );
}

// ── Predictions view ───────────────────────────────────────────────────────────
function PredictView({ guildId }: { guildId: string | null }) {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';
  const [matches, setMatches] = useState<MatchBrief[]>([]);
  const [open, setOpen] = useState<OpenResponse | null>(null);
  const [rules, setRules] = useState<Rules | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, { home: string; away: string }>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<'phase' | 'day'>('phase');
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  const loadOpen = () => {
    if (!guildId) return;
    setLoadError(false);
    apiClient.get<OpenResponse>(`/guilds/${guildId}/predictions/open`)
      .then((o) => { setOpen(o); const d: Record<number, { home: string; away: string }> = {}; for (const [mid, p] of Object.entries(o.picks)) d[Number(mid)] = { home: String(p.home), away: String(p.away) }; setDrafts(d); })
      .catch(() => setLoadError(true));
  };
  useEffect(() => {
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today').then((d) => setMatches(d.matches)).catch(() => {});
    if (guildId) { apiClient.get<Rules>(`/guilds/${guildId}/predictions/rules`).then(setRules).catch(() => {}); loadOpen(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guildId]);

  const cdmxDayLabel = (key: string) => {
    const [y, mo, da] = key.split('-').map(Number);
    return new Date(Date.UTC(y, mo - 1, da, 12)).toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
  };

  const { groupSecs, koSecs, daySecs, totalDone, totalTotal } = useMemo(() => {
    const openSet = new Set(open?.open_match_ids ?? []); const picks = open?.picks ?? {};
    const mk = (key: string, title: string, ms: MatchBrief[]): Section => {
      ms = [...ms].sort((a, b) => (a.kickoff_unix ?? 0) - (b.kickoff_unix ?? 0));
      const predictableIds = new Set(ms.filter((m) => openSet.has(m.id)).map((m) => m.id));
      const done = [...predictableIds].filter((id) => picks[id] !== undefined).length;
      return { key, title, matches: ms, predictableIds, total: predictableIds.size, done };
    };
    const groupSecs = GROUP_LETTERS.map((L) => mk(`group:${L}`, `${t('worldcupData.group')} ${L}`, matches.filter((m) => m.round === 'group' && m.group === L)));
    const koSecs = KO_ROUNDS.map((r) => mk(`ko:${r}`, t(`worldcupData.round_${r}`), matches.filter((m) => m.round === r)));
    // Alternate grouping: one section per CDMX calendar day (a "daily competition").
    // The same matches as group/ko, re-bucketed by date — so it is NOT added to the totals.
    const dayMap = new Map<string, MatchBrief[]>();
    for (const m of matches) { if (!m.kickoff_unix) continue; const k = cdmxDayKey(m.kickoff_unix); (dayMap.get(k) ?? (dayMap.set(k, []), dayMap.get(k)!)).push(m); }
    const daySecs = [...dayMap.keys()].sort().map((k) => mk(`day:${k}`, cdmxDayLabel(k), dayMap.get(k)!));
    const all = [...groupSecs, ...koSecs];
    return { groupSecs, koSecs, daySecs, totalDone: all.reduce((s, x) => s + x.done, 0), totalTotal: all.reduce((s, x) => s + x.total, 0) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matches, open, t, locale]);

  const fmtDate = (unix: number | null) => unix ? new Date(unix * 1000).toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' }) : t('worldcupData.tbd');
  const nm = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? t('predictions.vs');

  const saveSection = async (section: Section) => {
    if (!guildId) return;
    const items = section.matches.filter((m) => section.predictableIds.has(m.id)).map((m) => ({ m, d: drafts[m.id] })).filter(({ d }) => d && d.home !== '' && d.away !== '').map(({ m, d }) => ({ match_id: m.id, home: Number(d.home), away: Number(d.away) }));
    if (items.length === 0) { setSelected(null); return; }
    setSaving(true);
    try {
      await apiClient.post<{ saved: number; skipped: number[] }>(`/guilds/${guildId}/predictions/submit-batch`, { items });
      setOpen((prev) => prev ? { ...prev, picks: { ...prev.picks, ...Object.fromEntries(items.map((it) => [it.match_id, { home: it.home, away: it.away, points: 0 }])) } } : prev);
      setSavedFlash(true); setTimeout(() => setSavedFlash(false), 2500); setSelected(null);
    } catch { /* locked */ } finally { setSaving(false); }
  };
  const activeSection = useMemo(() => [...groupSecs, ...koSecs, ...daySecs].find((s) => s.key === selected) || null, [groupSecs, koSecs, daySecs, selected]);

  if (!guildId) return <p className="text-muted-foreground">{t('predictions.openFromDiscord')}</p>;
  if (loadError) return (<div className="space-y-3"><p className="text-muted-foreground">{t('worldcupData.error')}</p><button onClick={loadOpen} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground">{t('predictions.save')}</button></div>);
  if (open && !open.enabled) return <p className="text-muted-foreground">{t('predictions.enabledOff')}</p>;

  const Card = ({ s }: { s: Section }) => {
    const disabled = s.total === 0; const complete = s.total > 0 && s.done >= s.total;
    return (
      <button onClick={() => !disabled && setSelected(s.key)} disabled={disabled} className={`flex flex-col gap-2 rounded-lg border p-3 text-left transition ${disabled ? 'cursor-not-allowed border-border bg-card/50 opacity-60' : 'border-border bg-card hover:border-primary/50'}`}>
        <div className="flex items-center justify-between"><span className="font-medium text-foreground">{s.title}</span><span className={`text-xs ${complete ? 'text-primary' : 'text-muted-foreground'}`}>{disabled ? t('predictions.comingSoon') : `${s.done}/${s.total}`}</span></div>
        {!disabled && <Bar done={s.done} total={s.total} />}
      </button>
    );
  };

  if (activeSection) {
    const s = activeSection;
    const byDate: { date: string; items: MatchBrief[] }[] = [];
    for (const m of s.matches) { const date = fmtDate(m.kickoff_unix); const last = byDate[byDate.length - 1]; if (last && last.date === date) last.items.push(m); else byDate.push({ date, items: [m] }); }
    return (
      <div className="space-y-5 pb-36 md:pb-24">
        <button onClick={() => setSelected(null)} className="text-sm text-muted-foreground hover:text-foreground">← {t('predictions.back')}</button>
        <div><h1 className="text-xl font-bold text-foreground">{s.title}</h1><p className="mt-2 text-sm text-muted-foreground">{t('predictions.progress', { done: String(s.done), total: String(s.total) })}</p><div className="mt-2"><Bar done={s.done} total={s.total} /></div></div>
        {s.total === 0 && <p className="text-muted-foreground">{t('predictions.comingSoon')}</p>}
        {byDate.map(({ date, items }) => (
          <div key={date} className="space-y-2"><h3 className="text-sm font-semibold capitalize text-muted-foreground">{date}</h3>
            {items.map((m) => {
              const predictable = s.predictableIds.has(m.id); const d = drafts[m.id] ?? { home: '', away: '' };
              const ktime = m.kickoff_unix ? new Date(m.kickoff_unix * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }) : '';
              return (
                <div key={m.id} className="rounded-md border border-border bg-card px-3 py-1.5">
                  {ktime && <div className="text-center text-[10px] text-muted-foreground">{ktime}</div>}
                  <div className="flex items-center gap-2">
                    <span className="flex flex-1 items-center justify-end gap-2 text-sm"><span className="truncate">{nm(m.home)}</span><Flag team={m.home.team} /></span>
                    {predictable ? (<>
                      <input type="number" min={0} max={99} inputMode="numeric" value={d.home} onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, home: e.target.value } }))} className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                      <span className="text-muted-foreground">–</span>
                      <input type="number" min={0} max={99} inputMode="numeric" value={d.away} onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, away: e.target.value } }))} className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                    </>) : (<span className="px-2 text-sm font-semibold text-muted-foreground">{m.finished && m.home_score !== null ? `${m.home_score}–${m.away_score}` : t('predictions.locked')}</span>)}
                    <span className="flex flex-1 items-center gap-2 text-sm"><Flag team={m.away.team} /><span className="truncate">{nm(m.away)}</span></span>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        {s.total > 0 && (
          <div className="fixed inset-x-0 bottom-16 z-20 border-t border-border bg-background/95 px-4 py-3 backdrop-blur md:bottom-0"><div className="mx-auto flex max-w-2xl items-center justify-end gap-3"><span className="min-w-0 flex-1 text-[10px] leading-tight text-muted-foreground">{t('fixturesActivity.tosAccept')}</span>{savedFlash && <span className="text-sm text-muted-foreground">{t('predictions.savedAll')}</span>}<button onClick={() => saveSection(s)} disabled={saving} className="shrink-0 rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">{saving ? t('common.loading') : t('predictions.saveAll')}</button></div></div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4"><div className="mb-2 flex items-center justify-between text-sm"><span className="font-medium text-foreground">{t('predictions.overviewTitle')}</span><span className="text-muted-foreground">{t('predictions.progress', { done: String(totalDone), total: String(totalTotal) })}</span></div><Bar done={totalDone} total={totalTotal} /></div>
      <RulesLabel rules={rules} />
      <div className="flex gap-2">
        {(['phase', 'day'] as const).map((k) => (
          <button key={k} onClick={() => setMode(k)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>
            {t(k === 'day' ? 'predictions.byDay' : 'predictions.byPhase')}
          </button>
        ))}
      </div>
      {mode === 'phase' ? (<>
        <div className="space-y-2"><h2 className="font-semibold text-foreground">{t('predictions.groupStage')}</h2><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{groupSecs.map((s) => <Card key={s.key} s={s} />)}</div></div>
        <div className="space-y-2"><h2 className="font-semibold text-foreground">{t('predictions.knockouts')}</h2><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{koSecs.map((s) => <Card key={s.key} s={s} />)}</div></div>
      </>) : (
        <div className="space-y-2"><h2 className="font-semibold text-foreground">{t('predictions.byDay')}</h2>
          {daySecs.length === 0 ? <p className="text-sm text-muted-foreground">{t('predictions.comingSoon')}</p>
            : <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{daySecs.map((s) => <Card key={s.key} s={s} />)}</div>}
        </div>
      )}
    </div>
  );
}

// ── Leaderboard view ────────────────────────────────────────────────────────────
function BoardView({ guildId }: { guildId: string | null }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'global' | 'today' | 'daily'>('global');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [today, setToday] = useState<TodayBoard | null>(null);
  useEffect(() => {
    if (!guildId) { setRows([]); setToday({ date: '', matches: [], players: [] }); return; }
    if (tab === 'today') {
      setToday(null);
      apiClient.get<TodayBoard>(`/guilds/${guildId}/leaderboard/today`)
        .then(setToday)
        .catch(() => setToday({ date: '', matches: [], players: [] }));
      return;
    }
    setRows(null);
    const path = tab === 'daily' ? `/guilds/${guildId}/leaderboard/daily` : `/guilds/${guildId}/leaderboard`;
    apiClient.get<{ standings: Row[] }>(path).then((d) => setRows(d.standings)).catch(() => setRows([]));
  }, [guildId, tab]);
  if (!guildId) return <p className="text-muted-foreground">{t('predictions.openFromDiscord')}</p>;
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
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
            <ol className="space-y-1">{rows.map((r) => (
              <li key={r.user_id} className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm"><span className="flex items-center gap-3"><span className="w-6 text-muted-foreground">{r.position}</span><span className="font-medium">{r.username}</span></span><span className="flex items-center gap-3"><span className="font-semibold">{r.points} pts</span><span className="text-xs text-muted-foreground">{r.exactos} {t('leaderboard.exact')}</span></span></li>
            ))}</ol>
          )}
        </>
      )}
    </div>
  );
}

// A match is "live" from 5 min before kickoff until 3 h after — same window the worker uses.
function inWindow(m: MatchBrief | null): boolean {
  if (!m?.kickoff_unix) return false;
  const now = Math.floor(Date.now() / 1000);
  return m.kickoff_unix - 300 <= now && now <= m.kickoff_unix + 3 * 3600;
}

// ── "Now" / "Inauguración": match of the moment + AI feed (the stream). Before the
// first match kicks off it is framed as the inauguration; once a game is live it shows
// the live score and the live feed takes over. `onLiveChange` lets the hub relabel the tab.
function NowView({ onLiveChange }: { onLiveChange?: (live: boolean) => void }) {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';
  const [match, setMatch] = useState<MatchBrief | null>(null);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [started, setStarted] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    apiClient.get<{ match: MatchBrief | null; events: FeedEvent[]; tournament_started?: boolean }>('/worldcup/now')
      .then((d) => { setMatch(d.match); setEvents(d.events || []); setStarted(!!d.tournament_started); })
      .catch(() => {})
      .finally(() => setLoaded(true));
    const sub = subscribeSSE('/worldcup/live-stream', (ev: FeedEvent) => setEvents((p) => [ev, ...p].slice(0, 50)));
    return () => sub.close();
  }, []);
  const live = inWindow(match) && !match?.finished;
  useEffect(() => { onLiveChange?.(live); }, [live, onLiveChange]);
  const nm = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? t('predictions.vs');
  const when = (u: number | null | undefined) => u ? new Date(u * 1000).toLocaleString(locale, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
  // Inauguration is the PRE-tournament exception: shown only until the first match has
  // been played AND when no game is currently live. Then it's about the live game.
  const showInaug = !live && !started;
  const inaugNews = events.find((e) => e.type === 'news')?.text;

  if (showInaug) {
    // Inauguration only — the whole stream (full news text) lives on this one card.
    // The first match is intentionally NOT shown here.
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-4 text-center">
          <p className="text-lg font-bold text-foreground">🎉 {t('liveTracker.inauguration')} · Mundial 2026</p>
          {match?.kickoff_unix && <p className="mt-1 text-sm capitalize text-muted-foreground">{when(match.kickoff_unix)}</p>}
          {inaugNews
            ? <p className="mt-3 whitespace-pre-wrap text-left text-sm leading-relaxed text-foreground/90">{inaugNews}</p>
            : loaded && <p className="mt-3 text-sm text-muted-foreground">{t('liveTracker.feedEmpty')}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {match && (
        <div className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-around text-center">
            <span className="flex flex-col items-center gap-1"><Flag team={match.home.team} size="h-10 w-16" /><span className="text-sm font-semibold">{nm(match.home)}</span></span>
            <span className="text-2xl font-bold">{match.finished || match.home_score !== null ? `${match.home_score ?? 0} – ${match.away_score ?? 0}` : t('predictions.vs')}</span>
            <span className="flex flex-col items-center gap-1"><Flag team={match.away.team} size="h-10 w-16" /><span className="text-sm font-semibold">{nm(match.away)}</span></span>
          </div>
          <p className="mt-3 text-center text-xs text-muted-foreground">
            {match.finished ? t('liveTracker.final') : (match.time_elapsed || when(match.kickoff_unix))}
            {match.stadium?.city ? ` · ${match.stadium.city}` : ''}
          </p>
        </div>
      )}
      {/* Full event timeline for the match — every significant event accumulates here
          (goal 9', penalty 25', cards, subs…), newest first, each tagged with its minute. */}
      <h2 className="font-semibold text-foreground">{t('liveTracker.feedTitle')}</h2>
      {loaded && events.length === 0 && <p className="text-sm text-muted-foreground">{t('liveTracker.feedEmpty')}</p>}
      <div className="space-y-2">
        {events.map((ev, i) => (
          <div key={`${ev.ts}-${i}`} className="rounded-md border border-border bg-card px-3 py-2 text-sm leading-snug">
            <span className="mr-2" aria-hidden="true">{ev.type === 'news' ? '📰' : ev.type === 'live' ? '⏱' : ''}</span>{ev.text}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Hub (single page, persistent tab bar, handshake once) ──────────────────────
type View =
  | { name: 'now' } | { name: 'predict' } | { name: 'board' }
  | { name: 'groups' } | { name: 'group'; letter: string } | { name: 'team'; id: number } | { name: 'match'; id: number }
  | { name: 'bracket' } | { name: 'venues' };

// Joke Terms of Service ("you may not watch the matches") — pure fun, not legal text.
function JokeTos() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <footer className="mt-10 pb-4 text-center">
      <button onClick={() => setOpen((v) => !v)}
        className="text-xs text-muted-foreground underline-offset-2 hover:underline">
        {t('fixturesActivity.tosLink')}
      </button>
      {open && (
        <div className="mx-auto mt-3 max-w-xl rounded-lg border border-border bg-card p-4 text-left text-sm">
          <h3 className="font-semibold text-foreground">{t('fixturesActivity.tosTitle')}</h3>
          <p className="mt-1 text-muted-foreground">{t('fixturesActivity.tosIntro')}</p>
          <ul className="mt-2 space-y-1.5 text-muted-foreground">
            {[1, 2, 3, 4, 5, 6].map((n) => <li key={n}>{t(`fixturesActivity.tos${n}`)}</li>)}
          </ul>
          <p className="mt-3 text-muted-foreground">{t('fixturesActivity.tosAccept')}</p>
          <p className="mt-3 text-xs italic text-muted-foreground">{t('fixturesActivity.tosDisclaimer')}</p>
        </div>
      )}
    </footer>
  );
}

function Hub() {
  const { t, setLanguage } = useTranslation();
  const [guildId, setGuildId] = useState<string | null>(null);
  const [view, setView] = useState<View>({ name: 'now' });
  const [nowLive, setNowLive] = useState(false);

  // One handshake for the whole activity; the token stays in memory and every
  // tab reuses it. World Cup tabs are public and work even without a session.
  // Also adopt the user's Discord client language (e.g. Spanish).
  useEffect(() => {
    initActivity().then((s) => {
      if (s?.guild_id) setGuildId(String(s.guild_id));
      if (s?.locale) setLanguage(s.locale.toLowerCase().startsWith('es') ? 'es' : 'en');
    }).catch(() => {});
  }, []);

  const groupActive = view.name === 'groups' || view.name === 'group' || view.name === 'team' || view.name === 'match';
  type Tab = { key: string; label: string; title: string; Icon: typeof Home; active: boolean; go: () => void };
  const tabs: Tab[] = [
    { key: 'now', label: nowLive ? t('liveTracker.live') : t('fixturesActivity.navHome'), title: nowLive ? t('liveTracker.live') : t('fixturesActivity.navHome'), Icon: nowLive ? Radio : Home, active: view.name === 'now', go: () => setView({ name: 'now' }) },
    { key: 'predict', label: t('fixturesActivity.navPredict'), title: t('predictions.title'), Icon: Target, active: view.name === 'predict', go: () => setView({ name: 'predict' }) },
    { key: 'board', label: t('fixturesActivity.navBoard'), title: t('leaderboard.title'), Icon: Trophy, active: view.name === 'board', go: () => setView({ name: 'board' }) },
    { key: 'groups', label: t('fixturesActivity.navGroups'), title: t('fixturesActivity.navGroups'), Icon: LayoutGrid, active: groupActive, go: () => setView({ name: 'groups' }) },
    { key: 'bracket', label: t('fixturesActivity.navKnockout'), title: t('fixturesActivity.navBracket'), Icon: Swords, active: view.name === 'bracket', go: () => setView({ name: 'bracket' }) },
    { key: 'venues', label: t('fixturesActivity.navVenues'), title: t('fixturesActivity.navVenues'), Icon: MapPin, active: view.name === 'venues', go: () => setView({ name: 'venues' }) },
  ];

  return (
    <div className="min-h-screen bg-background pb-20 text-foreground md:pb-0">
      {/* Responsive nav: DESKTOP gets a proper top tab bar (with the theme toggle).
          MOBILE has no top bar (it overlapped Discord's exit-activity controls) — its
          navigation + theme toggle live in the bottom bar below. */}
      <header className="sticky top-0 z-20 hidden border-b border-border bg-card/90 backdrop-blur md:block">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2">
          <MiniGlobe />
          <nav className="flex flex-1 items-center gap-1">
            {tabs.map((tb) => (
              <button key={tb.key} onClick={tb.go} aria-current={tb.active ? 'page' : undefined}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition ${tb.active ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                <tb.Icon className="h-4 w-4" aria-hidden="true" />{tb.title}
              </button>
            ))}
          </nav>
          <ThemeTopButton />
        </div>
      </header>
      <main className="mx-auto max-w-5xl p-4">
        {view.name === 'now' && <NowView onLiveChange={setNowLive} />}
        {view.name === 'predict' && <PredictView guildId={guildId} />}
        {view.name === 'board' && <BoardView guildId={guildId} />}
        {view.name === 'groups' && <GroupsHome onOpenGroup={(l) => setView({ name: 'group', letter: l })} />}
        {view.name === 'group' && <GroupView letter={view.letter} onTeam={(id) => setView({ name: 'team', id })} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'groups' })} />}
        {view.name === 'team' && <TeamView id={view.id} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'groups' })} />}
        {view.name === 'match' && <MatchView id={view.id} onTeam={(id) => setView({ name: 'team', id })} onBack={() => setView({ name: 'groups' })} />}
        {view.name === 'bracket' && <BracketBoard onMatch={(id) => setView({ name: 'match', id })} />}
        {view.name === 'venues' && <VenuesView onMatch={(id) => setView({ name: 'match', id })} />}
        <JokeTos />
      </main>
      {/* Bottom bar — MOBILE only: every destination + the theme toggle, thumb-reachable. */}
      <nav className="fixed inset-x-0 bottom-0 z-30 mx-auto flex max-w-5xl border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {tabs.map((tb) => (
          <button key={tb.key} onClick={tb.go} aria-label={tb.label} aria-current={tb.active ? 'page' : undefined}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition ${tb.active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}`}>
            <tb.Icon className="h-5 w-5" strokeWidth={tb.active ? 2.5 : 2} aria-hidden="true" />
            <span className="max-w-full truncate leading-none">{tb.label}</span>
          </button>
        ))}
        <ThemeNavButton />
      </nav>
    </div>
  );
}

export default withActivityPage(Hub);
