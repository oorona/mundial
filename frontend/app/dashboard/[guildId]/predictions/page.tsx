'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ChevronLeft } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { usePermissions } from '@/lib/hooks/use-permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';

interface TeamBrief { id: number | null; name: string | null; flag_url: string | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; round: string; group: string | null;
  home: MatchSide; away: MatchSide;
  finished: boolean; home_score: number | null; away_score: number | null;
  kickoff_unix: number | null;
}
interface OpenResponse {
  enabled: boolean;
  open_match_ids: number[];
  picks: Record<string, { home: number; away: number; points: number }>;
}
interface Rules {
  weight_exact: number; weight_diff: number; weight_tendency: number;
  knockout_multiplier: number; lock_lead_minutes: number;
}
interface Pool {
  name: string; weight_exact: number; weight_diff: number; weight_tendency: number;
  knockout_multiplier: number; lock_lead_minutes: number; enabled: boolean;
}
interface Section {
  key: string; title: string; matches: MatchBrief[];
  predictableIds: Set<number>; total: number; done: number;
}

const GROUP_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
const KO_ROUNDS = ['r32', 'r16', 'qf', 'sf', 'third', 'final'];

// Calendar-day key (YYYY-MM-DD) in Mexico City time (fixed UTC-6), so the by-day
// prediction grouping matches the CDMX daily-leaderboard window exactly.
const cdmxDayKey = (unix: number | null | undefined): string => {
  const d = new Date(((unix ?? 0) - 6 * 3600) * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
};

function Flag({ team }: { team: TeamBrief | null }) {
  if (!team?.flag_url) return <span className="text-muted-foreground">—</span>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={team.flag_url} alt={team.name ?? ''} className="inline-block h-4 w-6 rounded-sm object-cover align-middle" />;
}

function Bar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

// Read-only "how points work" label — NOT an editable form.
function RulesLabel({ rules }: { rules: Rules | null }) {
  const { t } = useTranslation();
  const r = rules ?? { weight_exact: 4, weight_diff: 3, weight_tendency: 2, knockout_multiplier: 2, lock_lead_minutes: 0 };
  const Row = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-center justify-between border-b border-border py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span><span className="font-semibold text-foreground">{value}</span>
    </div>
  );
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold text-foreground">{t('predictions.rulesTitle')}</h2>
      <p className="mb-2 text-xs text-muted-foreground">{t('predictions.rulesIntro')}</p>
      <div className="text-sm">
        <Row label={t('predictions.ruleParticipation')} value="1 pt" />
        <Row label={t('predictions.ruleExact')} value={`+${r.weight_exact}`} />
        <Row label={t('predictions.ruleDiff')} value={`+${r.weight_diff}`} />
        <Row label={t('predictions.ruleTendency')} value={`+${r.weight_tendency}`} />
        <Row label={t('predictions.ruleKnockout')} value={`×${r.knockout_multiplier}`} />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{t('predictions.lockNote')}</p>
    </div>
  );
}

