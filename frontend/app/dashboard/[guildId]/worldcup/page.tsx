'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';
import { NorthAmericaMap } from '@/lib/na-map';
import { BracketBoard } from '@/lib/bracket';
import { AnalysisMarkdown } from '@/lib/markdown';

// ── Types (mirror worldcup_data API payloads) ───────────────────────────────────
interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; fifa_code: string | null; }
interface StandingRow { position: number; team: TeamBrief | null; mp: number; w: number; d: number; l: number; gf: number; ga: number; gd: number; pts: number; }
interface Stadium { id: number; name: string; city: string | null; country: string | null; capacity: number | null; region?: string; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; round: string; group: string | null; matchday: number | null;
  home: MatchSide; away: MatchSide;
  home_score: number | null; away_score: number | null;
  home_pens: number | null; away_pens: number | null;
  finished: boolean; time_elapsed: string | null;
  kickoff_unix: number | null; stadium: Stadium | null;
}
interface Group { group: string; standings: StandingRow[]; }
interface TeamDetail {
  team: TeamBrief & {
    name_en?: string; coach?: string; nickname?: string; confederation?: string;
    wc_appearances?: number; wc_first_year?: number; wc_best_result?: string;
    fifa_ranking?: number; wikipedia_url?: string;
  };
  standing: StandingRow | null;
  players: { id: number; name: string; position: string | null }[];
  matches: MatchBrief[];
}

type View =
  | { name: 'home' }
  | { name: 'group'; letter: string }
  | { name: 'team'; id: number }
  | { name: 'match'; id: number }
  | { name: 'bracket' }
  | { name: 'venues' };

// Approx coordinates of the host cities for the (very basic) map.
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
    apiClient.get<T>(path)
      .then((d) => { if (active) { setData(d); setError(false); } })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path]);
  return { data, loading, error };
}

function localTime(unix: number | null): string {
  if (!unix) return '';
  try { return new Date(unix * 1000).toLocaleString(); } catch { return ''; }
}
function sideName(s: MatchSide, tbd: string): string {
  return s.resolved && s.team ? (s.team.name ?? '') : (s.label ?? tbd);
}

