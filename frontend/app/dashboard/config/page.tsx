'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  Settings2, RefreshCw, Save, Trash2, AlertTriangle, CheckCircle2,
  Eye, EyeOff, Zap, Lock, Info, Key, Database
} from 'lucide-react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { APP_CATEGORIES, DYNAMIC_KEYS } from '@/config/settings-definitions';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface SettingEntry {
  key: string;
  friendly_name: string;
  description: string;
  category: string;
  type: 'string' | 'boolean' | 'integer' | 'select';
  is_dynamic: boolean;
  is_secret: boolean;
  possible_values?: [string, string][] | null;
  default?: string | null;
  effective_value?: string | null;
  db_override?: string | null;
  env_value?: string | null;
  source?: string;
  requires_restart_note?: string | null;
}

interface SettingsResponse {
  categories: Record<string, string>;
  settings: Record<string, SettingEntry[]>;
}

interface ApiKeyEntry {
  friendly_name: string;
  description: string;
  is_set: boolean;
  masked_value: string | null;
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------
const TABS = [
  { key: 'general',      label: 'General' },
  { key: 'bot_identity', label: 'Bot Identity' },
  { key: 'discord',      label: 'Discord' },
  { key: 'api',          label: 'API & Security' },
  { key: 'llm',          label: 'LLM / AI' },
  { key: 'rate_limit',   label: 'Rate Limits' },
  { key: 'features',     label: 'Feature Flags' },
  { key: 'frontend',     label: 'Frontend' },
  { key: 'database',     label: 'Database' },
  { key: 'api_keys',     label: 'API Keys', icon: Key },
] as const;

type TabKey = typeof TABS[number]['key'];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Badge({ label, variant }: { label: string; variant: 'dynamic' | 'static' | 'secret' | 'source' }) {
  const cls: Record<string, string> = {
    dynamic: 'bg-green-500/10 text-green-400 border-green-500/30',
    static:  'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
    secret:  'bg-red-500/10 text-red-400 border-red-500/30',
    source:  'bg-blue-500/10 text-blue-400 border-blue-500/30',
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls[variant]}`}>
      {variant === 'dynamic' && <Zap size={10} className="mr-1" />}
      {variant === 'static'  && <Lock size={10} className="mr-1" />}
      {label}
    </span>
  );
}

function SettingInput({
  setting,
  value,
  onChange,
  showSecret,
  onToggleSecret,
  modelOptions,
}: {
  setting: SettingEntry;
  value: string;
  onChange: (v: string) => void;
  showSecret: boolean;
  onToggleSecret: () => void;
  modelOptions?: string[];
}) {
  const base = 'w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-colors';

  // Default-model picker: a datalist gives a live dropdown of the selected
  // provider's models while still allowing a custom/unlisted model id. Fed by
  // GET /llm/models for the currently selected LLM_DEFAULT_PROVIDER.
  if (setting.key === 'LLM_DEFAULT_MODEL') {
    return (
      <>
        <input
          list="llm-default-model-options"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="(leave blank for the provider's default)"
          className={base}
        />
        <datalist id="llm-default-model-options">
          {(modelOptions ?? []).map(m => <option key={m} value={m} />)}
        </datalist>
      </>
    );
  }

  if (setting.type === 'boolean') {
    return (
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onChange(value === 'true' ? 'false' : 'true')}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            value === 'true' ? 'bg-green-500' : 'bg-muted-foreground/30'
          }`}
        >
          <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
            value === 'true' ? 'translate-x-6' : 'translate-x-1'
          }`} />
        </button>
        <span className="text-sm text-muted-foreground">{value === 'true' ? 'Enabled' : 'Disabled'}</span>
      </div>
    );
  }

  if (setting.type === 'select' && setting.possible_values) {
    return (
      <select value={value} onChange={e => onChange(e.target.value)} className={base}>
        {setting.possible_values.map(([v, label]) => (
          <option key={v} value={v}>{label}</option>
        ))}
      </select>
    );
  }

  if (setting.is_secret) {
    return (
      <div className="relative">
        <input
          type={showSecret ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          className={`${base} pr-10`}
          placeholder="(secret)"
        />
        <button
          type="button"
          onClick={onToggleSecret}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        >
          {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    );
  }

  return (
    <input
      type={setting.type === 'integer' ? 'number' : 'text'}
      value={value}
      onChange={e => onChange(e.target.value)}
      className={base}
    />
  );
}

function SettingRow({
  s,
  catKey,
  edits,
  showSecrets,
  onEdit,
  onToggleSecret,
  onRevert,
  modelOptions,
}: {
  s: SettingEntry;
  catKey: string;
  edits: Record<string, string>;
  showSecrets: Record<string, boolean>;
  onEdit: (key: string, value: string) => void;
  onToggleSecret: (key: string) => void;
  onRevert: (key: string) => void;
  modelOptions?: string[];
}) {
  const currentVal = edits[s.key] ?? s.effective_value ?? s.default ?? '';
  const isEdited   = edits[s.key] !== undefined;
  const hasOverride = s.source === 'database';

  return (
    <div className={`px-6 py-5 ${isEdited ? 'bg-primary/5' : ''}`}>
      <div className="flex flex-col md:flex-row md:items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-medium text-foreground text-sm">{s.friendly_name}</span>
            <code className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded font-mono">{s.key}</code>
            {s.is_dynamic
              ? <Badge label="Dynamic" variant="dynamic" />
              : <Badge label="Requires restart" variant="static" />
            }
            {s.is_secret && <Badge label="Secret" variant="secret" />}
            {hasOverride && <Badge label={`Override (${s.source})`} variant="source" />}
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed mb-3">{s.description}</p>
          {catKey !== 'frontend' ? (
            <SettingInput
              setting={s}
              value={currentVal}
              onChange={v => onEdit(s.key, v)}
              showSecret={showSecrets[s.key] ?? false}
              onToggleSecret={() => onToggleSecret(s.key)}
              modelOptions={modelOptions}
            />
          ) : (
            <div className="flex items-center gap-2 p-2 bg-muted/30 rounded-lg border border-border/50">
              <Info size={12} className="text-muted-foreground shrink-0" />
              <span className="text-xs text-muted-foreground">
                Frontend build-time variable. Current value:{' '}
                <code className="font-mono">{s.effective_value ?? s.default ?? '(not set)'}</code>
              </span>
            </div>
          )}
          {s.source && (
            <p className="text-xs text-muted-foreground mt-1">
              Source: <span className="font-medium capitalize">{s.source}</span>
              {s.default && ` · Default: ${s.is_secret ? '****' : s.default}`}
            </p>
          )}
          {!s.is_dynamic && s.requires_restart_note && (
            <p className="text-xs text-amber-600/80 dark:text-amber-400/80 mt-1 flex items-center gap-1">
              <Lock size={10} />
              {s.requires_restart_note}
            </p>
          )}
        </div>
        {hasOverride && (
          <button
            type="button"
            onClick={() => onRevert(s.key)}
            className="shrink-0 flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border text-xs text-muted-foreground hover:text-destructive hover:border-destructive/50 transition-colors"
            title="Revert to environment default"
          >
            <Trash2 size={12} />
            Revert
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// API Keys tab
// ---------------------------------------------------------------------------

function ApiKeysTab() {
  const [keys, setKeys]           = useState<Record<string, ApiKeyEntry> | null>(null);
  const [edits, setEdits]         = useState<Record<string, string>>({});
  const [showKey, setShowKey]     = useState<Record<string, boolean>>({});
  const [encKey, setEncKey]       = useState('');
  const [showEncKey, setShowEncKey] = useState(false);
  const [saving, setSaving]       = useState(false);
  const [message, setMessage]     = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiClient.getApiKeys();
      setKeys(data);
    } catch {
      setMessage({ type: 'error', text: 'Failed to load API keys.' });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    if (Object.keys(edits).length === 0) {
      setMessage({ type: 'warning', text: 'No changes to save.' });
      return;
    }
    if (!encKey.trim()) {
      setMessage({ type: 'error', text: 'Encryption key is required to save changes.' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const res = await apiClient.updateApiKeys(edits, encKey.trim());
      setMessage({ type: 'success', text: res.message });
      setEdits({});
      setEncKey('');
      await load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setMessage({
        type: 'error',
        text: status === 401
          ? 'Encryption key is incorrect.'
          : 'Failed to update API keys.',
      });
    } finally {
      setSaving(false);
    }
  };

  const base = 'w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-colors pr-10';

  if (!keys) {
    return <div className="flex justify-center py-12"><div className="w-6 h-6 border-4 border-primary/30 border-t-primary rounded-full animate-spin" /></div>;
  }

  const hasEdits = Object.keys(edits).length > 0;
  const canSave  = hasEdits && encKey.trim().length > 0;

  return (
    <div className="space-y-6">
      {/* Encryption key gate */}
      <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Lock size={14} className="text-amber-600 dark:text-amber-400 shrink-0" />
          <p className="text-sm font-medium text-amber-700 dark:text-amber-300">Encryption Key Required</p>
        </div>
        <p className="text-xs text-muted-foreground">
          API keys are stored in an encrypted file. To write changes you must supply the encryption
          key — it is sent directly to the server and used only for this operation.
          The server never uses its own copy of the key for writes.
        </p>
        <div className="relative">
          <input
            type={showEncKey ? 'text' : 'password'}
            value={encKey}
            onChange={e => setEncKey(e.target.value)}
            placeholder="Enter encryption key…"
            className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-amber-600/50 focus:border-amber-600/50 transition-colors pr-10"
          />
          <button
            type="button"
            onClick={() => setShowEncKey(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showEncKey ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>

      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Leave a key field blank to keep its current value unchanged. Changes take effect after a server restart.
        </p>
        <button
          onClick={handleSave}
          disabled={saving || !canSave}
          className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50"
        >
          <Save size={14} />
          {saving ? 'Saving…' : `Save${hasEdits ? ` (${Object.keys(edits).length})` : ''}`}
        </button>
      </div>

      {message && (
        <div className={`flex items-start gap-3 p-4 rounded-lg border text-sm ${
          message.type === 'success' ? 'bg-green-500/10 border-green-500/30 text-green-400' :
          message.type === 'warning' ? 'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400' :
          'bg-destructive/10 border-destructive/30 text-destructive'
        }`}>
          {message.type === 'success' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> :
           <AlertTriangle size={16} className="mt-0.5 shrink-0" />}
          <span>{message.text}</span>
        </div>
      )}

      <div className="bg-card border border-border rounded-xl divide-y divide-border/50">
        {Object.entries(keys).map(([key, entry]) => {
          const editValue  = edits[key] ?? '';
          const isEdited   = edits[key] !== undefined;
          const isVisible  = showKey[key] ?? false;

          return (
            <div key={key} className={`px-6 py-5 ${isEdited ? 'bg-primary/5' : ''}`}>
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span className="font-medium text-foreground text-sm">{entry.friendly_name}</span>
                <code className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded font-mono">{key}</code>
                <Badge label="Secret" variant="secret" />
                <Badge label="Requires restart" variant="static" />
                {entry.is_set && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border bg-green-500/10 text-green-400 border-green-500/30">
                    Set
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mb-3">{entry.description}</p>
              <div className="relative">
                <input
                  type={isVisible ? 'text' : 'password'}
                  value={editValue}
                  onChange={e => setEdits(prev => ({ ...prev, [key]: e.target.value }))}
                  className={base}
                  placeholder={entry.masked_value ?? 'Enter new value…'}
                />
                <button
                  type="button"
                  onClick={() => setShowKey(prev => ({ ...prev, [key]: !prev[key] }))}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {isVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Current: {entry.is_set ? (entry.masked_value ?? '****') : <span className="text-amber-600/80 dark:text-amber-400/80">Not set</span>}
              </p>
            </div>
          );
        })}
      </div>

      {hasEdits && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-card border border-border rounded-xl shadow-xl px-5 py-3">
          <span className="text-sm text-muted-foreground">
            {encKey.trim() ? '' : <Lock size={12} className="inline mr-1 text-amber-600 dark:text-amber-400" />}
            {Object.keys(edits).length} unsaved change{Object.keys(edits).length !== 1 ? 's' : ''}
            {!encKey.trim() && <span className="text-amber-600/80 dark:text-amber-400/80 ml-1">— enter key above</span>}
          </span>
          <button
            onClick={handleSave}
            disabled={saving || !canSave}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Database settings tab
// ---------------------------------------------------------------------------

function DatabaseTab() {
  const [data, setData]       = useState<SettingsResponse | null>(null);
  const [edits, setEdits]     = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [saving, setSaving]   = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.getDatabaseSettings();
      setData(res);
    } catch {
      setMessage({ type: 'error', text: 'Failed to load database settings.' });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    const updates = Object.entries(edits).map(([key, value]) => ({ key, value }));
    if (updates.length === 0) { setMessage({ type: 'warning', text: 'No changes to save.' }); return; }
    setSaving(true);
    setMessage(null);
    try {
      const res = await apiClient.updateConfigSettings(updates);
      setMessage({ type: res.restart_required ? 'warning' : 'success', text: res.message || 'Settings saved.' });
      setEdits({});
      await load();
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings.' });
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = async (key: string) => {
    try {
      await apiClient.deleteConfigOverride(key);
      setMessage({ type: 'success', text: `${key} reverted to environment default.` });
      await load();
    } catch {
      setMessage({ type: 'error', text: `Failed to revert ${key}.` });
    }
  };

  if (!data) return <div className="flex justify-center py-12"><div className="w-6 h-6 border-4 border-primary/30 border-t-primary rounded-full animate-spin" /></div>;

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Database connection settings. All require a server restart to take effect.
        </p>
        <button
          onClick={handleSave}
          disabled={saving || !hasEdits}
          className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50"
        >
          <Save size={14} />
          {saving ? 'Saving…' : `Save${hasEdits ? ` (${Object.keys(edits).length})` : ''}`}
        </button>
      </div>

      {message && (
        <div className={`flex items-start gap-3 p-4 rounded-lg border text-sm ${
          message.type === 'success' ? 'bg-green-500/10 border-green-500/30 text-green-400' :
          message.type === 'warning' ? 'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400' :
          'bg-destructive/10 border-destructive/30 text-destructive'
        }`}>
          {message.type === 'success' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> :
           <AlertTriangle size={16} className="mt-0.5 shrink-0" />}
          <span>{message.text}</span>
        </div>
      )}

      {Object.entries(data.categories).map(([catKey, catLabel]) => {
        const catSettings = data.settings[catKey] ?? [];
        if (catSettings.length === 0) return null;
        return (
          <div key={catKey} className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="flex items-center gap-2 px-6 py-4 border-b border-border">
              <Database size={16} className="text-muted-foreground" />
              <h3 className="text-base font-semibold text-foreground">{catLabel}</h3>
              <span className="text-xs text-muted-foreground ml-auto">{catSettings.length} setting{catSettings.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="divide-y divide-border/50">
              {catSettings.map((s: SettingEntry) => (
                <SettingRow
                  key={s.key}
                  s={s}
                  catKey={catKey}
                  edits={edits}
                  showSecrets={showSecrets}
                  onEdit={(key, value) => setEdits(prev => ({ ...prev, [key]: value }))}
                  onToggleSecret={key => setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }))}
                  onRevert={handleRevert}
                />
              ))}
            </div>
          </div>
        );
      })}

      {hasEdits && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-card border border-border rounded-xl shadow-xl px-5 py-3">
          <span className="text-sm text-muted-foreground">{Object.keys(edits).length} unsaved change{Object.keys(edits).length !== 1 ? 's' : ''}</span>
          <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50">
            <Save size={14} />
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function SystemConfigPage() {
  const [data, setData]             = useState<SettingsResponse | null>(null);
  const [loading, setLoading]       = useState(true);
  const [saving, setSaving]         = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage]       = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);
  const [edits, setEdits]           = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [activeTab, setActiveTab]   = useState<TabKey>('general');
  const [models, setModels]         = useState<Record<string, string[]>>({});

  // Available models per provider, for the Default Model dropdown.
  useEffect(() => {
    apiClient.getLLMModels().then(setModels).catch(() => setModels({}));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.getConfigSettings();
      setData(res);
    } catch {
      setMessage({ type: 'error', text: 'Failed to load configuration. Access denied or backend unavailable.' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleEdit = (key: string, value: string) => {
    setEdits(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    const updates = Object.entries(edits).map(([key, value]) => ({ key, value }));
    if (updates.length === 0) {
      setMessage({ type: 'warning', text: 'No changes to save.' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const res = await apiClient.updateConfigSettings(updates);
      setMessage({
        type: res.restart_required ? 'warning' : 'success',
        text: res.message || 'Settings saved.',
      });
      setEdits({});
      await load();
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings.' });
    } finally {
      setSaving(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setMessage(null);
    try {
      const res = await apiClient.refreshDynamicSettings();
      setMessage({ type: 'success', text: `Dynamic settings refreshed. ${res.count} setting(s) pushed to runtime.` });
    } catch {
      setMessage({ type: 'error', text: 'Failed to refresh settings.' });
    } finally {
      setRefreshing(false);
    }
  };

  const handleRevert = async (key: string) => {
    try {
      await apiClient.deleteConfigOverride(key);
      setMessage({ type: 'success', text: `${key} reverted to environment default.` });
      await load();
    } catch {
      setMessage({ type: 'error', text: `Failed to revert ${key}.` });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-muted-foreground animate-pulse">Loading configuration...</p>
        </div>
      </div>
    );
  }

  const settingsByCategory = data?.settings ?? {};
  const hasEdits = Object.keys(edits).length > 0;

  // Settings for the currently active non-special tab
  const activeSettings: SettingEntry[] = activeTab !== 'database' && activeTab !== 'api_keys'
    ? (settingsByCategory[activeTab] ?? [])
    : [];

  // Currently-selected default provider (edited value wins), used to populate the
  // Default Model dropdown with that provider's models.
  const llmProvider =
    edits['LLM_DEFAULT_PROVIDER']
    ?? activeSettings.find(x => x.key === 'LLM_DEFAULT_PROVIDER')?.effective_value
    ?? activeSettings.find(x => x.key === 'LLM_DEFAULT_PROVIDER')?.default
    ?? 'openai';
  const llmModelOptions = models[llmProvider] ?? [];

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="p-2 rounded-lg bg-red-500/10">
              <Settings2 className="text-red-500" size={22} />
            </div>
            <h1 className="text-3xl font-bold text-foreground">System Configuration</h1>
          </div>
          <p className="text-muted-foreground">
            Manage all framework settings. Dynamic settings apply immediately; static settings require a server restart.
          </p>
        </div>
        {activeTab !== 'database' && activeTab !== 'api_keys' && (
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border bg-background hover:bg-muted/40 text-sm font-medium transition-colors disabled:opacity-50"
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              Refresh Dynamic
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !hasEdits}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50"
            >
              <Save size={14} />
              {saving ? 'Saving…' : `Save Changes${hasEdits ? ` (${Object.keys(edits).length})` : ''}`}
            </button>
          </div>
        )}
      </div>

      {/* Legend (only for app settings tabs) */}
      {activeTab !== 'database' && activeTab !== 'api_keys' && (
        <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
          <span className="flex items-center gap-1"><Zap size={12} className="text-green-400" /> Dynamic — applied at runtime without restart</span>
          <span className="flex items-center gap-1"><Lock size={12} className="text-amber-600 dark:text-amber-400" /> Static — requires server restart</span>
        </div>
      )}

      {/* Global message (for app settings tabs) */}
      {message && activeTab !== 'database' && activeTab !== 'api_keys' && (
        <div className={`flex items-start gap-3 p-4 rounded-lg border text-sm ${
          message.type === 'success' ? 'bg-green-500/10 border-green-500/30 text-green-400' :
          message.type === 'warning' ? 'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400' :
          'bg-destructive/10 border-destructive/30 text-destructive'
        }`}>
          {message.type === 'success' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> :
           <AlertTriangle size={16} className="mt-0.5 shrink-0" />}
          <span>{message.text}</span>
        </div>
      )}

      {/* Tab bar */}
      <div className="border-b border-border overflow-x-auto">
        <nav className="flex gap-1 -mb-px min-w-max">
          {TABS.map(tab => (
            <button
              key={tab.key}
              type="button"
              onClick={() => { setActiveTab(tab.key); setMessage(null); }}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex items-center gap-1.5 ${
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              }`}
            >
              {'icon' in tab && tab.icon && <tab.icon size={14} />}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'api_keys' ? (
        <ApiKeysTab />
      ) : activeTab === 'database' ? (
        <DatabaseTab />
      ) : (
        <div className="space-y-0 bg-card border border-border rounded-xl overflow-hidden">
          {activeSettings.length === 0 ? (
            <div className="px-6 py-12 text-center text-muted-foreground text-sm">
              No settings in this category.
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              {activeSettings.map((s: SettingEntry) => (
                <SettingRow
                  key={s.key}
                  s={s}
                  catKey={activeTab}
                  edits={edits}
                  showSecrets={showSecrets}
                  onEdit={handleEdit}
                  onToggleSecret={key => setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }))}
                  onRevert={handleRevert}
                  modelOptions={s.key === 'LLM_DEFAULT_MODEL' ? llmModelOptions : undefined}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sticky save bar for app settings tabs */}
      {hasEdits && activeTab !== 'database' && activeTab !== 'api_keys' && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-card border border-border rounded-xl shadow-xl px-5 py-3">
          <span className="text-sm text-muted-foreground">{Object.keys(edits).length} unsaved change{Object.keys(edits).length !== 1 ? 's' : ''}</span>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

export default withPermission(SystemConfigPage, PermissionLevel.DEVELOPER);