// Developer-only pool configuration form (weights / lock / enabled).
function PoolConfig({ guildId }: { guildId: string }) {
  const { t } = useTranslation();
  const [pool, setPool] = useState<Pool | null>(null);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    apiClient.get<Pool>(`/guilds/${guildId}/predictions/pool`).then(setPool).catch(() => setStatus('error'));
  }, [guildId]);

  const num = (k: keyof Pool) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setPool((p) => (p ? { ...p, [k]: Number(e.target.value) } : p));

  const save = async () => {
    if (!pool) return;
    setStatus('saving');
    try {
      const saved = await apiClient.put<Pool>(`/guilds/${guildId}/predictions/pool`, pool);
      setPool(saved);
      setStatus('saved');
    } catch {
      setStatus('error');
    }
  };

  if (!pool) return null;

  const Field = ({ label, k, min = 0 }: { label: string; k: keyof Pool; min?: number }) => (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input type="number" min={min} value={pool[k] as number} onChange={num(k)}
        className="rounded-md border border-border bg-background px-2 py-1" />
    </label>
  );

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <h2 className="font-semibold text-foreground">{t('predictions.poolConfig')}</h2>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input type="checkbox" checked={pool.enabled} onChange={(e) => setPool({ ...pool, enabled: e.target.checked })} />
        {t('predictions.enabled')}
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">{t('predictions.fieldName')}</span>
        <input value={pool.name} onChange={(e) => setPool({ ...pool, name: e.target.value })}
          className="rounded-md border border-border bg-background px-2 py-1" />
      </label>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field label={t('predictions.weightExact')} k="weight_exact" />
        <Field label={t('predictions.weightDiff')} k="weight_diff" />
        <Field label={t('predictions.weightTendency')} k="weight_tendency" />
        <Field label={t('predictions.knockoutMultiplier')} k="knockout_multiplier" min={1} />
        <Field label={t('predictions.lockLead')} k="lock_lead_minutes" />
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={status === 'saving'}
          className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
          {status === 'saving' ? t('common.loading') : t('predictions.save')}
        </button>
        {status === 'saved' && <span className="text-sm text-muted-foreground">{t('predictions.saved')}</span>}
        {status === 'error' && <span className="text-sm text-destructive">{t('predictions.saveError')}</span>}
      </div>
      <p className="text-xs text-muted-foreground">{t('predictions.adminOnly')}</p>
    </div>
  );
}

