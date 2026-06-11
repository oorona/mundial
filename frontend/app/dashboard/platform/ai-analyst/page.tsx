'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/app/api-client';
import { BrainCircuit, Loader2, Sparkles } from 'lucide-react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

interface MatchRow {
  id: number;
  home: string | null;
  away: string | null;
  kickoff_unix: number | null;
  finished: boolean;
  round: string | null;
  grp: string | null;
  status: string | null;
  pred_home: number | null;
  pred_away: number | null;
}
interface Analysis {
  match_id: number;
  status: string;
  analysis?: string | null;
  pred_home?: number | null;
  pred_away?: number | null;
  confidence?: number | null;
}

// Tomorrow's date in Mexico City (UTC-6) — the dev runs this daily for next-day matches.
function tomorrowCDMX(): string {
  return new Date(Date.now() - 6 * 3600 * 1000 + 24 * 3600 * 1000).toISOString().slice(0, 10);
}

function AIAnalystPage() {
  const { t, language } = useTranslation();
  const locale = language === 'es' ? 'es-ES' : 'en-US';
  const [day, setDay] = useState(tomorrowCDMX());
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Record<number, Analysis>>({});
  const [busy, setBusy] = useState<Set<number>>(new Set());

  const loadDay = useCallback(() => {
    setLoading(true);
    apiClient.get<{ matches: MatchRow[] }>(`/ai-player/matches?day=${day}`)
      .then((d) => setMatches(d.matches || []))
      .catch(() => setMatches([]))
      .finally(() => setLoading(false));
  }, [day]);
  useEffect(() => { loadDay(); }, [loadDay]);

  const loadAnalysis = useCallback(async (id: number): Promise<Analysis> => {
    const a = await apiClient.get<Analysis>(`/ai-player/analysis/${id}`);
    setAnalysis((p) => ({ ...p, [id]: a }));
    return a;
  }, []);

  const pollUntilDone = useCallback((id: number) => {
    let tries = 0;
    const tick = async () => {
      tries += 1;
      let a: Analysis | null = null;
      try { a = await loadAnalysis(id); } catch { /* keep trying */ }
      if (a && (a.status === 'done' || a.status === 'error')) {
        setBusy((p) => { const n = new Set(p); n.delete(id); return n; });
        loadDay(); // refresh the row's status/decision
        return;
      }
      if (tries < 40) setTimeout(tick, 3000);
      else setBusy((p) => { const n = new Set(p); n.delete(id); return n; });
    };
    setTimeout(tick, 1500);
  }, [loadAnalysis, loadDay]);

  const analyze = async (id: number) => {
    setBusy((p) => new Set(p).add(id));
    setOpen(id);
    try {
      await apiClient.post(`/ai-player/analyze/${id}`, {});
      setAnalysis((p) => ({ ...p, [id]: { match_id: id, status: 'queued' } }));
      pollUntilDone(id);
    } catch {
      setBusy((p) => { const n = new Set(p); n.delete(id); return n; });
    }
  };

  const toggle = (id: number) => {
    const next = open === id ? null : id;
    setOpen(next);
    if (next !== null && !analysis[id]) loadAnalysis(id).catch(() => {});
  };

  const fmtTime = (u: number | null) =>
    u ? new Date(u * 1000).toLocaleString(locale, { hour: '2-digit', minute: '2-digit' }) : '—';
  const statusLabel = (s?: string | null) => t(`aiPlayer.status.${s && s !== 'none' ? s : 'none'}`);
  const canAnalyze = (m: MatchRow) => !m.finished && !!m.home && !!m.away;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4">
      <div className="flex items-center gap-3">
        <BrainCircuit className="h-7 w-7 text-fuchsia-500" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t('aiPlayer.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('aiPlayer.subtitle')}</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-foreground">{t('aiPlayer.day')}</label>
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      {!loading && matches.length === 0 && (
        <p className="text-muted-foreground">{t('aiPlayer.noMatches')}</p>
      )}

      <div className="space-y-2">
        {matches.map((m) => {
          const a = analysis[m.id];
          const status = a?.status ?? m.status ?? 'none';
          const decided = (a?.pred_home ?? m.pred_home);
          const decidedA = (a?.pred_away ?? m.pred_away);
          const hasDecision = decided !== null && decided !== undefined && decidedA !== null && decidedA !== undefined;
          const isBusy = busy.has(m.id) || status === 'queued' || status === 'running';
          return (
            <div key={m.id} className="rounded-lg border border-border bg-card">
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="w-12 text-xs text-muted-foreground">{fmtTime(m.kickoff_unix)}</span>
                <button onClick={() => toggle(m.id)} className="flex-1 text-left">
                  <span className="font-medium text-foreground">{m.home ?? t('predictions.vs')} </span>
                  <span className="text-muted-foreground">vs</span>
                  <span className="font-medium text-foreground"> {m.away ?? t('predictions.vs')}</span>
                  {hasDecision && (
                    <span className="ml-2 rounded bg-fuchsia-500/15 px-1.5 py-0.5 text-xs font-semibold text-fuchsia-600">
                      {decided}–{decidedA}
                    </span>
                  )}
                </button>
                <span className={`text-xs ${status === 'done' ? 'text-green-500' : status === 'error' ? 'text-red-500' : 'text-muted-foreground'}`}>
                  {statusLabel(status)}
                </span>
                <button onClick={() => analyze(m.id)} disabled={!canAnalyze(m) || isBusy}
                  className="flex items-center gap-1 rounded-md bg-fuchsia-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
                  {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {hasDecision ? t('aiPlayer.reanalyze') : t('aiPlayer.analyze')}
                </button>
              </div>
              {open === m.id && (
                <div className="border-t border-border px-4 py-3">
                  {isBusy && !a?.analysis && <p className="text-sm text-muted-foreground">{t('aiPlayer.analyzing')}</p>}
                  {a?.analysis && (
                    <>
                      <div className="mb-2 flex items-center gap-3 text-sm">
                        <span className="font-semibold text-foreground">{t('aiPlayer.decision')}:</span>
                        <span className="rounded bg-fuchsia-500/15 px-2 py-0.5 font-bold text-fuchsia-600">{a.pred_home}–{a.pred_away}</span>
                        {a.confidence != null && <span className="text-xs text-muted-foreground">{t('aiPlayer.confidence')}: {Math.round((a.confidence) * 100)}%</span>}
                      </div>
                      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('aiPlayer.analysisTitle')}</h4>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">{a.analysis}</p>
                    </>
                  )}
                  {!isBusy && !a?.analysis && status !== 'error' && (
                    <p className="text-sm text-muted-foreground">{t('aiPlayer.notAnalyzed')}</p>
                  )}
                  {status === 'error' && <p className="text-sm text-red-500">{t('aiPlayer.errorMsg')}</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default withPermission(AIAnalystPage, PermissionLevel.DEVELOPER);
