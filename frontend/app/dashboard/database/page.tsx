'use client';

import { useEffect, useState, useCallback, Component, ReactNode } from 'react';
import {
  Database, RefreshCw, Play, CheckCircle2, XCircle, AlertTriangle,
  ArrowUpCircle, Activity, Layers, TestTube2, Eye, EyeOff, ChevronDown, ChevronRight,
  Puzzle
} from 'lucide-react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { DATABASE_SETTINGS, DB_CATEGORIES } from '@/config/settings-definitions';

// ---------------------------------------------------------------------------
// Error boundary — catches render errors and logs them to the console so
// "see the browser console" actually has something useful in it.
// ---------------------------------------------------------------------------
interface EBState { error: Error | null }
class PageErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: null };

  static getDerivedStateFromError(error: Error): EBState {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    // Next.js swallows this in its own boundary; log explicitly so the
    // browser console always shows the real stack trace.
    console.error('[DatabaseManagementPage] render error:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
          <div className="p-4 rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 text-sm">
            <p className="font-semibold mb-1">Page render error</p>
            <pre className="text-xs font-mono whitespace-pre-wrap opacity-80">
              {this.state.error.message}
            </pre>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface PluginMigrationEntry {
  plugin: string;
  version: string;
  description: string;
  revisions: string[];
  head_revision: string;
  already_applied?: boolean;
}

interface DbInfo {
  framework_version: string;
  required_db_revision: string;
  current_db_revision: string | null;
  schema_match: boolean;
  upgrade_needed: boolean;
  revision_history: Record<string, string>;
  plugin_migrations: PluginMigrationEntry[];
  postgres: {
    status: string;
    version?: string;
    size?: string;
    active_connections?: number;
    current_revision?: string;
    error?: string;
  };
  redis: {
    status: string;
    version?: string;
    used_memory_human?: string;
    connected_clients?: number;
    uptime_in_days?: number;
    error?: string;
  };
}

interface ChangelogEntry {
  version: string;
  description: string;
  revisions: string[];
  head_revision: string;
  is_current: boolean;
  already_applied: boolean;
}

interface MigrationInfo {
  current_revision: string | null;
  current_db_version: string | null;
  head_revision: string;
  framework_version: string;
  schema_up_to_date: boolean;
  is_plugin_revision_current: boolean;
  changelog: ChangelogEntry[];
  pending_versions: ChangelogEntry[];
  plugin_migrations: PluginMigrationEntry[];
}

interface ValidationResult {
  passed: boolean;
  total_checks: number;
  passed_count: number;
  failed_count: number;
  results: Array<{ check: string; passed: boolean; detail: string }>;
}

interface ConnectionTestResult {
  postgres: { ok: boolean; database?: string; user?: string; version?: string; error?: string };
  redis: { ok: boolean; version?: string; uptime_seconds?: number; error?: string };
  all_ok: boolean;
}

interface DbSettingEntry {
  key: string;
  friendly_name: string;
  description: string;
  category: string;
  type: string;
  is_dynamic: boolean;
  is_secret: boolean;
  effective_value?: string | null;
  source?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
type TabId = 'overview' | 'connection' | 'migrations' | 'validation';

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
      ok ? 'bg-green-500/10 text-green-400 border border-green-500/30'
         : 'bg-red-500/10 text-red-400 border border-red-500/30'
    }`}>
      {ok ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
      {label}
    </span>
  );
}

function InfoRow({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/40 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium font-mono text-foreground">{value ?? '—'}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function OverviewTab({ info, onRefresh: _ }: { info: DbInfo; onRefresh: () => void }) {
  const plugin = info.plugin_migrations?.[0] ?? null;
  return (
    <div className="space-y-6">
      {/* Version status banner */}
      <div className={`flex items-start gap-3 p-4 rounded-lg border text-sm ${
        info.schema_match
          ? 'bg-green-500/10 border-green-500/30 text-green-400'
          : 'bg-amber-500/10 border-amber-500/30 text-amber-400'
      }`}>
        {info.schema_match
          ? <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
          : <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        }
        <div>
          <p className="font-semibold">
            {info.schema_match
              ? 'Database schema is up to date'
              : 'Database schema upgrade required'
            }
          </p>
          <p className="text-xs mt-0.5 opacity-80">
            Framework {info.framework_version} requires revision {info.required_db_revision}.
            {info.current_db_revision
              ? ` Current revision: ${info.current_db_revision}.`
              : ' Current revision: unknown.'
            }
            {info.upgrade_needed && ' Go to the Migrations tab to apply pending patches.'}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Framework info */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
            <Layers size={16} className="text-indigo-400" />
            Framework
          </h3>
          <div>
            <InfoRow label="Framework Version"   value={info.framework_version} />
            <InfoRow label="Required DB Revision" value={info.required_db_revision} />
            <InfoRow label="Current DB Revision"  value={info.current_db_revision} />
            <InfoRow label="Schema Status"        value={info.schema_match ? 'Matched ✓' : 'Mismatch — upgrade needed'} />
          </div>
        </div>

        {/* PostgreSQL */}
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-foreground flex items-center gap-2">
              <Database size={16} className="text-blue-400" />
              PostgreSQL
            </h3>
            <StatusPill ok={info.postgres.status === 'connected'} label={info.postgres.status} />
          </div>
          {info.postgres.error
            ? <p className="text-xs text-red-400">{info.postgres.error}</p>
            : (
              <>
                <InfoRow label="Version"            value={info.postgres.version?.split(' ')[1]} />
                <InfoRow label="Database Size"      value={info.postgres.size} />
                <InfoRow label="Active Connections" value={info.postgres.active_connections} />
              </>
            )
          }
        </div>

        {/* Redis */}
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-foreground flex items-center gap-2">
              <Activity size={16} className="text-red-400" />
              Redis
            </h3>
            <StatusPill ok={info.redis.status === 'connected'} label={info.redis.status} />
          </div>
          {info.redis.error
            ? <p className="text-xs text-red-400">{info.redis.error}</p>
            : (
              <>
                <InfoRow label="Version"           value={info.redis.version} />
                <InfoRow label="Memory Used"       value={info.redis.used_memory_human} />
                <InfoRow label="Connected Clients" value={info.redis.connected_clients} />
                <InfoRow label="Uptime (days)"     value={info.redis.uptime_in_days} />
              </>
            )
          }
        </div>

        {/* Revision history */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
            <Layers size={16} className="text-purple-400" />
            Framework ↔ DB Version History
          </h3>
          <div className="space-y-1.5">
            {Object.entries(info.revision_history).map(([fw, rev]) => (
              <div key={fw} className="flex items-center justify-between text-xs">
                <code className="font-mono text-muted-foreground">Framework {fw}</code>
                <code className="font-mono text-foreground bg-muted/30 px-2 py-0.5 rounded">{rev}</code>
              </div>
            ))}
          </div>
        </div>

        {/* Plugin */}
        {plugin && (
          <div className="bg-card border border-border rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-foreground flex items-center gap-2">
                <Puzzle size={16} className="text-violet-400" />
                Plugin — {plugin.plugin}
              </h3>
              {plugin.already_applied === true
                ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">Migration applied</span>
                : <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20">Migration pending</span>
              }
            </div>
            <InfoRow label="Version"       value={plugin.version} />
            <InfoRow label="Head Revision" value={plugin.head_revision} />
            <p className="text-xs text-muted-foreground mt-2">{plugin.description}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ConnectionTab() {
  const [dbSettings, setDbSettings]     = useState<Record<string, DbSettingEntry[]> | null>(null);
  const [loading, setLoading]           = useState(true);
  const [testing, setTesting]           = useState(false);
  const [testResult, setTestResult]     = useState<ConnectionTestResult | null>(null);
  const [showSecrets, setShowSecrets]   = useState<Record<string, boolean>>({});
  const [collapsed, setCollapsed]       = useState<Record<string, boolean>>({});

  useEffect(() => {
    apiClient.getDatabaseSettings()
      .then(res => setDbSettings(res.settings))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await apiClient.testDatabaseConnection();
      setTestResult(res);
    } catch {
      setTestResult({ all_ok: false, postgres: { ok: false, error: 'Request failed' }, redis: { ok: false } });
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <div className="text-muted-foreground text-sm py-8 text-center">Loading connection settings…</div>;

  return (
    <div className="space-y-6">
      {/* Test connection button */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Test the currently configured connections. Settings are read-only here — change them in your
          environment variables or Docker secrets and restart the server.
        </p>
        <button
          onClick={handleTestConnection}
          disabled={testing}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50 shrink-0 ml-4"
        >
          <Play size={14} className={testing ? 'animate-pulse' : ''} />
          {testing ? 'Testing…' : 'Test Connection'}
        </button>
      </div>

      {/* Test results */}
      {testResult && (
        <div className={`p-4 rounded-lg border text-sm ${
          testResult.all_ok
            ? 'bg-green-500/10 border-green-500/30 text-green-400'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>
          <p className="font-semibold mb-2">{testResult.all_ok ? '✓ All connections healthy' : '✗ Connection issue detected'}</p>
          <div className="space-y-1 text-xs">
            <p>PostgreSQL: {testResult.postgres.ok ? `✓ Connected as ${testResult.postgres.user} on ${testResult.postgres.database}` : `✗ ${testResult.postgres.error ?? 'Failed'}`}</p>
            <p>Redis: {testResult.redis.ok ? `✓ Connected — Redis ${testResult.redis.version}` : `✗ ${testResult.redis.error ?? 'Failed'}`}</p>
          </div>
        </div>
      )}

      {/* DB settings display (read-only) */}
      {Object.keys(DB_CATEGORIES).map(catKey => {
        const catLabel    = DB_CATEGORIES[catKey as keyof typeof DB_CATEGORIES];
        const catSettings = dbSettings?.[catKey] ?? [];
        if (catSettings.length === 0) return null;
        const isCollapsed = collapsed[catKey] ?? false;

        return (
          <div key={catKey} className="bg-card border border-border rounded-xl overflow-hidden">
            <button
              type="button"
              className="w-full flex items-center justify-between px-6 py-4 hover:bg-muted/20 transition-colors"
              onClick={() => setCollapsed(prev => ({ ...prev, [catKey]: !prev[catKey] }))}
            >
              <h3 className="font-semibold text-foreground">{catLabel}</h3>
              {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
            </button>

            {!isCollapsed && (
              <div className="border-t border-border divide-y divide-border/50">
                {catSettings.map((s: DbSettingEntry) => (
                  <div key={s.key} className="px-6 py-4">
                    <div className="flex flex-col md:flex-row md:items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className="font-medium text-sm text-foreground">{s.friendly_name}</span>
                          <code className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded font-mono">{s.key}</code>
                          {s.is_secret && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs border bg-red-500/10 text-red-400 border-red-500/30">Secret</span>
                          )}
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs border bg-amber-500/10 text-amber-400 border-amber-500/30">Requires restart</span>
                        </div>
                        <p className="text-xs text-muted-foreground mb-2">{s.description}</p>
                        <div className="flex items-center gap-2">
                          {s.is_secret ? (
                            <>
                              <code className="text-sm font-mono bg-muted/30 px-2 py-1 rounded text-foreground">
                                {showSecrets[s.key] ? (s.effective_value ?? '(not set)') : '••••••••'}
                              </code>
                              <button
                                type="button"
                                onClick={() => setShowSecrets(prev => ({ ...prev, [s.key]: !prev[s.key] }))}
                                className="text-muted-foreground hover:text-foreground"
                              >
                                {showSecrets[s.key] ? <EyeOff size={14} /> : <Eye size={14} />}
                              </button>
                            </>
                          ) : (
                            <code className="text-sm font-mono bg-muted/30 px-2 py-1 rounded text-foreground">
                              {s.effective_value ?? '(not set)'}
                            </code>
                          )}
                          {s.source && (
                            <span className="text-xs text-muted-foreground">from {s.source}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface ApplyResult { success: boolean; stdout: string; stderr: string; label: string }

function MigrationsTab() {
  const [data, setData]                   = useState<MigrationInfo | null>(null);
  const [loading, setLoading]             = useState(true);
  const [applyingFw, setApplyingFw]       = useState(false);
  const [applyingPlugin, setApplyingPlugin] = useState<string | null>(null);
  const [result, setResult]               = useState<ApplyResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.getDatabaseMigrations();
      setData(res);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleUpgradeFramework = async () => {
    setApplyingFw(true);
    setResult(null);
    try {
      const res = await apiClient.upgradeFrameworkSchema();
      setResult({ ...res, label: `Framework v${data?.framework_version}` });
      await load();
    } catch {
      setResult({ success: false, stdout: '', stderr: 'Request failed', label: 'Framework upgrade' });
    } finally {
      setApplyingFw(false);
    }
  };

  const handleApplyPlugin = async (pluginName: string) => {
    setApplyingPlugin(pluginName);
    setResult(null);
    try {
      const res = await apiClient.applyPluginMigration(pluginName);
      setResult({ ...res, label: `Plugin: ${pluginName}` });
      await load();
    } catch {
      setResult({ success: false, stdout: '', stderr: 'Request failed', label: `Plugin: ${pluginName}` });
    } finally {
      setApplyingPlugin(null);
    }
  };

  if (loading) return <div className="text-muted-foreground text-sm py-8 text-center">Loading migration status…</div>;
  if (!data)   return <div className="text-red-400 text-sm py-8 text-center">Failed to load migrations.</div>;

  const frameworkPending = !data.schema_up_to_date;
  const pendingPlugins   = data.plugin_migrations?.filter(p => !p.already_applied) ?? [];
  const busy             = applyingFw || !!applyingPlugin;

  return (
    <div className="space-y-6">

      {/* ── Action cards ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Framework card */}
        <div className={`rounded-xl border p-5 space-y-3 ${
          frameworkPending ? 'border-amber-500/30 bg-amber-500/5' : 'border-border bg-card'
        }`}>
          <div className="flex items-center gap-2">
            <Layers size={15} className={frameworkPending ? 'text-amber-400' : 'text-indigo-400'} />
            <h3 className="font-semibold text-sm text-foreground">Framework Schema</h3>
            {frameworkPending
              ? <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  <AlertTriangle size={10} /> {data.pending_versions.length} version(s) pending
                </span>
              : <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">
                  <CheckCircle2 size={10} /> Up to date
                </span>
            }
          </div>
          <p className="text-xs text-muted-foreground">
            v{data.framework_version} · head: <code className="font-mono">{data.head_revision}</code>
          </p>
          {frameworkPending && (
            <button
              onClick={handleUpgradeFramework}
              disabled={busy}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-500/90 text-sm font-medium transition-colors disabled:opacity-50"
            >
              <ArrowUpCircle size={14} className={applyingFw ? 'animate-bounce' : ''} />
              {applyingFw ? 'Upgrading…' : `Upgrade to v${data.framework_version}`}
            </button>
          )}
        </div>

        {/* Plugin card */}
        <div className={`rounded-xl border p-5 space-y-3 ${
          pendingPlugins.length > 0 ? 'border-violet-500/30 bg-violet-500/5' : 'border-border bg-card'
        }`}>
          <div className="flex items-center gap-2">
            <Puzzle size={15} className={pendingPlugins.length > 0 ? 'text-violet-400' : 'text-green-400'} />
            <h3 className="font-semibold text-sm text-foreground">Plugin Migrations</h3>
            {pendingPlugins.length > 0
              ? <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-violet-500/10 text-violet-400 border border-violet-500/20">
                  <AlertTriangle size={10} /> {pendingPlugins.length} pending
                </span>
              : <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">
                  <CheckCircle2 size={10} /> {data.plugin_migrations?.length ? 'All applied' : 'None installed'}
                </span>
            }
          </div>
          <p className="text-xs text-muted-foreground">
            Independent branches — do not affect framework versioning
          </p>
          {data.plugin_migrations?.length === 0 && (
            <p className="text-xs text-muted-foreground/60">Install a plugin with a migration component to see it here.</p>
          )}
          {(data.plugin_migrations?.length ?? 0) > 0 && (
            <div className="space-y-2">
              {data.plugin_migrations.map(p => (
                <div key={p.plugin} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <code className="text-xs font-mono text-foreground">{p.plugin}</code>
                    <span className="text-xs text-muted-foreground ml-1.5">v{p.version}</span>
                  </div>
                  {p.already_applied ? (
                    <span className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">
                      <CheckCircle2 size={10} /> Applied
                    </span>
                  ) : (
                    <button
                      onClick={() => handleApplyPlugin(p.plugin)}
                      disabled={busy || frameworkPending}
                      title={frameworkPending ? 'Apply framework migrations first' : undefined}
                      className="shrink-0 flex items-center gap-1.5 px-3 py-1 rounded text-xs bg-violet-600 text-white hover:bg-violet-600/90 disabled:opacity-50 transition-colors"
                    >
                      <ArrowUpCircle size={11} className={applyingPlugin === p.plugin ? 'animate-bounce' : ''} />
                      {applyingPlugin === p.plugin ? 'Applying…' : 'Apply'}
                    </button>
                  )}
                </div>
              ))}
              {frameworkPending && pendingPlugins.length > 0 && (
                <p className="text-xs text-amber-400 pt-1">
                  ⚠ Apply framework upgrade first — plugin buttons are disabled until then.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Result output ─────────────────────────────────────────────────── */}
      {result && (
        <div className={`p-4 rounded-lg border text-xs font-mono whitespace-pre-wrap ${
          result.success
            ? 'bg-green-500/10 border-green-500/30 text-green-300'
            : 'bg-red-500/10 border-red-500/30 text-red-300'
        }`}>
          {result.success ? `✓ ${result.label} — applied\n` : `✗ ${result.label} — failed\n`}
          {result.stdout}
          {result.stderr}
        </div>
      )}

      {/* ── Framework changelog ───────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center gap-2">
          <Layers size={15} className="text-indigo-400" />
          <h3 className="font-semibold text-foreground">Framework Migration History</h3>
        </div>
        <div className="divide-y divide-border/50">
          {data.changelog.map((entry, idx) => {
            // When a plugin is the current revision, the framework head entry
            // is still fully applied — mark it as the framework's current state.
            const isFwHead = entry.head_revision === data.head_revision && data.is_plugin_revision_current;
            return (
              <div key={idx} className={`px-6 py-4 ${entry.is_current || isFwHead ? 'bg-primary/5' : ''}`}>
                <div className="flex items-center gap-3 mb-1 flex-wrap">
                  <code className={`text-xs font-mono font-semibold ${entry.is_current || isFwHead ? 'text-primary' : 'text-foreground'}`}>
                    v{entry.version}
                  </code>
                  {(entry.is_current || isFwHead) && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-primary/10 text-primary border border-primary/20">
                      Framework head
                    </span>
                  )}
                  {entry.already_applied && !entry.is_current && !isFwHead && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">Applied</span>
                  )}
                  {!entry.already_applied && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20">Pending</span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{entry.description}</p>
                <p className="text-xs font-mono text-muted-foreground/60 mt-1">head: {entry.head_revision}</p>
              </div>
            );
          })}
          {data.changelog.length === 0 && (
            <div className="px-6 py-4 text-sm text-muted-foreground">No migration history available.</div>
          )}
        </div>
      </div>

      {/* ── Plugin migration history ──────────────────────────────────────── */}
      {(data.plugin_migrations?.length ?? 0) > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-border flex items-center gap-2">
            <Puzzle size={15} className="text-violet-400" />
            <h3 className="font-semibold text-foreground">Plugin Migration History</h3>
            <span className="text-xs text-muted-foreground ml-1">Each plugin is an independent Alembic branch</span>
          </div>
          <div className="divide-y divide-border/50">
            {data.plugin_migrations.map((entry, idx) => (
              <div key={idx} className="px-6 py-4">
                <div className="flex items-center gap-3 mb-1 flex-wrap">
                  <code className="text-xs font-mono font-semibold text-foreground">
                    {entry.plugin} v{entry.version}
                  </code>
                  {entry.already_applied ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-500/10 text-green-400 border border-green-500/20">
                      <CheckCircle2 size={10} /> Applied
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-violet-500/10 text-violet-400 border border-violet-500/20">
                      <AlertTriangle size={10} /> Pending
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{entry.description}</p>
                <p className="text-xs font-mono text-muted-foreground/60 mt-1">branch head: {entry.head_revision}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ValidationTab() {
  const [data, setData]       = useState<ValidationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [ran, setRan]         = useState(false);

  const run = async () => {
    setLoading(true);
    setRan(true);
    try {
      const res = await apiClient.validateDatabase();
      setData(res);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h3 className="font-semibold text-foreground">Database Validation Suite</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Validates table existence, column structure, schema version, and seeded catalog data.
          </p>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50 shrink-0"
        >
          <TestTube2 size={14} className={loading ? 'animate-pulse' : ''} />
          {loading ? 'Running…' : ran ? 'Re-run Validation' : 'Run Validation'}
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="flex flex-col items-center gap-4">
            <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
            <p className="text-sm text-muted-foreground">Running validation checks…</p>
          </div>
        </div>
      )}

      {!loading && data && (
        <>
          {/* Summary */}
          <div className={`flex items-center gap-4 p-4 rounded-lg border ${
            data.passed
              ? 'bg-green-500/10 border-green-500/30'
              : 'bg-red-500/10 border-red-500/30'
          }`}>
            {data.passed
              ? <CheckCircle2 size={24} className="text-green-400 shrink-0" />
              : <XCircle size={24} className="text-red-400 shrink-0" />
            }
            <div>
              <p className={`font-semibold ${data.passed ? 'text-green-400' : 'text-red-400'}`}>
                {data.passed ? 'All checks passed' : `${data.failed_count} check(s) failed`}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {data.passed_count} / {data.total_checks} checks passed
              </p>
            </div>
          </div>

          {/* Results list */}
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="divide-y divide-border/50">
              {data.results.map((r, idx) => (
                <div key={idx} className={`px-6 py-3 flex items-start gap-3 ${r.check.startsWith('  ') ? 'pl-10' : ''}`}>
                  {r.passed
                    ? <CheckCircle2 size={14} className="text-green-400 mt-0.5 shrink-0" />
                    : <XCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
                  }
                  <div className="min-w-0">
                    <code className="text-xs font-mono text-foreground">{r.check.trim()}</code>
                    {!r.passed && (
                      <p className="text-xs text-red-400 mt-0.5">{r.detail}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {!loading && ran && !data && (
        <div className="text-center py-12 text-red-400 text-sm">
          Validation request failed. Check backend logs.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function DatabaseManagementPage() {
  const [info, setInfo]       = useState<DbInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setTab]   = useState<TabId>('overview');

  const loadInfo = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.getDatabaseInfo();
      setInfo(res);
    } catch {
      setInfo(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadInfo(); }, [loadInfo]);

  const tabs: { id: TabId; label: string; icon: any }[] = [
    { id: 'overview',    label: 'Overview',    icon: Database },
    { id: 'connection',  label: 'Connection',  icon: Activity },
    { id: 'migrations',  label: 'Migrations',  icon: ArrowUpCircle },
    { id: 'validation',  label: 'Validation',  icon: TestTube2 },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="p-2 rounded-lg bg-blue-500/10">
              <Database className="text-blue-500" size={22} />
            </div>
            <h1 className="text-3xl font-bold text-foreground">Database Management</h1>
          </div>
          <p className="text-muted-foreground">
            Monitor connections, manage schema migrations, and validate the database state.
          </p>
        </div>
        <button
          onClick={loadInfo}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border bg-background hover:bg-muted/40 text-sm font-medium transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Quick status bar */}
      {info && (
        <div className="flex flex-wrap gap-3">
          <StatusPill ok={info.postgres.status === 'connected'} label={`PostgreSQL: ${info.postgres.status}`} />
          <StatusPill ok={info.redis.status === 'connected'} label={`Redis: ${info.redis.status}`} />
          <StatusPill ok={info.schema_match} label={info.schema_match ? 'Schema: current' : 'Schema: upgrade needed'} />
          {info.plugin_migrations?.length > 0 && (
            <StatusPill
              ok={info.plugin_migrations.every(p => p.already_applied !== false)}
              label={info.plugin_migrations.every(p => p.already_applied !== false) ? 'Plugin: applied' : 'Plugin: migration pending'}
            />
          )}
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
            <Layers size={11} />
            Framework {info.framework_version}
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-border">
        <div className="flex gap-0">
          {tabs.map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-primary text-primary'
                    : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                }`}
              >
                <Icon size={14} />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab content */}
      {loading && activeTab === 'overview' ? (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-4">
            <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
            <p className="text-muted-foreground animate-pulse">Loading database info…</p>
          </div>
        </div>
      ) : (
        <>
          {activeTab === 'overview'   && info   && <OverviewTab info={info} onRefresh={loadInfo} />}
          {activeTab === 'overview'   && !info  && !loading && <div className="text-center py-12 text-red-400 text-sm">Failed to load database information. Check backend connectivity.</div>}
          {activeTab === 'connection'  && <ConnectionTab />}
          {activeTab === 'migrations'  && <MigrationsTab />}
          {activeTab === 'validation'  && <ValidationTab />}
        </>
      )}
    </div>
  );
}

function DatabaseManagementPageWithBoundary(props: object) {
  return (
    <PageErrorBoundary>
      <DatabaseManagementPage {...(props as any)} />
    </PageErrorBoundary>
  );
}

export default withPermission(DatabaseManagementPageWithBoundary, PermissionLevel.DEVELOPER);