function NavBtn({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${active ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>
      {label}
    </button>
  );
}

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
      <span className="px-2 font-semibold">
        {m.finished && m.home_score !== null ? `${m.home_score}–${m.away_score}` : (m.kickoff_unix ? localTime(m.kickoff_unix) : t('fixturesActivity.vs'))}
      </span>
      <span className="flex flex-1 items-center justify-end gap-2"><span className="truncate">{sideName(m.away, tbd)}</span> <Flag team={m.away.team} /></span>
    </button>
  );
}

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
              <li key={r.position} className="flex items-center gap-2">
                <span className="w-4 text-muted-foreground">{r.position}</span>
                <Flag team={r.team} /> <span className="flex-1 truncate">{r.team?.name ?? '—'}</span>
                <span className="font-semibold">{r.pts}</span>
              </li>
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
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr><th className="px-2 py-1 text-left">{t('fixturesActivity.colTeam')}</th><th>{t('worldcupData.colPlayed')}</th><th>{t('worldcupData.colGD')}</th><th>{t('worldcupData.colPts')}</th></tr>
          </thead>
          <tbody>
            {data.standings.map((r) => (
              <tr key={r.position} className="cursor-pointer border-t border-border hover:bg-muted" onClick={() => r.team?.id && onTeam(r.team.id)}>
                <td className="px-2 py-1.5"><Flag team={r.team} /> <span className="align-middle">{r.team?.name ?? '—'}</span></td>
                <td className="text-center">{r.mp}</td>
                <td className="text-center">{r.gd > 0 ? `+${r.gd}` : r.gd}</td>
                <td className="text-center font-semibold">{r.pts}</td>
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

function Stat({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium text-foreground">{value ?? '—'}</p>
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
        <div className="flex-1">
          <h2 className="text-xl font-bold text-foreground">{tm.name}</h2>
          <p className="text-sm text-muted-foreground">{tm.nickname} {tm.confederation ? `· ${tm.confederation}` : ''}</p>
        </div>
        {tm.wikipedia_url && (
          <a href={tm.wikipedia_url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">Wikipedia ↗</a>
        )}
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
          <div key={pos} className="mb-2">
            <p className="text-xs uppercase text-muted-foreground">{t(`fixturesActivity.pos_${pos}` as never) || pos}</p>
            <p className="text-sm text-foreground">{byPos(pos).map((p) => p.name).join(', ')}</p>
          </div>
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
  const m = data.match;
  const tbd = t('fixturesActivity.tbd');
  return (
    <div>
      <BackBar onBack={onBack} label={t('fixturesActivity.match')} />
      <div className="rounded-lg border border-border bg-card p-5 text-center">
        <div className="flex items-center justify-around">
          <button className="flex flex-col items-center gap-2" onClick={() => m.home.team?.id && onTeam(m.home.team.id)}>
            <Flag team={m.home.team} size="h-12 w-20" /><span className="font-semibold text-foreground">{sideName(m.home, tbd)}</span>
          </button>
          <div className="text-3xl font-bold text-foreground">
            {m.finished && m.home_score !== null ? `${m.home_score} – ${m.away_score}` : t('fixturesActivity.vs')}
            {m.home_pens !== null && m.away_pens !== null && <div className="text-sm text-muted-foreground">{t('fixturesActivity.pens')} {m.home_pens}–{m.away_pens}</div>}
          </div>
          <button className="flex flex-col items-center gap-2" onClick={() => m.away.team?.id && onTeam(m.away.team.id)}>
            <Flag team={m.away.team} size="h-12 w-20" /><span className="font-semibold text-foreground">{sideName(m.away, tbd)}</span>
          </button>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          {m.kickoff_unix ? localTime(m.kickoff_unix) : ''} {m.stadium?.city ? `· ${m.stadium.city}, ${m.stadium.country}` : ''}
        </p>
        {m.stadium && (
          <div className="mt-3 flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <MiniGlobe /><span>{m.stadium.name}</span>
          </div>
        )}
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
  const cityMatches = useMemo(
    () => (today?.matches ?? []).filter((m) => m.stadium?.city && city && m.stadium.city === city),
    [today, city]
  );
  return (
    <div>
      <h2 className="mb-3 flex items-center gap-2 font-semibold text-foreground"><MiniGlobe /> {t('fixturesActivity.venuesTitle')}</h2>
      <div className="relative mb-4 aspect-[1.3/1] w-full max-w-xl overflow-hidden rounded-lg border border-border bg-sky-500/10">
        <NorthAmericaMap />
        {dots.map(({ s, xy }) => xy && (
          <button
            key={s.id}
            onClick={() => setCity(s.city)}
            style={{ left: `${project(xy[0], xy[1])[0]}%`, top: `${project(xy[0], xy[1])[1]}%` }}
            className={`group absolute -translate-x-1/2 -translate-y-full transition ${city === s.city ? 'z-20' : 'z-10 hover:z-20'}`}
          >
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
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="font-semibold text-foreground">{city}</h3>
            {selStadium && (
              <span className="text-xs text-muted-foreground">
                {selStadium.name}{selStadium.capacity ? ` · ${selStadium.capacity.toLocaleString()}` : ''}
              </span>
            )}
          </div>
          <div className="space-y-2">
            {cityMatches.length === 0 && <p className="text-sm text-muted-foreground">{t('fixturesActivity.noCityMatches')}</p>}
            {cityMatches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}
          </div>
        </div>
      )}
    </div>
  );
}

function WorldcupInner() {
  const { t } = useTranslation();
  useParams(); // ensures the route param is wired
  const search = useSearchParams();
  const [view, setView] = useState<View>(() => {
    const tid = search.get('team');
    return tid ? { name: 'team', id: Number(tid) } : { name: 'home' };
  });

  // Deep-link: another page (predictions, fixtures, match) can link here with
  // ?team=<id> to open the same country stats.
  useEffect(() => {
    const tid = search.get('team');
    if (tid) setView({ name: 'team', id: Number(tid) });
  }, [search]);

  const tab = (v: 'home' | 'bracket' | 'venues') =>
    (view.name === v) || (v === 'home' && (view.name === 'group' || view.name === 'team' || view.name === 'match'));

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('worldcupData.title')}</h1>
        <p className="text-muted-foreground">{t('worldcupData.description')}</p>
      </div>

      <div className="flex gap-2">
        <NavBtn active={tab('home')} onClick={() => setView({ name: 'home' })} label={t('fixturesActivity.navGroups')} />
        <NavBtn active={tab('bracket')} onClick={() => setView({ name: 'bracket' })} label={t('fixturesActivity.navBracket')} />
        <NavBtn active={tab('venues')} onClick={() => setView({ name: 'venues' })} label={t('fixturesActivity.navVenues')} />
      </div>

      {view.name === 'home' && <GroupsHome onOpenGroup={(l) => setView({ name: 'group', letter: l })} />}
      {view.name === 'group' && <GroupView letter={view.letter} onTeam={(id) => setView({ name: 'team', id })} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'home' })} />}
      {view.name === 'team' && <TeamView id={view.id} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'home' })} />}
      {view.name === 'match' && <MatchView id={view.id} onTeam={(id) => setView({ name: 'team', id })} onBack={() => setView({ name: 'home' })} />}
      {view.name === 'bracket' && <BracketBoard onMatch={(id) => setView({ name: 'match', id })} />}
      {view.name === 'venues' && <VenuesView onMatch={(id) => setView({ name: 'match', id })} />}
    </div>
  );
}

function WorldcupPage() {
  return (
    <Suspense fallback={null}>
      <WorldcupInner />
    </Suspense>
  );
}

export default withPermission(WorldcupPage, PermissionLevel.USER);
