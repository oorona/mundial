'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity } from '@/lib/activity';
import { apiClient } from '@/app/api-client';

// ── Types (mirror worldcup_data API payloads) ───────────────────────────────────
interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; fifa_code: string | null; }
interface StandingRow { position: number; team: TeamBrief | null; mp: number; w: number; d: number; l: number; gf: number; ga: number; gd: number; pts: number; }
interface Stadium { id: number; name: string; city: string | null; country: string | null; capacity: number | null; region?: string; match_count?: number; }
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
const LON_MIN = -125, LON_MAX = -69, LAT_MIN = 18, LAT_MAX = 51;

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
    <svg viewBox="0 0 64 64" className="h-12 w-12 text-sky-500" aria-hidden="true">
      <circle cx="32" cy="32" r="28" className="fill-sky-500/10 stroke-current" strokeWidth="2" />
      <ellipse cx="32" cy="32" rx="12" ry="28" className="fill-none stroke-current" strokeWidth="1" opacity="0.5" />
      <line x1="4" y1="32" x2="60" y2="32" className="stroke-current" strokeWidth="1" opacity="0.5" />
    </svg>
  );
}

function MundialActivity() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>({ name: 'home' });
  const [authed, setAuthed] = useState(false);

  // Best-effort Discord Activity handshake (framework helper). Public reads work
  // without it; a session is only needed for guild-scoped predictions/leaderboard.
  // Returns null outside Discord → public read mode. The minted token persists in
  // localStorage so sub-pages (/activity/predicciones, …) reuse it.
  useEffect(() => {
    initActivity().then((s) => setAuthed(!!s)).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-card/80 px-4 py-3 backdrop-blur">
        <MiniGlobe />
        <div className="flex-1">
          <h1 className="text-lg font-bold">{t('fixturesActivity.title')}</h1>
          <p className="text-xs text-muted-foreground">
            {authed ? t('fixturesActivity.connected') : t('fixturesActivity.guest')}
          </p>
        </div>
        <nav className="flex gap-1 text-sm">
          <a href="/activity/inicio" className="rounded-md px-3 py-1.5 font-medium text-muted-foreground hover:text-foreground">{t('fixturesActivity.navHome')}</a>
          <NavBtn active={view.name === 'home'} onClick={() => setView({ name: 'home' })} label={t('fixturesActivity.navGroups')} />
          <NavBtn active={view.name === 'bracket'} onClick={() => setView({ name: 'bracket' })} label={t('fixturesActivity.navBracket')} />
          <NavBtn active={view.name === 'venues'} onClick={() => setView({ name: 'venues' })} label={t('fixturesActivity.navVenues')} />
        </nav>
      </header>

      <main className="mx-auto max-w-4xl p-4">
        {view.name === 'home' && <GroupsHome onOpenGroup={(l) => setView({ name: 'group', letter: l })} />}
        {view.name === 'group' && <GroupView letter={view.letter} onTeam={(id) => setView({ name: 'team', id })} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'home' })} />}
        {view.name === 'team' && <TeamView id={view.id} onMatch={(id) => setView({ name: 'match', id })} onBack={() => setView({ name: 'home' })} />}
        {view.name === 'match' && <MatchView id={view.id} onTeam={(id) => setView({ name: 'team', id })} onBack={() => setView({ name: 'home' })} />}
        {view.name === 'bracket' && <BracketView onMatch={(id) => setView({ name: 'match', id })} />}
        {view.name === 'venues' && <VenuesView onMatch={(id) => setView({ name: 'match', id })} />}
      </main>
    </div>
  );
}