function PredictionsPage() {
  const { t, language } = useTranslation();
  const guildId = useParams().guildId as string;
  const { permissionLevel } = usePermissions(guildId);
  const isDeveloper = permissionLevel >= PermissionLevel.DEVELOPER;
  const locale = language === 'es' ? 'es-ES' : 'en-US';

  const [matches, setMatches] = useState<MatchBrief[]>([]);
  const [open, setOpen] = useState<OpenResponse | null>(null);
  const [rules, setRules] = useState<Rules | null>(null);
  const [drafts, setDrafts] = useState<Record<number, { home: string; away: string }>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<'phase' | 'day'>('phase');
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today').then((d) => setMatches(d.matches)).catch(() => {});
    apiClient.get<Rules>(`/guilds/${guildId}/predictions/rules`).then(setRules).catch(() => {});
    apiClient.get<OpenResponse>(`/guilds/${guildId}/predictions/web-open`)
      .then((o) => {
        setOpen(o);
        const d: Record<number, { home: string; away: string }> = {};
        for (const [mid, p] of Object.entries(o.picks)) d[Number(mid)] = { home: String(p.home), away: String(p.away) };
        setDrafts(d);
      })
      .catch(() => setOpen({ enabled: false, open_match_ids: [], picks: {} }));
  }, [guildId]);

  const cdmxDayLabel = (key: string) => {
    const [y, mo, da] = key.split('-').map(Number);
    return new Date(Date.UTC(y, mo - 1, da, 12)).toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
  };

  const { groupSecs, koSecs, daySecs, totalDone, totalTotal } = useMemo(() => {
    const openSet = new Set(open?.open_match_ids ?? []);
    const picks = open?.picks ?? {};
    const mk = (key: string, title: string, ms: MatchBrief[]): Section => {
      ms = [...ms].sort((a, b) => (a.kickoff_unix ?? 0) - (b.kickoff_unix ?? 0));
      const predictableIds = new Set(ms.filter((m) => openSet.has(m.id)).map((m) => m.id));
      const done = [...predictableIds].filter((id) => picks[id] !== undefined).length;
      return { key, title, matches: ms, predictableIds, total: predictableIds.size, done };
    };
    const groupSecs = GROUP_LETTERS.map((L) =>
      mk(`group:${L}`, `${t('worldcupData.group')} ${L}`, matches.filter((m) => m.round === 'group' && m.group === L)));
    const koSecs = KO_ROUNDS.map((r) =>
      mk(`ko:${r}`, t(`worldcupData.round_${r}`), matches.filter((m) => m.round === r)));
    // Alternate grouping: one section per CDMX calendar day (a "daily competition").
    // Same matches as group/ko, re-bucketed by date — so it is NOT added to the totals.
    const dayMap = new Map<string, MatchBrief[]>();
    for (const m of matches) { if (!m.kickoff_unix) continue; const k = cdmxDayKey(m.kickoff_unix); (dayMap.get(k) ?? (dayMap.set(k, []), dayMap.get(k)!)).push(m); }
    const daySecs = [...dayMap.keys()].sort().map((k) => mk(`day:${k}`, cdmxDayLabel(k), dayMap.get(k)!));
    const all = [...groupSecs, ...koSecs];
    return {
      groupSecs, koSecs, daySecs,
      totalDone: all.reduce((s, x) => s + x.done, 0),
      totalTotal: all.reduce((s, x) => s + x.total, 0),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matches, open, t, locale]);

  const fmtDate = (unix: number | null) =>
    unix ? new Date(unix * 1000).toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' }) : t('worldcupData.tbd');

  const sideName = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? t('predictions.vs');
  // Country name links to its full stats on the World Cup page (same view everywhere).
  const TeamLink = ({ side }: { side: MatchSide }) =>
    side.team?.id
      ? <Link href={`/dashboard/${guildId}/worldcup?team=${side.team.id}`} className="truncate hover:underline">{sideName(side)}</Link>
      : <span className="truncate">{sideName(side)}</span>;

  const saveSection = async (section: Section) => {
    const items = section.matches
      .filter((m) => section.predictableIds.has(m.id))
      .map((m) => ({ m, d: drafts[m.id] }))
      .filter(({ d }) => d && d.home !== '' && d.away !== '')
      .map(({ m, d }) => ({ match_id: m.id, home: Number(d.home), away: Number(d.away) }));
    if (items.length === 0) { setSelected(null); return; }
    setSaving(true);
    try {
      await apiClient.post<{ saved: number; skipped: number[] }>(`/guilds/${guildId}/predictions/web-submit-batch`, { items });
      setOpen((prev) => prev ? {
        ...prev,
        picks: { ...prev.picks, ...Object.fromEntries(items.map((it) => [it.match_id, { home: it.home, away: it.away, points: 0 }])) },
      } : prev);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2500);
      setSelected(null);
    } catch {
      /* disabled or no access */
    } finally {
      setSaving(false);
    }
  };

  const activeSection = useMemo(
    () => [...groupSecs, ...koSecs, ...daySecs].find((s) => s.key === selected) || null,
    [groupSecs, koSecs, daySecs, selected],
  );

  // ── Section card (overview) ──────────────────────────────────────────────────
  const Card = ({ s }: { s: Section }) => {
    const disabled = s.total === 0;
    const complete = s.total > 0 && s.done >= s.total;
    return (
      <button
        onClick={() => !disabled && setSelected(s.key)}
        disabled={disabled}
        className={`flex flex-col gap-2 rounded-lg border p-3 text-left transition ${disabled
          ? 'cursor-not-allowed border-border bg-card/50 opacity-60'
          : 'border-border bg-card hover:border-primary/50'}`}
      >
        <div className="flex items-center justify-between">
          <span className="font-medium text-foreground">{s.title}</span>
          <span className={`text-xs ${complete ? 'text-primary' : 'text-muted-foreground'}`}>
            {disabled ? t('predictions.comingSoon') : `${s.done}/${s.total}`}
          </span>
        </div>
        {!disabled && <Bar done={s.done} total={s.total} />}
      </button>
    );
  };

  // ── Section detail view ──────────────────────────────────────────────────────
  if (activeSection) {
    const s = activeSection;
    // group its matches by date
    const byDate: { date: string; items: MatchBrief[] }[] = [];
    for (const m of s.matches) {
      const date = fmtDate(m.kickoff_unix);
      const last = byDate[byDate.length - 1];
      if (last && last.date === date) last.items.push(m);
      else byDate.push({ date, items: [m] });
    }
    return (
      <div className="max-w-2xl mx-auto space-y-5 pb-24">
        <button onClick={() => setSelected(null)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-4 w-4" />{t('predictions.back')}
        </button>
        <div>
          <h1 className="text-2xl font-bold text-foreground">{s.title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t('predictions.progress', { done: String(s.done), total: String(s.total) })}</p>
          <div className="mt-2"><Bar done={s.done} total={s.total} /></div>
        </div>

        {s.total === 0 && <p className="text-muted-foreground">{t('predictions.comingSoon')}</p>}

        {byDate.map(({ date, items }) => (
          <div key={date} className="space-y-2">
            <h3 className="text-sm font-semibold capitalize text-muted-foreground">{date}</h3>
            {items.map((m) => {
              const predictable = s.predictableIds.has(m.id);
              const d = drafts[m.id] ?? { home: '', away: '' };
              const ktime = m.kickoff_unix ? new Date(m.kickoff_unix * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }) : '';
              return (
                <div key={m.id} className="rounded-md border border-border bg-card px-3 py-1.5">
                  {ktime && <div className="text-center text-[10px] text-muted-foreground">{ktime}</div>}
                  <div className="flex items-center gap-2">
                    <span className="flex flex-1 items-center justify-end gap-2 text-sm"><TeamLink side={m.home} /><Flag team={m.home.team} /></span>
                    {predictable ? (
                      <>
                        <input type="number" min={0} max={99} value={d.home}
                          onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, home: e.target.value } }))}
                          className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                        <span className="text-muted-foreground">–</span>
                        <input type="number" min={0} max={99} value={d.away}
                          onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, away: e.target.value } }))}
                          className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                      </>
                    ) : (
                      <span className="px-2 text-sm font-semibold text-muted-foreground">
                        {m.finished && m.home_score !== null
                          ? `${m.home_score}–${m.away_score}`
                          : t('predictions.locked')}
                      </span>
                    )}
                    <span className="flex flex-1 items-center gap-2 text-sm"><Flag team={m.away.team} /><TeamLink side={m.away} /></span>
                  </div>
                </div>
              );
            })}
          </div>
        ))}

        {s.total > 0 && (
          <div className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 px-4 py-3 backdrop-blur">
            <div className="mx-auto flex max-w-2xl items-center justify-end gap-3">
              <span className="min-w-0 flex-1 text-[10px] leading-tight text-muted-foreground">{t('fixturesActivity.tosAccept')}</span>
              {savedFlash && <span className="text-sm text-muted-foreground">{t('predictions.savedAll')}</span>}
              <button onClick={() => saveSection(s)} disabled={saving}
                className="shrink-0 rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {saving ? t('common.loading') : t('predictions.saveAll')}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Overview ─────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('predictions.title')}</h1>
        <p className="text-muted-foreground">{t('predictions.description')}</p>
      </div>

      {open && !open.enabled && <p className="text-muted-foreground">{t('predictions.enabledOff')}</p>}

      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-foreground">{t('predictions.overviewTitle')}</span>
          <span className="text-muted-foreground">{t('predictions.progress', { done: String(totalDone), total: String(totalTotal) })}</span>
        </div>
        <Bar done={totalDone} total={totalTotal} />
      </div>

      <RulesLabel rules={rules} />

      <div className="flex gap-2">
        {(['phase', 'day'] as const).map((k) => (
          <button key={k} onClick={() => setMode(k)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>
            {t(k === 'day' ? 'predictions.byDay' : 'predictions.byPhase')}
          </button>
        ))}
      </div>

      {mode === 'phase' ? (
        <>
          <div className="space-y-2">
            <h2 className="font-semibold text-foreground">{t('predictions.groupStage')}</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {groupSecs.map((s) => <Card key={s.key} s={s} />)}
            </div>
          </div>

          <div className="space-y-2">
            <h2 className="font-semibold text-foreground">{t('predictions.knockouts')}</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {koSecs.map((s) => <Card key={s.key} s={s} />)}
            </div>
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <h2 className="font-semibold text-foreground">{t('predictions.byDay')}</h2>
          {daySecs.length === 0
            ? <p className="text-sm text-muted-foreground">{t('predictions.comingSoon')}</p>
            : <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{daySecs.map((s) => <Card key={s.key} s={s} />)}</div>}
        </div>
      )}

      {isDeveloper && <PoolConfig guildId={guildId} />}
    </div>
  );
}

export default withPermission(PredictionsPage, PermissionLevel.USER);
