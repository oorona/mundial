'use client';

import { useState, useCallback, useEffect } from 'react';
import {
  Lock, Database, Server, MessageCircle, Settings2, CheckCircle2,
  XCircle, AlertTriangle, ChevronRight, ChevronLeft, Eye, EyeOff,
  RefreshCw, ArrowUpCircle, Shuffle, Layers, Bot, ShieldOff
} from 'lucide-react';

// ---------------------------------------------------------------------------
// API helpers (direct fetch — apiClient uses auth interceptors we can't rely on)
// ---------------------------------------------------------------------------
const BASE = '/api/v1/setup';

async function setupFetch(path: string, method = 'GET', body?: object, key?: string) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (key) headers['X-Setup-Key'] = key;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface PostgresConfig     { host: string; port: string; user: string; db: string; password: string; }
interface RedisConfig        { host: string; port: string; db: string; password: string; }
interface DiscordConfig      { client_id: string; client_secret: string; bot_token: string; redirect_uri: string; guild_id: string; developer_role_id: string; }
interface BotIdentityConfig  { name: string; tagline: string; tagline_es: string; description: string; description_es: string; invite_url: string; }
interface AppConfig          { api_secret_key: string; app_name: string; openai_api_key: string; google_api_key: string; anthropic_api_key: string; xai_api_key: string; }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function randomHex(n: number) {
  return Array.from(crypto.getRandomValues(new Uint8Array(n)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

function SecretInput({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">{label}</label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full px-3 py-2 pr-10 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
        />
        <button type="button" onClick={() => setShow(s => !s)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}

function TextInput({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
      />
    </div>
  );
}

function StatusBox({ ok, message }: { ok: boolean | null; message: string }) {
  if (ok === null) return null;
  return (
    <div className={`flex items-start gap-2 p-3 rounded-lg text-sm border ${
      ok ? 'bg-green-500/10 border-green-500/30 text-green-400'
         : 'bg-red-500/10 border-red-500/30 text-red-400'
    }`}>
      {ok ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <XCircle size={14} className="mt-0.5 shrink-0" />}
      <span className="whitespace-pre-wrap">{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------
const STEPS = [
  { label: 'Key',        icon: Lock },
  { label: 'PostgreSQL', icon: Database },
  { label: 'Schema',     icon: Layers },
  { label: 'Redis',      icon: Server },
  { label: 'Discord',    icon: MessageCircle },
  { label: 'Bot',        icon: Bot },
  { label: 'App',        icon: Settings2 },
  { label: 'Save',       icon: CheckCircle2 },
];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center justify-center gap-0 mb-10">
      {STEPS.map((s, i) => {
        const Icon = s.icon;
        const done    = i < current;
        const active  = i === current;
        return (
          <div key={i} className="flex items-center">
            <div className={`flex items-center justify-center w-9 h-9 rounded-full text-xs font-bold transition-all ${
              done   ? 'bg-green-500 text-white' :
              active ? 'bg-primary text-primary-foreground ring-4 ring-primary/20' :
                       'bg-muted text-muted-foreground'
            }`}>
              {done ? <CheckCircle2 size={16} /> : <Icon size={15} />}
            </div>
            <div className="hidden sm:block text-xs text-muted-foreground mx-1.5 min-w-[40px] text-center">
              {s.label}
            </div>
            {i < STEPS.length - 1 && (
              <div className={`w-6 h-0.5 mx-1 ${i < current ? 'bg-green-500' : 'bg-border'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main wizard
// ---------------------------------------------------------------------------
export default function SetupWizardPage() {
  // ── Access gate ───────────────────────────────────────────────────────────
  const [pageReady, setPageReady] = useState(false);
  const [accessDenied, setAccessDenied] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const stateRes = await fetch('/api/v1/setup/state');
        const state = await stateRes.json();

        if (!state.setup_complete) {
          // First-time setup — allow anyone (no auth configured yet)
          setPageReady(true);
          return;
        }

        // Setup is complete — require platform admin authentication
        const meRes = await fetch('/api/v1/auth/me', { credentials: 'include' });
        if (!meRes.ok) {
          setAccessDenied('sign-in');
          return;
        }
        const me = await meRes.json();
        if (me.permission_level !== 'admin') {
          setAccessDenied('forbidden');
          return;
        }

        setPageReady(true);
      } catch {
        setAccessDenied('error');
      }
    })();
  }, []);

  const [step, setStep] = useState(0);
  const [setupKey, setSetupKey] = useState('');
  const [keyVerified, setKeyVerified] = useState(false);
  const [verifyError, setVerifyError] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [existingLoaded, setExistingLoaded] = useState(false);

  // Per-step state
  const [pg, setPg] = useState<PostgresConfig>({ host: 'postgres', port: '5432', user: 'baseline', db: 'baseline', password: '' });
  const [pgStatus, setPgStatus] = useState<{ ok: boolean | null; message: string }>({ ok: null, message: '' });
  const [pgTesting, setPgTesting] = useState(false);

  const [migrations, setMigrations] = useState<{ current: string | null; required: string; upToDate: boolean; fresh: boolean; queryError?: string } | null>(null);
  const [migrLoading, setMigrLoading] = useState(false);
  const [migrApplying, setMigrApplying] = useState(false);
  const [migrStatus, setMigrStatus] = useState<{ ok: boolean | null; message: string }>({ ok: null, message: '' });
  const [migrLog, setMigrLog] = useState<string[]>([]);

  const [rd, setRd] = useState<RedisConfig>({ host: 'redis', port: '6379', db: '0', password: '' });
  const [rdStatus, setRdStatus] = useState<{ ok: boolean | null; message: string }>({ ok: null, message: '' });
  const [rdTesting, setRdTesting] = useState(false);

  const [discord, setDiscord] = useState<DiscordConfig>({ client_id: '', client_secret: '', bot_token: '', redirect_uri: 'http://localhost:3000/auth/callback', guild_id: '', developer_role_id: '' });

  const [botId, setBotId] = useState<BotIdentityConfig>({ name: '', tagline: '', tagline_es: '', description: '', description_es: '', invite_url: '' });

  const [appCfg, setAppCfg] = useState<AppConfig>({ api_secret_key: '', app_name: '', openai_api_key: '', google_api_key: '', anthropic_api_key: '', xai_api_key: '' });

  const [saving, setSaving] = useState(false);
  const [saved, setSaved]   = useState(false);
  const [saveError, setSaveError] = useState('');
  const [restarting, setRestarting] = useState(false);

  // ── Step 0: Key verification ───────────────────────────────────────────────
  const handleVerifyKey = async () => {
    setVerifying(true);
    setVerifyError('');
    try {
      await setupFetch('/verify-key', 'POST', { key: setupKey });
      setKeyVerified(true);

      // Load existing settings and pre-populate form fields
      try {
        const { settings: s } = await setupFetch('/current-settings', 'GET', undefined, setupKey);
        if (s && Object.keys(s).length > 0) {
          if (s.POSTGRES_HOST)     setPg(p => ({ ...p, host:     s.POSTGRES_HOST }));
          if (s.POSTGRES_PORT)     setPg(p => ({ ...p, port:     s.POSTGRES_PORT }));
          if (s.POSTGRES_USER)     setPg(p => ({ ...p, user:     s.POSTGRES_USER }));
          if (s.POSTGRES_DB)       setPg(p => ({ ...p, db:       s.POSTGRES_DB }));
          if (s.POSTGRES_PASSWORD) setPg(p => ({ ...p, password: s.POSTGRES_PASSWORD }));

          if (s.REDIS_HOST)     setRd(r => ({ ...r, host:     s.REDIS_HOST }));
          if (s.REDIS_PORT)     setRd(r => ({ ...r, port:     s.REDIS_PORT }));
          if (s.REDIS_DB)       setRd(r => ({ ...r, db:       s.REDIS_DB }));
          if (s.REDIS_PASSWORD) setRd(r => ({ ...r, password: s.REDIS_PASSWORD }));

          setDiscord(d => ({
            ...d,
            ...(s.DISCORD_CLIENT_ID     ? { client_id:        s.DISCORD_CLIENT_ID }     : {}),
            ...(s.DISCORD_CLIENT_SECRET ? { client_secret:    s.DISCORD_CLIENT_SECRET } : {}),
            ...(s.DISCORD_BOT_TOKEN     ? { bot_token:        s.DISCORD_BOT_TOKEN }     : {}),
            ...(s.DISCORD_REDIRECT_URI  ? { redirect_uri:     s.DISCORD_REDIRECT_URI }  : {}),
            ...(s.DISCORD_GUILD_ID      ? { guild_id:         s.DISCORD_GUILD_ID }      : {}),
            ...(s.DEVELOPER_ROLE_ID     ? { developer_role_id: s.DEVELOPER_ROLE_ID }    : {}),
          }));

          setBotId(b => ({
            ...b,
            ...(s.BOT_NAME           ? { name:           s.BOT_NAME }           : {}),
            ...(s.BOT_TAGLINE        ? { tagline:        s.BOT_TAGLINE }        : {}),
            ...(s.BOT_TAGLINE_ES     ? { tagline_es:     s.BOT_TAGLINE_ES }     : {}),
            ...(s.BOT_DESCRIPTION    ? { description:    s.BOT_DESCRIPTION }    : {}),
            ...(s.BOT_DESCRIPTION_ES ? { description_es: s.BOT_DESCRIPTION_ES } : {}),
            ...(s.BOT_INVITE_URL     ? { invite_url:     s.BOT_INVITE_URL }     : {}),
          }));

          setAppCfg(a => ({
            ...a,
            ...(s.API_SECRET_KEY    ? { api_secret_key:    s.API_SECRET_KEY }    : {}),
            ...(s.APP_NAME          ? { app_name:          s.APP_NAME }          : {}),
            ...(s.OPENAI_API_KEY    ? { openai_api_key:    s.OPENAI_API_KEY }    : {}),
            ...(s.GOOGLE_API_KEY    ? { google_api_key:    s.GOOGLE_API_KEY }    : {}),
            ...(s.ANTHROPIC_API_KEY ? { anthropic_api_key: s.ANTHROPIC_API_KEY } : {}),
            ...(s.XAI_API_KEY       ? { xai_api_key:       s.XAI_API_KEY }       : {}),
          }));

          setExistingLoaded(true);
        }
      } catch { /* no existing settings — fresh setup, continue normally */ }

      setStep(1);
    } catch (e: any) {
      setVerifyError(e.message || 'Key verification failed');
    } finally {
      setVerifying(false);
    }
  };

  // ── Step 1: PostgreSQL test ────────────────────────────────────────────────
  const handleTestPg = async () => {
    setPgTesting(true);
    setPgStatus({ ok: null, message: '' });
    try {
      const res = await setupFetch('/test-postgres', 'POST', { host: pg.host, port: parseInt(pg.port), user: pg.user, db: pg.db, password: pg.password }, setupKey);
      if (res.ok) {
        setPgStatus({ ok: true, message: `Connected ✓\nUser: ${res.user} · DB: ${res.database} · Size: ${res.db_size ?? 'N/A'}\n${res.version?.split('\n')[0]}` });
      } else {
        setPgStatus({ ok: false, message: res.error ?? 'Connection failed' });
      }
    } catch (e: any) {
      setPgStatus({ ok: false, message: e.message });
    } finally {
      setPgTesting(false);
    }
  };

  // ── Step 2: Migration check + apply ───────────────────────────────────────
  const handleCheckMigrations = useCallback(async () => {
    setMigrLoading(true);
    setMigrStatus({ ok: null, message: '' });
    try {
      const res = await setupFetch('/check-migrations', 'POST', { host: pg.host, port: parseInt(pg.port), user: pg.user, db: pg.db, password: pg.password }, setupKey);
      if (res.error) {
        setMigrStatus({ ok: false, message: res.error });
      } else {
        setMigrations({ current: res.current_revision, required: res.required_revision, upToDate: res.up_to_date, fresh: res.is_fresh_database, queryError: res.query_error });
      }
    } catch (e: any) {
      setMigrStatus({ ok: false, message: e.message });
    } finally {
      setMigrLoading(false);
    }
  }, [pg, setupKey]);

  const handleApplyMigrations = async () => {
    setMigrApplying(true);
    setMigrStatus({ ok: null, message: '' });
    setMigrLog([]);
    try {
      const res = await fetch(`${BASE}/apply-migrations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Setup-Key': setupKey },
        body: JSON.stringify({ host: pg.host, port: parseInt(pg.port), user: pg.user, db: pg.db, password: pg.password }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';
        for (const part of parts) {
          const dataLine = part.split('\n').find(l => l.startsWith('data: '));
          if (!dataLine) continue;
          try {
            const event = JSON.parse(dataLine.slice(6));
            if (event.line !== undefined) {
              setMigrLog(prev => [...prev, event.line]);
            }
            if (event.done) {
              if (event.success) {
                setMigrStatus({ ok: true, message: 'Migrations applied successfully.' });
                await handleCheckMigrations();
              } else {
                setMigrStatus({ ok: false, message: `Migration failed (exit code ${event.returncode})` });
              }
            }
          } catch { /* ignore malformed SSE frames */ }
        }
      }
    } catch (e: any) {
      setMigrStatus({ ok: false, message: e.message });
    } finally {
      setMigrApplying(false);
    }
  };

  // ── Step 3: Redis test ─────────────────────────────────────────────────────
  const handleTestRedis = async () => {
    setRdTesting(true);
    setRdStatus({ ok: null, message: '' });
    try {
      const res = await setupFetch('/test-redis', 'POST', { host: rd.host, port: parseInt(rd.port), db: parseInt(rd.db), password: rd.password || null }, setupKey);
      if (res.ok) {
        setRdStatus({ ok: true, message: `Connected ✓\nRedis ${res.version} · Uptime: ${res.uptime_days ?? '?'} day(s)` });
      } else {
        setRdStatus({ ok: false, message: res.error ?? 'Connection failed' });
      }
    } catch (e: any) {
      setRdStatus({ ok: false, message: e.message });
    } finally {
      setRdTesting(false);
    }
  };

  // ── Step 6: Save + restart ─────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    const allSettings: Record<string, string> = {
      POSTGRES_HOST: pg.host, POSTGRES_PORT: pg.port, POSTGRES_USER: pg.user,
      POSTGRES_DB: pg.db, POSTGRES_PASSWORD: pg.password,
      REDIS_HOST: rd.host, REDIS_PORT: rd.port, REDIS_DB: rd.db,
      ...(rd.password ? { REDIS_PASSWORD: rd.password } : {}),
      DISCORD_CLIENT_ID: discord.client_id, DISCORD_CLIENT_SECRET: discord.client_secret,
      DISCORD_BOT_TOKEN: discord.bot_token, DISCORD_REDIRECT_URI: discord.redirect_uri,
      ...(discord.guild_id         ? { DISCORD_GUILD_ID:    discord.guild_id }         : {}),
      ...(discord.developer_role_id ? { DEVELOPER_ROLE_ID: discord.developer_role_id } : {}),
      BOT_NAME: botId.name,
      ...(botId.tagline        ? { BOT_TAGLINE:        botId.tagline }        : {}),
      ...(botId.tagline_es     ? { BOT_TAGLINE_ES:     botId.tagline_es }     : {}),
      ...(botId.description    ? { BOT_DESCRIPTION:    botId.description }    : {}),
      ...(botId.description_es ? { BOT_DESCRIPTION_ES: botId.description_es } : {}),
      ...(botId.invite_url     ? { BOT_INVITE_URL:     botId.invite_url }     : {}),
      API_SECRET_KEY: appCfg.api_secret_key,
      APP_NAME: appCfg.app_name,
      NEXT_PUBLIC_APP_NAME: appCfg.app_name,
      ...(appCfg.openai_api_key    ? { OPENAI_API_KEY:    appCfg.openai_api_key }    : {}),
      ...(appCfg.google_api_key    ? { GOOGLE_API_KEY:    appCfg.google_api_key }    : {}),
      ...(appCfg.anthropic_api_key ? { ANTHROPIC_API_KEY: appCfg.anthropic_api_key } : {}),
      ...(appCfg.xai_api_key       ? { XAI_API_KEY:       appCfg.xai_api_key }       : {}),
    };
    try {
      await setupFetch('/save', 'POST', { settings: allSettings }, setupKey);
      setSaved(true);
    } catch (e: any) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await setupFetch('/restart', 'POST', undefined, setupKey);
      // Poll /health until the app comes back
      const poll = setInterval(async () => {
        try {
          const res = await fetch('/api/v1/health');
          const data = await res.json();
          if (res.ok && !data.setup_mode) {
            clearInterval(poll);
            window.location.href = '/';
          }
        } catch { /* still restarting */ }
      }, 2000);
    } catch { setRestarting(false); }
  };

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------
  const card = (children: React.ReactNode) => (
    <div className="bg-card border border-border rounded-2xl p-8 shadow-lg">{children}</div>
  );

  const navButtons = (onNext?: () => void, nextLabel = 'Next', nextDisabled = false, onBack?: () => void) => (
    <div className="flex items-center justify-between pt-6 mt-6 border-t border-border">
      {onBack ? (
        <button onClick={onBack} className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ChevronLeft size={14} /> Back
        </button>
      ) : <div />}
      {onNext && (
        <button onClick={onNext} disabled={nextDisabled} className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50">
          {nextLabel} <ChevronRight size={14} />
        </button>
      )}
    </div>
  );

  // ---------------------------------------------------------------------------
  // Steps
  // ---------------------------------------------------------------------------

  const renderStep = () => {
    switch (step) {
      // ── Step 0: Welcome & key ────────────────────────────────────────────
      case 0: return card(<>
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
            <Lock className="text-primary" size={32} />
          </div>
          <h2 className="text-2xl font-bold text-foreground mb-2">Platform Setup Wizard</h2>
          <p className="text-muted-foreground text-sm max-w-md mx-auto">
            First-time setup or updating an existing configuration — all settings are encrypted and stored securely on disk.
          </p>
        </div>

        <div className="max-w-sm mx-auto space-y-4">
          <SecretInput
            label="Encryption Key"
            value={setupKey}
            onChange={setSetupKey}
            placeholder="Enter the ENCRYPTION_KEY from your docker-compose environment"
          />
          <p className="text-xs text-muted-foreground">
            This is the <code className="font-mono bg-muted/50 px-1 rounded">ENCRYPTION_KEY</code> environment
            variable you set in your docker-compose file. It proves you have infrastructure access and
            will be used to encrypt all critical settings on disk.
          </p>
          {verifyError && <p className="text-sm text-red-400">{verifyError}</p>}
          <button onClick={handleVerifyKey} disabled={!setupKey || verifying}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50">
            {verifying ? <RefreshCw size={14} className="animate-spin" /> : <Lock size={14} />}
            {verifying ? 'Verifying…' : 'Verify Key & Begin Setup'}
          </button>
        </div>
      </>);

      // ── Step 1: PostgreSQL ───────────────────────────────────────────────
      case 1: return card(<>
        {existingLoaded && (
          <div className="flex items-start gap-2 p-3 mb-5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-sm">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
            <span>Existing configuration loaded — fields are pre-filled. Change only what you need, then proceed to Save.</span>
          </div>
        )}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-blue-500/10"><Database className="text-blue-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">PostgreSQL Configuration</h2>
            <p className="text-sm text-muted-foreground">Enter the credentials for the database this platform will use.</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <TextInput label="Host"     value={pg.host}     onChange={v => setPg(p => ({ ...p, host: v }))}     placeholder="postgres" />
          <TextInput label="Port"     value={pg.port}     onChange={v => setPg(p => ({ ...p, port: v }))}     placeholder="5432" type="number" />
          <TextInput label="Username" value={pg.user}     onChange={v => setPg(p => ({ ...p, user: v }))}     placeholder="baseline" />
          <TextInput label="Database" value={pg.db}       onChange={v => setPg(p => ({ ...p, db: v }))}       placeholder="baseline" />
        </div>
        <div className="mb-4">
          <SecretInput label="Password" value={pg.password} onChange={v => setPg(p => ({ ...p, password: v }))} placeholder="••••••••" />
        </div>

        <div className="flex gap-3 mb-4">
          <button onClick={handleTestPg} disabled={pgTesting || !pg.host || !pg.user || !pg.db}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm hover:bg-muted/40 transition-colors disabled:opacity-50">
            <RefreshCw size={13} className={pgTesting ? 'animate-spin' : ''} />
            {pgTesting ? 'Testing…' : 'Test Connection'}
          </button>
        </div>
        <StatusBox ok={pgStatus.ok} message={pgStatus.message} />
        {navButtons(() => setStep(2), 'Next — Schema', pgStatus.ok !== true && !existingLoaded, () => setStep(0))}
      </>);

      // ── Step 2: Schema / migrations ──────────────────────────────────────
      case 2: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-indigo-500/10"><Layers className="text-indigo-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Database Schema</h2>
            <p className="text-sm text-muted-foreground">Check the schema version and apply any needed migrations.</p>
          </div>
        </div>

        <div className="flex gap-3 mb-4">
          <button onClick={handleCheckMigrations} disabled={migrLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm hover:bg-muted/40 transition-colors disabled:opacity-50">
            <RefreshCw size={13} className={migrLoading ? 'animate-spin' : ''} />
            {migrLoading ? 'Checking…' : 'Check Schema Version'}
          </button>
        </div>

        {migrations && (
          <div className="space-y-3 mb-4">
            <div className="bg-muted/30 rounded-lg p-4 text-sm space-y-1.5">
              <div className="flex justify-between gap-4"><span className="text-muted-foreground shrink-0">Current revision</span>
                {migrations.queryError
                  ? <span className="text-red-400 text-xs text-right">{migrations.queryError}</span>
                  : <code className="font-mono text-foreground">{migrations.current ?? '(none — fresh database)'}</code>}
              </div>
              <div className="flex justify-between"><span className="text-muted-foreground">Required revision</span><code className="font-mono text-foreground">{migrations.required}</code></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Status</span><span className={migrations.upToDate ? 'text-green-400 font-medium' : 'text-amber-400 font-medium'}>{migrations.upToDate ? '✓ Up to date' : migrations.queryError ? 'Cannot read DB' : 'Upgrade required'}</span></div>
            </div>

            {!migrations.upToDate && (
              <button onClick={handleApplyMigrations} disabled={migrApplying}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-500/90 text-sm font-medium transition-colors disabled:opacity-50">
                <ArrowUpCircle size={14} className={migrApplying ? 'animate-bounce' : ''} />
                {migrApplying ? 'Applying…' : `Apply Migrations (upgrade to ${migrations.required.slice(0, 8)}…)`}
              </button>
            )}
          </div>
        )}

        {migrLog.length > 0 && (
          <div className="bg-black/50 rounded-lg border border-border p-3 font-mono text-xs text-green-400 max-h-52 overflow-y-auto space-y-0.5 mb-4">
            {migrLog.map((line, i) => (
              <div key={i} className="leading-relaxed whitespace-pre-wrap">{line || '\u00a0'}</div>
            ))}
            {migrApplying && <div className="text-muted-foreground animate-pulse">▌</div>}
          </div>
        )}

        <StatusBox ok={migrStatus.ok} message={migrStatus.message} />
        {navButtons(
          () => setStep(3),
          'Next — Redis',
          migrations?.upToDate !== true,
          () => setStep(1)
        )}
      </>);

      // ── Step 3: Redis ────────────────────────────────────────────────────
      case 3: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-red-500/10"><Server className="text-red-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Redis Configuration</h2>
            <p className="text-sm text-muted-foreground">Redis is used for session caching and runtime configuration.</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <TextInput label="Host" value={rd.host} onChange={v => setRd(r => ({ ...r, host: v }))} placeholder="redis" />
          <TextInput label="Port" value={rd.port} onChange={v => setRd(r => ({ ...r, port: v }))} placeholder="6379" type="number" />
          <TextInput label="Database Index" value={rd.db} onChange={v => setRd(r => ({ ...r, db: v }))} placeholder="0" type="number" />
        </div>
        <div className="mb-4">
          <SecretInput label="Password (leave blank if not set)" value={rd.password} onChange={v => setRd(r => ({ ...r, password: v }))} placeholder="(optional)" />
        </div>

        <div className="flex gap-3 mb-4">
          <button onClick={handleTestRedis} disabled={rdTesting || !rd.host}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm hover:bg-muted/40 transition-colors disabled:opacity-50">
            <RefreshCw size={13} className={rdTesting ? 'animate-spin' : ''} />
            {rdTesting ? 'Testing…' : 'Test Connection'}
          </button>
        </div>
        <StatusBox ok={rdStatus.ok} message={rdStatus.message} />
        {navButtons(() => setStep(4), 'Next — Discord', rdStatus.ok !== true && !existingLoaded, () => setStep(2))}
      </>);

      // ── Step 4: Discord ──────────────────────────────────────────────────
      case 4: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-purple-500/10"><MessageCircle className="text-purple-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Discord & Authentication</h2>
            <p className="text-sm text-muted-foreground">These four credentials are required — without them users cannot log in.</p>
          </div>
        </div>

        <div className="space-y-5">
          {/* ── Required ── */}
          <div className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Required</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TextInput label="Client ID" value={discord.client_id} onChange={v => setDiscord(d => ({ ...d, client_id: v }))} placeholder="123456789012345678" />
              <SecretInput label="Client Secret" value={discord.client_secret} onChange={v => setDiscord(d => ({ ...d, client_secret: v }))} placeholder="••••••••••••••••••••••••" />
            </div>
            <SecretInput label="Bot Token" value={discord.bot_token} onChange={v => setDiscord(d => ({ ...d, bot_token: v }))} placeholder="MT…" />
            <div>
              <TextInput label="OAuth Redirect URI" value={discord.redirect_uri} onChange={v => setDiscord(d => ({ ...d, redirect_uri: v }))} placeholder="https://yourdomain.com/auth/callback" />
              <p className="text-xs text-muted-foreground mt-1">Must match exactly the Redirect URI you set in the Discord Developer Portal under OAuth2.</p>
            </div>
          </div>

          {/* ── Where to find these ── */}
          <div className="flex items-start gap-2 p-3 rounded-lg bg-muted/30 border border-border text-xs text-muted-foreground">
            <AlertTriangle size={13} className="mt-0.5 shrink-0 text-blue-400" />
            <span>
              Find all four values in the <strong className="text-foreground">Discord Developer Portal</strong> under
              your application → OAuth2. The Bot Token is under Bot → Token.
              Admin access settings (Developer Guild, Role) are configured on the next step.
            </span>
          </div>
        </div>
        {navButtons(
          () => setStep(5),
          'Next — Bot Identity',
          !existingLoaded && (!discord.client_id || !discord.client_secret || !discord.bot_token || !discord.redirect_uri),
          () => setStep(3)
        )}
      </>);

      // ── Step 5: Bot Identity ─────────────────────────────────────────────
      case 5: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-violet-500/10"><Bot className="text-violet-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Bot Identity</h2>
            <p className="text-sm text-muted-foreground">Set the bot's name now — everything else can be filled in later.</p>
          </div>
        </div>

        <div className="space-y-5">
          {/* ── Required ── */}
          <div className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Required</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <TextInput label="Bot Name" value={botId.name} onChange={v => setBotId(b => ({ ...b, name: v }))} placeholder="My Discord Bot" />
                <p className="text-xs text-muted-foreground mt-1">Shown in the dashboard header and landing page.</p>
              </div>
              <div>
                <TextInput label="Application Name" value={appCfg.app_name} onChange={v => setAppCfg(a => ({ ...a, app_name: v }))} placeholder="My Discord Bot" />
                <p className="text-xs text-muted-foreground mt-1">Shown in API responses and the browser tab title.</p>
              </div>
            </div>
          </div>

          {/* ── Optional ── */}
          <div className="pt-4 border-t border-border space-y-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Optional — can be updated any time in Settings</p>

            <p className="text-xs text-muted-foreground">
              The bot logo is automatically fetched from Discord using the bot token configured above.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <TextInput
                  label="Tagline (English)"
                  value={botId.tagline}
                  onChange={v => setBotId(b => ({ ...b, tagline: v }))}
                  placeholder="A short one-line description"
                />
              </div>
              <div>
                <TextInput
                  label="Tagline (Spanish)"
                  value={botId.tagline_es}
                  onChange={v => setBotId(b => ({ ...b, tagline_es: v }))}
                  placeholder="Una breve descripción en una línea"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Description (English)</label>
                <textarea
                  value={botId.description}
                  onChange={e => setBotId(b => ({ ...b, description: e.target.value }))}
                  placeholder="Explain what this bot does…"
                  rows={3}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary resize-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Description (Spanish)</label>
                <textarea
                  value={botId.description_es}
                  onChange={e => setBotId(b => ({ ...b, description_es: e.target.value }))}
                  placeholder="Explica qué hace este bot…"
                  rows={3}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary resize-none"
                />
              </div>
            </div>

            <div>
              <TextInput
                label="Bot Invite URL"
                value={botId.invite_url}
                onChange={v => setBotId(b => ({ ...b, invite_url: v }))}
                placeholder="https://discord.com/oauth2/authorize?client_id=…&permissions=…&scope=bot"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Optional — auto-generated from your Client ID if left blank. Generate a custom one in Discord Developer Portal → OAuth2 → URL Generator to specify exact permissions.
              </p>
            </div>
          </div>
        </div>
        {navButtons(
          () => setStep(6),
          'Next — Security & Optional Features',
          !existingLoaded && !botId.name,
          () => setStep(4)
        )}
      </>);

      // ── Step 6: Security + Optional features ─────────────────────────────
      case 6: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-green-500/10"><Settings2 className="text-green-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Security & Optional Features</h2>
            <p className="text-sm text-muted-foreground">One required security key, then three optional sections you can skip entirely.</p>
          </div>
        </div>

        <div className="space-y-5">
          {/* ── Required: secret key ── */}
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Required</p>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">API Secret Key</label>
              <div className="flex gap-2">
                <div className="flex-1">
                  <input type="password" value={appCfg.api_secret_key} onChange={e => setAppCfg(a => ({ ...a, api_secret_key: e.target.value }))} placeholder="At least 32 random characters"
                    className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary" />
                </div>
                <button onClick={() => setAppCfg(a => ({ ...a, api_secret_key: randomHex(32) }))}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border text-xs hover:bg-muted/40 transition-colors whitespace-nowrap">
                  <Shuffle size={12} /> Generate
                </button>
              </div>
              <p className="text-xs text-muted-foreground mt-1">Signs and verifies all session tokens. Use Generate — never reuse a password here.</p>
            </div>
          </div>

          {/* ── Optional: Platform admin access ── */}
          <div className="pt-4 border-t border-border space-y-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-1">Platform Admin Access <span className="normal-case font-normal tracking-normal text-muted-foreground/70">— optional</span></p>
              <p className="text-xs text-muted-foreground">
                Grants Level 5 (platform admin) access to Discord members who have a specific role in a specific server.
                Leave blank to configure later — you can still use direct Discord user IDs in the config page.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <TextInput label="Developer Guild ID" value={discord.guild_id} onChange={v => setDiscord(d => ({ ...d, guild_id: v }))} placeholder="Discord Server ID" />
                <p className="text-xs text-muted-foreground mt-1">The server where admin roles are assigned.</p>
              </div>
              <div>
                <TextInput label="Developer Role ID" value={discord.developer_role_id} onChange={v => setDiscord(d => ({ ...d, developer_role_id: v }))} placeholder="Role ID in that server" />
                <p className="text-xs text-muted-foreground mt-1">Members with this role get full platform access.</p>
              </div>
            </div>
          </div>

          {/* ── Optional: AI providers ── */}
          <div className="pt-4 border-t border-border space-y-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-1">AI Provider Keys <span className="normal-case font-normal tracking-normal text-muted-foreground/70">— all optional</span></p>
              <div className="flex items-start gap-2 p-3 rounded-lg bg-muted/30 border border-border text-xs text-muted-foreground">
                <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-400" />
                <span>
                  Your bot deploys and runs fully without any AI keys. Only add the keys for providers
                  you plan to use. You can add or change them later on the <strong className="text-foreground">System Configuration</strong> page.
                </span>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <SecretInput label="OpenAI API Key" value={appCfg.openai_api_key} onChange={v => setAppCfg(a => ({ ...a, openai_api_key: v }))} placeholder="sk-…" />
                <p className="text-xs text-muted-foreground mt-1">GPT-4o, o1, Whisper, DALL·E</p>
              </div>
              <div>
                <SecretInput label="Google Gemini API Key" value={appCfg.google_api_key} onChange={v => setAppCfg(a => ({ ...a, google_api_key: v }))} placeholder="AIza…" />
                <p className="text-xs text-muted-foreground mt-1">Gemini 2.x, Imagen, text-to-speech</p>
              </div>
              <div>
                <SecretInput label="Anthropic API Key" value={appCfg.anthropic_api_key} onChange={v => setAppCfg(a => ({ ...a, anthropic_api_key: v }))} placeholder="sk-ant-…" />
                <p className="text-xs text-muted-foreground mt-1">Claude 3.x / 4.x models</p>
              </div>
              <div>
                <SecretInput label="xAI API Key" value={appCfg.xai_api_key} onChange={v => setAppCfg(a => ({ ...a, xai_api_key: v }))} placeholder="xai-…" />
                <p className="text-xs text-muted-foreground mt-1">Grok models</p>
              </div>
            </div>
          </div>
        </div>
        {navButtons(() => setStep(7), 'Review & Save', !existingLoaded && !appCfg.api_secret_key, () => setStep(5))}
      </>);

      // ── Step 7: Review & save ────────────────────────────────────────────
      case 7: return card(<>
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-amber-500/10"><CheckCircle2 className="text-amber-500" size={22} /></div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Review & Save</h2>
            <p className="text-sm text-muted-foreground">All settings will be AES-encrypted and saved to the Docker volume.</p>
          </div>
        </div>

        {!saved ? (
          <>
            <div className="space-y-3 text-sm mb-6">
              {([
                // Infrastructure — all required
                ['PostgreSQL',           `${pg.user}@${pg.host}:${pg.port}/${pg.db}`],
                ['Redis',                `${rd.host}:${rd.port} db=${rd.db}`],
                // Discord — required
                ['Discord Client ID',    discord.client_id || '(not set)'],
                ['Discord Redirect URI', discord.redirect_uri || '(not set)'],
                // Identity — required name, rest optional
                ['Bot Name',             botId.name || '(not set)'],
                ['Application Name',     appCfg.app_name || '(not set)'],
                ['Tagline (EN)',          botId.tagline || '(none)'],
                ['Tagline (ES)',          botId.tagline_es || '(none)'],
                ['Logo',                 'Auto-fetched from Discord'],
                ['Invite URL',           botId.invite_url ? `${botId.invite_url.slice(0, 40)}…` : '(auto-generated from Client ID)'],
                // Security — required
                ['API Secret Key',       appCfg.api_secret_key ? '••••••••' : '(not set — required!)'],
                // Optional
                ['Platform Admin Guild', discord.guild_id || '(none — configure later)'],
                ['Platform Admin Role',  discord.developer_role_id || '(none — configure later)'],
                ['AI Keys',              [appCfg.openai_api_key && 'OpenAI', appCfg.google_api_key && 'Google', appCfg.anthropic_api_key && 'Anthropic', appCfg.xai_api_key && 'xAI'].filter(Boolean).join(', ') || 'None — bot runs without AI'],
              ] as [string, string][]).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between py-2 border-b border-border/40 last:border-0">
                  <span className="text-muted-foreground">{k}</span>
                  <code className="font-mono text-foreground text-xs">{v}</code>
                </div>
              ))}
            </div>

            {saveError && <div className="text-sm text-red-400 mb-4">{saveError}</div>}

            <div className="flex gap-3">
              <button onClick={() => setStep(6)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground transition-colors">
                <ChevronLeft size={14} /> Back
              </button>
              <button onClick={handleSave} disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-green-600 text-white hover:bg-green-600/90 text-sm font-medium transition-colors disabled:opacity-50">
                {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                {saving ? 'Encrypting & saving…' : 'Encrypt & Save Settings'}
              </button>
            </div>
          </>
        ) : (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-green-500/10 flex items-center justify-center mx-auto">
              <CheckCircle2 className="text-green-500" size={32} />
            </div>
            <div>
              <p className="text-lg font-semibold text-green-400 mb-2">Settings saved successfully!</p>
              <p className="text-sm text-muted-foreground">
                The platform needs to restart to load the new configuration.
                Docker will bring it back automatically.
              </p>
            </div>
            <button onClick={handleRestart} disabled={restarting}
              className="flex items-center gap-2 mx-auto px-6 py-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50">
              {restarting ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {restarting ? 'Restarting… (waiting for server to come back)' : 'Restart & Launch Platform'}
            </button>
          </div>
        )}
      </>);

      default: return null;
    }
  };

  if (!pageReady) {
    if (accessDenied === 'sign-in') return (
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="w-full max-w-sm text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/10 flex items-center justify-center mx-auto">
            <ShieldOff className="text-amber-500" size={28} />
          </div>
          <h2 className="text-xl font-bold text-foreground">Platform Configuration</h2>
          <p className="text-sm text-muted-foreground">
            Setup is complete. This area is restricted to platform administrators.
            Sign in to continue.
          </p>
          <a href="/" className="inline-flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors">
            Sign in
          </a>
        </div>
      </div>
    );

    if (accessDenied === 'forbidden') return (
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="w-full max-w-sm text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center mx-auto">
            <ShieldOff className="text-red-500" size={28} />
          </div>
          <h2 className="text-xl font-bold text-foreground">Access Denied</h2>
          <p className="text-sm text-muted-foreground">
            Platform administrator access (Level 5) is required to access this page.
          </p>
          <a href="/" className="inline-flex items-center gap-2 px-5 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground transition-colors">
            Back to dashboard
          </a>
        </div>
      </div>
    );

    if (accessDenied === 'error') return (
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">Unable to verify access. Check that the backend is running.</p>
      </div>
    );

    // Still loading
    return (
      <div className="flex-1 flex items-center justify-center">
        <RefreshCw className="animate-spin text-muted-foreground" size={20} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 py-12">
      <div className="w-full max-w-2xl">
        {/* Title bar */}
        <div className="text-center mb-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-1">First-Time Setup</p>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent">
            Platform Configuration Wizard
          </h1>
        </div>

        <StepIndicator current={step} />
        {renderStep()}

        {/* Security note */}
        <p className="text-center text-xs text-muted-foreground mt-6 flex items-center justify-center gap-1.5">
          <Lock size={11} />
          All settings are encrypted with AES-256 (Fernet) before being written to disk.
        </p>
      </div>
    </div>
  );
}