function NavBtn({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} className={`rounded-md px-3 py-1.5 font-medium ${active ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
      {label}
    </button>
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

function GroupsHome({ onOpenGroup }: { onOpenGroup: (l: string) => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<{ groups: Group[] }>('/worldcup/groups');
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {data.groups.map((g) => (
        <button key={g.group} onClick={() => onOpenGroup(g.group)} className="rounded-lg border border-border bg-card p-3 text-left hover:border-primary">
          <h2 className="mb-2 font-semibold">{t('fixturesActivity.group')} {g.group}</h2>
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

function BackBar({ onBack, label }: { onBack: () => void; label: string }) {
  const { t } = useTranslation();
  return <button onClick={onBack} className="mb-3 text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.back')} · {label}</button>;
}

function MatchRow({ m, onClick }: { m: MatchBrief; onClick: () => void }) {
  const { t } = useTranslation();
  const tbd = t('fixturesActivity.tbd');
  return (
    <button onClick={onClick} className="flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm hover:border-primary">
      <span className="flex items-center gap-2"><Flag team={m.home.team} /> {sideName(m.home, tbd)}</span>
      <span className="font-semibold">
        {m.finished && m.home_score !== null ? `${m.home_score}–${m.away_score}` : (m.kickoff_unix ? localTime(m.kickoff_unix) : t('fixturesActivity.vs'))}
      </span>
      <span className="flex items-center gap-2">{sideName(m.away, tbd)} <Flag team={m.away.team} /></span>
    </button>
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
      <h3 className="mb-2 mt-4 font-semibold">{t('fixturesActivity.matches')}</h3>
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
        <div>
          <h2 className="text-xl font-bold">{tm.name}</h2>
          <p className="text-sm text-muted-foreground">{tm.nickname} {tm.confederation ? `· ${tm.confederation}` : ''}</p>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <Stat label={t('fixturesActivity.coach')} value={tm.coach} />
        <Stat label={t('fixturesActivity.ranking')} value={tm.fifa_ranking ? `#${tm.fifa_ranking}` : null} />
        <Stat label={t('fixturesActivity.appearances')} value={tm.wc_appearances} />
        <Stat label={t('fixturesActivity.firstWc')} value={tm.wc_first_year} />
        <Stat label={t('fixturesActivity.bestResult')} value={tm.wc_best_result} />
      </div>
      <h3 className="mb-2 mt-4 font-semibold">{t('fixturesActivity.matches')}</h3>
      <div className="space-y-2">{data.matches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}</div>
      <h3 className="mb-2 mt-4 font-semibold">{t('fixturesActivity.squad')}</h3>
      {['Goalkeeper', 'Defender', 'Midfielder', 'Forward'].map((pos) => (
        byPos(pos).length > 0 && (
          <div key={pos} className="mb-2">
            <p className="text-xs uppercase text-muted-foreground">{t(`fixturesActivity.pos_${pos}` as never) || pos}</p>
            <p className="text-sm">{byPos(pos).map((p) => p.name).join(', ')}</p>
          </div>
        )
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value ?? '—'}</p>
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
            <Flag team={m.home.team} size="h-12 w-20" /><span className="font-semibold">{sideName(m.home, tbd)}</span>
          </button>
          <div className="text-3xl font-bold">
            {m.finished && m.home_score !== null ? `${m.home_score} – ${m.away_score}` : t('fixturesActivity.vs')}
            {m.home_pens !== null && m.away_pens !== null && <div className="text-sm text-muted-foreground">{t('fixturesActivity.pens')} {m.home_pens}–{m.away_pens}</div>}
          </div>
          <button className="flex flex-col items-center gap-2" onClick={() => m.away.team?.id && onTeam(m.away.team.id)}>
            <Flag team={m.away.team} size="h-12 w-20" /><span className="font-semibold">{sideName(m.away, tbd)}</span>
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
    </div>
  );
}

function BracketView({ onMatch }: { onMatch: (id: number) => void }) {
  const { t } = useTranslation();
  const { data, loading, error } = useFetch<{ rounds: { round: string; matches: MatchBrief[] }[] }>('/worldcup/bracket');
  if (loading) return <p className="text-muted-foreground">{t('common.loading')}</p>;
  if (error || !data) return <p className="text-destructive">{t('fixturesActivity.error')}</p>;
  return (
    <div className="space-y-4">
      {data.rounds.map((rnd) => rnd.matches.length > 0 && (
        <div key={rnd.round}>
          <h3 className="mb-2 font-semibold">{t(`fixturesActivity.round_${rnd.round}` as never) || rnd.round}</h3>
          <div className="space-y-2">{rnd.matches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}</div>
        </div>
      ))}
    </div>
  );
}

function VenuesView({ onMatch }: { onMatch: (id: number) => void }) {
  const { t } = useTranslation();
  const { data } = useFetch<{ stadiums: Stadium[] }>('/worldcup/stadiums');
  const { data: today } = useFetch<{ matches: MatchBrief[] }>('/worldcup/today');
  const [city, setCity] = useState<string | null>(null);
  const dots = useMemo(() => (data?.stadiums ?? []).map((s) => ({ s, xy: coordsFor(s.city) })), [data]);
  const cityMatches = useMemo(
    () => (today?.matches ?? []).filter((m) => m.stadium?.city && city && m.stadium.city === city),
    [today, city]
  );
  return (
    <div>
      <h2 className="mb-3 flex items-center gap-2 font-semibold"><MiniGlobe /> {t('fixturesActivity.venuesTitle')}</h2>
      <div className="relative mb-4 h-64 w-full overflow-hidden rounded-lg border border-border bg-sky-500/5">
        {dots.map(({ s, xy }) => xy && (
          <button
            key={s.id}
            onClick={() => setCity(s.city)}
            style={{ left: `${project(xy[0], xy[1])[0]}%`, top: `${project(xy[0], xy[1])[1]}%` }}
            className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full px-2 py-0.5 text-[10px] font-medium ${city === s.city ? 'bg-primary text-primary-foreground' : 'bg-sky-500/30 text-foreground hover:bg-sky-500/50'}`}
          >
            {s.city}
          </button>
        ))}
      </div>
      {!city && <p className="text-sm text-muted-foreground">{t('fixturesActivity.pickCity')}</p>}
      {city && (
        <div>
          <h3 className="mb-2 font-semibold">{city}</h3>
          <div className="space-y-2">
            {cityMatches.length === 0 && <p className="text-sm text-muted-foreground">{t('fixturesActivity.noCityMatches')}</p>}
            {cityMatches.map((m) => <MatchRow key={m.id} m={m} onClick={() => onMatch(m.id)} />)}
          </div>
        </div>
      )}
    </div>
  );
}

export default withActivityPage(MundialActivity);
