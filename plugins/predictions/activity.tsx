'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';
import { initActivity, getActivityGuildId } from '@/lib/activity';
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
interface Section {
  key: string; title: string; matches: MatchBrief[];
  predictableIds: Set<number>; total: number; done: number;
}

const GROUP_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
const KO_ROUNDS = ['r32', 'r16', 'qf', 'sf', 'third', 'final'];

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

function PredictActivity() {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';

  const [guildId, setGuildId] = useState<string | null>(null);
  const [noSession, setNoSession] = useState(false);
  const [matches, setMatches] = useState<MatchBrief[]>([]);
  const [open, setOpen] = useState<OpenResponse | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, { home: string; away: string }>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  // Fresh handshake each load mints a valid activity token (stored for apiClient);
  // fall back to the guild the hub captured if the handshake returns null.
  useEffect(() => {
    initActivity()
      .then((s) => {
        const gid = s?.guild_id || getActivityGuildId();
        if (gid) setGuildId(String(gid)); else setNoSession(true);
      })
      .catch(() => {
        const gid = getActivityGuildId();
        if (gid) setGuildId(gid); else setNoSession(true);
      });
  }, []);

  const loadOpen = (gid: string) => {
    setLoadError(false);
    apiClient.get<OpenResponse>(`/guilds/${gid}/predictions/open`)
      .then((o) => {
        setOpen(o);
        const d: Record<number, { home: string; away: string }> = {};
        for (const [mid, p] of Object.entries(o.picks)) d[Number(mid)] = { home: String(p.home), away: String(p.away) };
        setDrafts(d);
      })
      .catch(() => setLoadError(true));
  };

  useEffect(() => {
    if (!guildId) return;
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today').then((d) => setMatches(d.matches)).catch(() => {});
    loadOpen(guildId);
  }, [guildId]);

  const { groupSecs, koSecs, totalDone, totalTotal } = useMemo(() => {
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
    const all = [...groupSecs, ...koSecs];
    return {
      groupSecs, koSecs,
      totalDone: all.reduce((s, x) => s + x.done, 0),
      totalTotal: all.reduce((s, x) => s + x.total, 0),
    };
  }, [matches, open, t]);

  const fmtDate = (unix: number | null) =>
    unix ? new Date(unix * 1000).toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' }) : t('worldcupData.tbd');
  const sideName = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? t('predictions.vs');

  const saveSection = async (section: Section) => {
    const items = section.matches
      .filter((m) => section.predictableIds.has(m.id))
      .map((m) => ({ m, d: drafts[m.id] }))
      .filter(({ d }) => d && d.home !== '' && d.away !== '')
      .map(({ m, d }) => ({ match_id: m.id, home: Number(d.home), away: Number(d.away) }));
    if (items.length === 0) { setSelected(null); return; }
    setSaving(true);
    try {
      await apiClient.post<{ saved: number; skipped: number[] }>(`/guilds/${guildId}/predictions/submit-batch`, { items });
      setOpen((prev) => prev ? {
        ...prev,
        picks: { ...prev.picks, ...Object.fromEntries(items.map((it) => [it.match_id, { home: it.home, away: it.away, points: 0 }])) },
      } : prev);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2500);
      setSelected(null);
    } catch {
      /* locked or no access */
    } finally {
      setSaving(false);
    }
  };

  const activeSection = useMemo(
    () => [...groupSecs, ...koSecs].find((s) => s.key === selected) || null,
    [groupSecs, koSecs, selected],
  );

  const homeLink = (
    <a href="/activity/inicio" className="mb-3 inline-block text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.navHome')}</a>
  );

  if (noSession) {
    return <div className="min-h-screen bg-background p-4 text-foreground">{homeLink}<p className="text-muted-foreground">{t('predictions.openFromDiscord')}</p></div>;
  }
  if (!guildId || (!open && !loadError)) {
    return <div className="min-h-screen bg-background p-4 text-foreground">{homeLink}<p className="text-muted-foreground">{t('common.loading')}</p></div>;
  }
  if (loadError) {
    return (
      <div className="min-h-screen bg-background p-4 text-foreground">
        {homeLink}
        <p className="mb-3 text-muted-foreground">{t('worldcupData.error')}</p>
        <button onClick={() => guildId && loadOpen(guildId)} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground">
          {t('predictions.save')}
        </button>
      </div>
    );
  }
  if (open && !open.enabled) {
    return <div className="min-h-screen bg-background p-4 text-foreground">{homeLink}<p className="text-muted-foreground">{t('predictions.enabledOff')}</p></div>;
  }

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

  // ── Section detail ───────────────────────────────────────────────────────────
  if (activeSection) {
    const s = activeSection;
    const byDate: { date: string; items: MatchBrief[] }[] = [];
    for (const m of s.matches) {
      const date = fmtDate(m.kickoff_unix);
      const last = byDate[byDate.length - 1];
      if (last && last.date === date) last.items.push(m);
      else byDate.push({ date, items: [m] });
    }
    return (
      <div className="min-h-screen bg-background p-4 text-foreground space-y-5 pb-24">
        <button onClick={() => setSelected(null)} className="text-sm text-muted-foreground hover:text-foreground">← {t('predictions.back')}</button>
        <div>
          <h1 className="text-xl font-bold">{s.title}</h1>
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
              return (
                <div key={m.id} className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2">
                  <span className="flex flex-1 items-center justify-end gap-2 text-sm"><span className="truncate">{sideName(m.home)}</span><Flag team={m.home.team} /></span>
                  {predictable ? (
                    <>
                      <input type="number" min={0} max={99} value={d.home} inputMode="numeric"
                        onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, home: e.target.value } }))}
                        className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                      <span className="text-muted-foreground">–</span>
                      <input type="number" min={0} max={99} value={d.away} inputMode="numeric"
                        onChange={(e) => setDrafts((p) => ({ ...p, [m.id]: { ...d, away: e.target.value } }))}
                        className="w-12 rounded-md border border-border bg-background px-2 py-1 text-center" />
                    </>
                  ) : (
                    <span className="px-2 text-sm font-semibold text-muted-foreground">
                      {m.finished && m.home_score !== null ? `${m.home_score}–${m.away_score}` : t('predictions.locked')}
                    </span>
                  )}
                  <span className="flex flex-1 items-center gap-2 text-sm"><Flag team={m.away.team} /><span className="truncate">{sideName(m.away)}</span></span>
                </div>
              );
            })}
          </div>
        ))}

        {s.total > 0 && (
          <div className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 px-4 py-3 backdrop-blur">
            <div className="mx-auto flex max-w-2xl items-center justify-end gap-3">
              {savedFlash && <span className="text-sm text-muted-foreground">{t('predictions.savedAll')}</span>}
              <button onClick={() => saveSection(s)} disabled={saving}
                className="rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
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
    <div className="min-h-screen bg-background p-4 text-foreground space-y-6">
      {homeLink}
      <div>
        <h1 className="text-xl font-bold">{t('predictions.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('predictions.description')}</p>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-foreground">{t('predictions.overviewTitle')}</span>
          <span className="text-muted-foreground">{t('predictions.progress', { done: String(totalDone), total: String(totalTotal) })}</span>
        </div>
        <Bar done={totalDone} total={totalTotal} />
      </div>

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
    </div>
  );
}

export default withActivityPage(PredictActivity);
