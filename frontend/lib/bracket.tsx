'use client';

// Two-sided knockout bracket ("tournament scoreboard"): rounds fan in from both
// edges (R32 → R16 → QF → SF) toward the Final in the centre, with the third-place
// match beneath it. Shared by the Activity and the dashboard World Cup view.
import { useEffect, useState } from 'react';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';

interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; fifa_code?: string | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface KMatch {
  id: number; round: string;
  home: MatchSide; away: MatchSide;
  home_score: number | null; away_score: number | null;
  home_pens?: number | null; away_pens?: number | null;
  finished: boolean;
}
interface Round { round: string; matches: KMatch[]; }

function Flag({ team }: { team: TeamBrief | null }) {
  if (!team?.flag_url) return <span className="inline-block h-3 w-4 rounded-sm bg-muted" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={team.flag_url} alt="" className="inline-block h-3 w-4 rounded-sm object-cover" />;
}

function sideShort(s: MatchSide, tbd: string): string {
  if (s.resolved && s.team) return s.team.fifa_code || s.team.name || tbd;
  return s.label || tbd;  // e.g. "Winner Group A", "Winner Match 89"
}

function MiniMatch({ m, onClick, big = false }: { m: KMatch; onClick: () => void; big?: boolean }) {
  const { t } = useTranslation();
  const tbd = t('fixturesActivity.tbd');
  const row = (s: MatchSide, score: number | null) => (
    <div className="flex items-center justify-between gap-1">
      <span className="flex min-w-0 items-center gap-1"><Flag team={s.team} /><span className="truncate">{sideShort(s, tbd)}</span></span>
      {m.finished && score !== null && <span className="font-semibold tabular-nums">{score}</span>}
    </div>
  );
  return (
    <button onClick={onClick}
      className={`w-full rounded-md border border-border bg-card px-2 py-1.5 text-left ${big ? 'text-sm ring-1 ring-primary/40' : 'text-[11px]'} leading-tight hover:border-primary`}>
      {row(m.home, m.home_score)}
      <div className="my-0.5 border-t border-border/60" />
      {row(m.away, m.away_score)}
    </button>
  );
}

function Column({ label, matches, onMatch }: { label: string; matches: KMatch[]; onMatch: (id: number) => void }) {
  return (
    <div className="flex w-28 shrink-0 flex-col">
      <div className="mb-1 text-center text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="flex flex-1 flex-col justify-around gap-2">
        {matches.map((m) => <MiniMatch key={m.id} m={m} onClick={() => onMatch(m.id)} />)}
      </div>
    </div>
  );
}

export function BracketBoard({ onMatch }: { onMatch: (id: number) => void }) {
  const { t } = useTranslation();
  const [rounds, setRounds] = useState<Round[] | null>(null);
  useEffect(() => {
    apiClient.get<{ rounds: Round[] }>('/worldcup/bracket').then((d) => setRounds(d.rounds)).catch(() => setRounds([]));
  }, []);

  if (!rounds) return <p className="text-muted-foreground">{t('common.loading')}</p>;

  const by: Record<string, KMatch[]> = Object.fromEntries(rounds.map((r) => [r.round, r.matches]));
  const half = (a: KMatch[] = []): [KMatch[], KMatch[]] => { const n = Math.ceil(a.length / 2); return [a.slice(0, n), a.slice(n)]; };
  const [r32L, r32R] = half(by.r32); const [r16L, r16R] = half(by.r16);
  const [qfL, qfR] = half(by.qf); const [sfL, sfR] = half(by.sf);
  const final = (by.final || [])[0]; const third = (by.third || [])[0];
  const lbl = (r: string) => (t(`worldcupData.round_${r}` as never) as string) || r;

  if ((by.r32?.length ?? 0) === 0 && (by.r16?.length ?? 0) === 0 && !final) {
    return <p className="text-muted-foreground">{t('fixturesActivity.error')}</p>;
  }

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex min-h-[28rem] min-w-max items-stretch gap-2">
        {r32L.length > 0 && <Column label={lbl('r32')} matches={r32L} onMatch={onMatch} />}
        {r16L.length > 0 && <Column label={lbl('r16')} matches={r16L} onMatch={onMatch} />}
        {qfL.length > 0 && <Column label={lbl('qf')} matches={qfL} onMatch={onMatch} />}
        {sfL.length > 0 && <Column label={lbl('sf')} matches={sfL} onMatch={onMatch} />}

        {/* Centre: Final + third place */}
        <div className="flex w-32 shrink-0 flex-col justify-center gap-4">
          <div>
            <div className="mb-1 text-center text-[10px] font-semibold uppercase tracking-wide text-primary">🏆 {lbl('final')}</div>
            {final ? <MiniMatch m={final} onClick={() => onMatch(final.id)} big /> : <div className="rounded-md border border-dashed border-border p-3 text-center text-[11px] text-muted-foreground">{t('fixturesActivity.tbd')}</div>}
          </div>
          {third && (
            <div>
              <div className="mb-1 text-center text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{lbl('third')}</div>
              <MiniMatch m={third} onClick={() => onMatch(third.id)} />
            </div>
          )}
        </div>

        {sfR.length > 0 && <Column label={lbl('sf')} matches={sfR} onMatch={onMatch} />}
        {qfR.length > 0 && <Column label={lbl('qf')} matches={qfR} onMatch={onMatch} />}
        {r16R.length > 0 && <Column label={lbl('r16')} matches={r16R} onMatch={onMatch} />}
        {r32R.length > 0 && <Column label={lbl('r32')} matches={r32R} onMatch={onMatch} />}
      </div>
    </div>
  );
}
