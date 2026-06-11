'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { apiClient } from '@/app/api-client';
import { subscribeSSE } from '@/lib/streaming';

interface TeamBrief { name: string | null; }
interface MatchSide { resolved: boolean; label: string | null; team: TeamBrief | null; }
interface MatchBrief {
  id: number; round: string; home: MatchSide; away: MatchSide;
  home_score: number | null; away_score: number | null;
  finished: boolean; time_elapsed: string | null; kickoff_unix: number | null;
}

function LiveTrackerPage() {
  const { t } = useTranslation();
  const guildId = useParams().guildId as string;
  const [matches, setMatches] = useState<MatchBrief[]>([]);
  const [form, setForm] = useState({ match_id: '', home_score: '', away_score: '', home_pens: '', away_pens: '', finished: true });
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  // Global (platform-wide) result auto-commit config — Developer only.
  const [commit, setCommit] = useState<{ auto_commit: boolean; confidence: number }>({ auto_commit: true, confidence: 0.8 });
  const [commitStatus, setCommitStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const load = useCallback(() => {
    apiClient.get<{ matches: MatchBrief[] }>('/worldcup/today').then((d) => setMatches(d.matches)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    apiClient.get<{ auto_commit: boolean; confidence: number }>('/guilds/live-tracker/commit-config').then(setCommit).catch(() => {});
    const sub = subscribeSSE(`/guilds/${guildId}/live-tracker/stream`, () => load());
    return () => sub.close();
  }, [guildId, load]);

  const saveCommit = async () => {
    setCommitStatus('saving');
    try {
      const r = await apiClient.post<{ auto_commit: boolean; confidence: number }>('/guilds/live-tracker/commit-config', commit);
      setCommit(r);
      setCommitStatus('saved');
    } catch {
      setCommitStatus('error');
    }
  };

  const submit = async () => {
    if (!form.match_id) return;
    setStatus('saving');
    try {
      await apiClient.post<{ ok: boolean }>(`/guilds/${guildId}/live-tracker/override/${Number(form.match_id)}`, {
        home_score: Number(form.home_score || 0),
        away_score: Number(form.away_score || 0),
        finished: form.finished,
        home_pens: form.home_pens === '' ? null : Number(form.home_pens),
        away_pens: form.away_pens === '' ? null : Number(form.away_pens),
      });
      setStatus('saved');
      load();
    } catch {
      setStatus('error');
    }
  };

  const now = Math.floor(Date.now() / 1000);
  const live = matches.filter((m) => m.kickoff_unix && m.kickoff_unix - 300 <= now && now <= m.kickoff_unix + 3 * 3600);
  const sideName = (s: MatchSide) => (s.resolved && s.team ? s.team.name : s.label) ?? '';

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('liveTracker.title')}</h1>
        <p className="text-muted-foreground">{t('liveTracker.description')}</p>
      </div>

      <div>
        <h2 className="mb-2 font-semibold text-foreground">{t('liveTracker.live')}</h2>
        {live.length === 0 && <p className="text-muted-foreground">{t('liveTracker.noLive')}</p>}
        <div className="space-y-2">
          {live.map((m) => (
            <div key={m.id} className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground">
              <span>#{m.id} · {sideName(m.home)} <b>{m.home_score ?? 0}–{m.away_score ?? 0}</b> {sideName(m.away)}</span>
              <span className="text-xs text-muted-foreground">{m.finished ? t('liveTracker.final') : (m.time_elapsed || t('liveTracker.live'))}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="font-semibold text-foreground">{t('liveTracker.override')}</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Num label={t('liveTracker.matchId')} v={form.match_id} on={(x) => setForm({ ...form, match_id: x })} />
          <Num label={t('liveTracker.homeScore')} v={form.home_score} on={(x) => setForm({ ...form, home_score: x })} />
          <Num label={t('liveTracker.awayScore')} v={form.away_score} on={(x) => setForm({ ...form, away_score: x })} />
          <Num label={t('liveTracker.homePens')} v={form.home_pens} on={(x) => setForm({ ...form, home_pens: x })} />
          <Num label={t('liveTracker.awayPens')} v={form.away_pens} on={(x) => setForm({ ...form, away_pens: x })} />
        </div>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={form.finished} onChange={(e) => setForm({ ...form, finished: e.target.checked })} />
          {t('liveTracker.finished')}
        </label>
        <div className="flex items-center gap-3">
          <button onClick={submit} disabled={status === 'saving'} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {t('liveTracker.submit')}
          </button>
          {status === 'saved' && <span className="text-sm text-muted-foreground">{t('liveTracker.saved')}</span>}
          {status === 'error' && <span className="text-sm text-destructive">{t('liveTracker.error')}</span>}
        </div>
        <p className="text-xs text-muted-foreground">{t('liveTracker.adminOnly')}</p>
      </div>

      {/* Global result auto-commit — Developer only (writes the shared matches table). */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="font-semibold text-foreground">{t('liveTracker.commitTitle')}</h2>
        <p className="text-xs text-muted-foreground">{t('liveTracker.commitDesc')}</p>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={commit.auto_commit} onChange={(e) => setCommit({ ...commit, auto_commit: e.target.checked })} />
          {t('liveTracker.commitAuto')}
        </label>
        <label className="flex max-w-[12rem] flex-col gap-1 text-sm">
          <span className="text-muted-foreground">{t('liveTracker.commitConfidence')}</span>
          <input type="number" min={0} max={1} step={0.05} value={commit.confidence}
            onChange={(e) => setCommit({ ...commit, confidence: Number(e.target.value) })}
            disabled={!commit.auto_commit}
            className="rounded-md border border-border bg-background px-2 py-1 disabled:opacity-50" />
        </label>
        <div className="flex items-center gap-3">
          <button onClick={saveCommit} disabled={commitStatus === 'saving'} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {t('liveTracker.submit')}
          </button>
          {commitStatus === 'saved' && <span className="text-sm text-muted-foreground">{t('liveTracker.saved')}</span>}
          {commitStatus === 'error' && <span className="text-sm text-destructive">{t('liveTracker.error')}</span>}
        </div>
        <p className="text-xs text-muted-foreground">{t('liveTracker.commitGlobal')}</p>
      </div>
    </div>
  );
}

function Num({ label, v, on }: { label: string; v: string; on: (x: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input type="number" min={0} value={v} onChange={(e) => on(e.target.value)} className="rounded-md border border-border bg-background px-2 py-1" />
    </label>
  );
}

export default withPermission(LiveTrackerPage, PermissionLevel.DEVELOPER);
