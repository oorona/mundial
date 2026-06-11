'use client';

/**
 * LLM Configs — Developer Dashboard (Level 5)
 *
 * Provides a full editor for the framework's two file-based stores:
 *
 * 1. **Output Schemas** (backend/schemas/)
 *    JSON Schema definitions that the structured-output endpoint can load by ID.
 *    Bots pass `schema_id` to POST /api/v1/gemini/structured instead of inlining
 *    the schema on every call.
 *
 * 2. **Function Sets** (backend/functions/)
 *    JSON bundles of FunctionDeclaration objects that the function-calling endpoint
 *    loads by ID. Bots pass `function_set_id` to POST /api/v1/gemini/function-calling.
 *
 * 3. **LLM Call Logs**
 *    Recent call records from Redis (7-day TTL): prompt preview, output preview,
 *    token counts, latency, and estimated cost.
 *
 * HOW TO ADD A CUSTOM FUNCTION SET:
 * -----------------------------------
 * 1. Click "New Function Set" and give it a unique ID (e.g. my_bot_tools).
 * 2. Paste or write the JSON. Each entry in "functions" must have:
 *    - name: snake_case identifier
 *    - description: detailed string (used by the model to decide when to call)
 *    - parameters: JSON Schema with "type": "object" and "properties"
 * 3. Save. The file is written to backend/functions/{id}.json.
 * 4. In your bot command, pass "function_set_id": "my_bot_tools" when calling
 *    POST /api/v1/gemini/function-calling.
 * 5. Implement the execution logic in your bot; return results via "function_results".
 *
 * See: https://ai.google.dev/gemini-api/docs/function-calling
 */

import { useState, useEffect, useCallback } from 'react';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { apiClient } from '@/app/api-client';

type Tab = 'schemas' | 'functions' | 'logs' | 'try-structured' | 'try-tools' | 'plugin-prompts';

interface SchemaEntry {
  id: string;
  name: string;
  description: string;
  example_prompt: string;
  properties?: string[];
}

interface FunctionSetEntry {
  id: string;
  name: string;
  description: string;
  function_count: number;
  function_names: string[];
  example_prompts: string[];
}

interface LogEntry {
  id: string;
  endpoint: string;
  model: string;
  user_id: string;
  prompt_preview: string;
  output_preview: string;
  prompt_tokens: number;
  completion_tokens: number;
  thoughts_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  latency_ms: number;
  timestamp: string;
  schema_id?: string;
  function_set_id?: string;
  schema_name?: string;
  scenario?: string;
}

const SCHEMA_TEMPLATE = JSON.stringify({
  id: "my_schema",
  name: "My Schema",
  description: "What this schema extracts",
  example_prompt: "Extract data from: ...",
  schema: {
    type: "object",
    title: "MySchema",
    properties: {
      field_one: { type: "string", description: "Description of field_one" },
      field_two: { type: "integer", description: "Description of field_two" }
    },
    required: ["field_one"]
  }
}, null, 2);

const FUNCTION_SET_TEMPLATE = JSON.stringify({
  id: "my_bot_tools",
  name: "My Bot Tools",
  description: "Functions for my bot",
  example_prompts: ["Do something useful"],
  functions: [
    {
      name: "my_function",
      description: "What this function does and when the model should call it",
      parameters: {
        type: "object",
        properties: {
          param_one: { type: "string", description: "Description of param_one" }
        },
        required: ["param_one"]
      }
    }
  ]
}, null, 2);

function LLMConfigsPage() {
  const [tab, setTab] = useState<Tab>('schemas');

  // Schemas
  const [schemas, setSchemas] = useState<SchemaEntry[]>([]);
  const [schemasLoading, setSchemasLoading] = useState(true);
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null);
  const [schemaEditor, setSchemaEditor] = useState('');
  const [schemaEditorMode, setSchemaEditorMode] = useState<'view' | 'edit' | 'new'>('view');
  const [schemaJsonError, setSchemaJsonError] = useState('');

  // Function Sets
  const [functionSets, setFunctionSets] = useState<FunctionSetEntry[]>([]);
  const [fnSetsLoading, setFnSetsLoading] = useState(true);
  const [selectedFnSet, setSelectedFnSet] = useState<string | null>(null);
  const [fnEditor, setFnEditor] = useState('');
  const [fnEditorMode, setFnEditorMode] = useState<'view' | 'edit' | 'new'>('view');
  const [fnJsonError, setFnJsonError] = useState('');

  // Logs
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logFilter, setLogFilter] = useState({ endpoint: '', model: '' });
  const [logsTotal, setLogsTotal] = useState(0);

  // Plugin Prompts — three-level hierarchy: plugin → context → file
  const [promptPlugins, setPromptPlugins] = useState<Array<{ plugin_name: string; display_name: string; contexts: any[] }>>([]);
  const [promptsLoading, setPromptsLoading] = useState(false);
  // Which file is open in the editor
  const [selectedFile, setSelectedFile] = useState<{ plugin: string; context: string; file: string } | null>(null);
  const [promptEditor, setPromptEditor] = useState('');
  const [promptFileMeta, setPromptFileMeta] = useState<{ label: string; description: string } | null>(null);
  const [promptSaveMsg, setPromptSaveMsg] = useState('');
  const [promptSaving, setPromptSaving] = useState(false);
  // Which contexts are expanded in the sidebar
  const [expandedContexts, setExpandedContexts] = useState<Set<string>>(new Set());

  // Pending delete confirmations
  const [pendingDeleteSchema, setPendingDeleteSchema] = useState<string | null>(null);
  const [pendingDeleteFnSet, setPendingDeleteFnSet] = useState<string | null>(null);

  // Saving state
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  // ── Try Structured Output state ───────────────────────────────────────────
  const STRUCT_SCHEMAS = [
    { id: 'user_intent', label: 'User Intent', example: "Classify: 'Can someone help me set up the bot to log joins and leaves?'" },
    { id: 'discord_moderation_action', label: 'Moderation Action', example: "Analyze: 'Hey everyone, check out my giveaway at spam-link.net — win $1000 today!'" },
    { id: 'server_health_report', label: 'Server Health Report', example: 'Generate a health report for a server with 1200 members, 45 active daily, boost level 2.' },
  ];
  const [structSchemaId, setStructSchemaId] = useState(STRUCT_SCHEMAS[0].id);
  const [structPrompt, setStructPrompt] = useState(STRUCT_SCHEMAS[0].example);
  const [structResult, setStructResult] = useState<any>(null);
  const [structLoading, setStructLoading] = useState(false);
  const [structError, setStructError] = useState('');
  const [structShowRaw, setStructShowRaw] = useState(false);

  // ── Try Function Calling state ────────────────────────────────────────────
  const TOOL_SCENARIOS = [
    { id: 'weather', label: 'Weather', fns: 'get_current_weather, get_forecast', example: "What's the weather in Tokyo right now?" },
    { id: 'calculator', label: 'Calculator', fns: 'add, multiply, power', example: 'What is 7 raised to the power of 3?' },
    { id: 'discord_query', label: 'Discord Query', fns: 'get_member_count, get_server_info', example: 'How many members does this server have?' },
  ];
  const [toolScenario, setToolScenario] = useState(TOOL_SCENARIOS[0].id);
  const [toolPrompt, setToolPrompt] = useState(TOOL_SCENARIOS[0].example);
  const [toolResult, setToolResult] = useState<any>(null);
  const [toolLoading, setToolLoading] = useState(false);
  const [toolError, setToolError] = useState('');
  const [toolShowRaw, setToolShowRaw] = useState(false);

  // ── Load data ─────────────────────────────────────────────────────────────

  const loadSchemas = useCallback(async () => {
    setSchemasLoading(true);
    try {
      const data = await apiClient.listLlmSchemas();
      setSchemas(data.schemas || []);
    } catch {
      setSchemas([]);
    } finally {
      setSchemasLoading(false);
    }
  }, []);

  const loadFunctionSets = useCallback(async () => {
    setFnSetsLoading(true);
    try {
      const data = await apiClient.listLlmFunctionSets();
      setFunctionSets(data.function_sets || []);
    } catch {
      setFunctionSets([]);
    } finally {
      setFnSetsLoading(false);
    }
  }, []);

  const loadLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const data = await apiClient.getLlmLogs({
        limit: 100,
        endpoint: logFilter.endpoint || undefined,
        model: logFilter.model || undefined,
      });
      setLogs(data.logs || []);
      setLogsTotal(data.total_indexed || 0);
    } catch {
      setLogs([]);
    } finally {
      setLogsLoading(false);
    }
  }, [logFilter]);

  const loadPluginPrompts = useCallback(async () => {
    setPromptsLoading(true);
    try {
      const data = await apiClient.listPluginPrompts();
      setPromptPlugins(data.plugins || []);
    } catch {
      setPromptPlugins([]);
    } finally {
      setPromptsLoading(false);
    }
  }, []);

  const openPromptFile = async (plugin: string, context: string, file: string, meta: { label: string; description: string }) => {
    setSelectedFile({ plugin, context, file });
    setPromptFileMeta(meta);
    setPromptSaveMsg('');
    try {
      const data = await apiClient.getPromptFile(plugin, context, file);
      setPromptEditor(data.content);
    } catch {
      setPromptEditor('');
    }
  };

  const savePromptFile = async () => {
    if (!selectedFile) return;
    setPromptSaving(true);
    setPromptSaveMsg('');
    try {
      await apiClient.savePromptFile(selectedFile.plugin, selectedFile.context, selectedFile.file, promptEditor);
      setPromptSaveMsg('Saved.');
    } catch (e: any) {
      setPromptSaveMsg(e.message || 'Save failed');
    } finally {
      setPromptSaving(false);
    }
  };

  const resetPromptFile = async () => {
    if (!selectedFile) return;
    setPromptSaving(true);
    setPromptSaveMsg('');
    try {
      const data = await apiClient.resetPromptFile(selectedFile.plugin, selectedFile.context, selectedFile.file);
      setPromptEditor(data.content);
      setPromptSaveMsg('Reset to default.');
    } catch (e: any) {
      setPromptSaveMsg(e.message || 'Reset failed');
    } finally {
      setPromptSaving(false);
    }
  };

  const toggleContext = (key: string) => {
    setExpandedContexts(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  useEffect(() => { loadSchemas(); }, [loadSchemas]);
  useEffect(() => { loadFunctionSets(); }, [loadFunctionSets]);
  useEffect(() => { if (tab === 'logs') loadLogs(); }, [tab, loadLogs]);
  useEffect(() => { if (tab === 'plugin-prompts') loadPluginPrompts(); }, [tab, loadPluginPrompts]);

  // ── Schema editor handlers ────────────────────────────────────────────────

  const openSchema = async (id: string) => {
    setSelectedSchema(id);
    setSchemaEditorMode('edit');
    setSchemaJsonError('');
    try {
      const data = await apiClient.getLlmSchema(id);
      setSchemaEditor(JSON.stringify(data, null, 2));
    } catch {
      setSchemaEditor('{}');
    }
  };

  const saveSchema = async () => {
    setSchemaJsonError('');
    let parsed: any;
    try { parsed = JSON.parse(schemaEditor); } catch (e: any) {
      setSchemaJsonError('Invalid JSON: ' + e.message);
      return;
    }
    const id = parsed.id || selectedSchema;
    if (!id) { setSchemaJsonError('JSON must include an "id" field.'); return; }
    setSaving(true);
    setSaveMsg('');
    try {
      await apiClient.upsertLlmSchema(id, parsed);
      setSaveMsg('Saved.');
      setSelectedSchema(id);
      setSchemaEditorMode('edit');
      await loadSchemas();
    } catch (e: any) {
      setSchemaJsonError(e.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const deleteSchema = async (id: string) => {
    try {
      await apiClient.deleteLlmSchema(id);
      setPendingDeleteSchema(null);
      setSelectedSchema(null);
      setSchemaEditorMode('view');
      await loadSchemas();
    } catch (e: any) {
      setPendingDeleteSchema(null);
      setSchemaJsonError(e.message || 'Delete failed');
    }
  };

  // ── Function set editor handlers ──────────────────────────────────────────

  const openFnSet = async (id: string) => {
    setSelectedFnSet(id);
    setFnEditorMode('edit');
    setFnJsonError('');
    try {
      const data = await apiClient.getLlmFunctionSet(id);
      setFnEditor(JSON.stringify(data, null, 2));
    } catch {
      setFnEditor('{}');
    }
  };

  const saveFnSet = async () => {
    setFnJsonError('');
    let parsed: any;
    try { parsed = JSON.parse(fnEditor); } catch (e: any) {
      setFnJsonError('Invalid JSON: ' + e.message);
      return;
    }
    const id = parsed.id || selectedFnSet;
    if (!id) { setFnJsonError('JSON must include an "id" field.'); return; }
    setSaving(true);
    setSaveMsg('');
    try {
      await apiClient.upsertLlmFunctionSet(id, parsed);
      setSaveMsg('Saved.');
      setSelectedFnSet(id);
      setFnEditorMode('edit');
      await loadFunctionSets();
    } catch (e: any) {
      setFnJsonError(e.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const deleteFnSet = async (id: string) => {
    try {
      await apiClient.deleteLlmFunctionSet(id);
      setPendingDeleteFnSet(null);
      setSelectedFnSet(null);
      setFnEditorMode('view');
      await loadFunctionSets();
    } catch (e: any) {
      setPendingDeleteFnSet(null);
      setFnJsonError(e.message || 'Delete failed');
    }
  };

  // ── Shared helpers ────────────────────────────────────────────────────────

  const fmtCost = (v: number) => v < 0.000001 ? '$0.000000' : `$${v.toFixed(6)}`;
  const fmtMs = (v: number) => v < 1000 ? `${v.toFixed(0)}ms` : `${(v / 1000).toFixed(2)}s`;

  const endpointColor = (ep: string) => {
    const m: Record<string, string> = {
      generate: 'bg-blue-500/20 text-blue-600 dark:text-blue-300',
      structured: 'bg-purple-500/20 text-purple-600 dark:text-purple-300',
      function_calling: 'bg-green-500/20 text-green-600 dark:text-green-300',
      image: 'bg-orange-500/20 text-orange-600 dark:text-orange-300',
    };
    return m[ep] || 'bg-muted text-muted-foreground';
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      {/* Header */}
      <div className="mb-2 p-4 bg-violet-500/10 border border-violet-500/30 rounded-lg">
        <h1 className="text-2xl font-bold text-foreground mb-1">LLM Configs — Developer Tool</h1>
        <p className="text-muted-foreground text-sm">
          Manage output schemas and function sets used by Gemini API endpoints.
          All changes write directly to <code className="text-violet-600 dark:text-violet-400">backend/schemas/</code> and{' '}
          <code className="text-violet-600 dark:text-violet-400">backend/functions/</code>.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-border pb-0 flex-wrap">
        {([
          { id: 'schemas',        label: 'Output Schemas' },
          { id: 'functions',      label: 'Function Sets' },
          { id: 'plugin-prompts', label: 'Plugin Prompts' },
          { id: 'logs',           label: 'LLM Call Logs' },
          { id: 'try-structured', label: '▶ Try: Structured Output' },
          { id: 'try-tools',      label: '▶ Try: Function Calling' },
        ] as { id: Tab; label: string }[]).map(({ id, label }) => (
          <button
            key={id}
            onClick={() => { setTab(id); setSaveMsg(''); }}
            className={`px-5 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === id
                ? id.startsWith('try-')
                  ? 'bg-card text-green-600 dark:text-green-300 border border-b-0 border-green-600/50'
                  : 'bg-card text-foreground border border-b-0 border-border'
                : id.startsWith('try-')
                  ? 'text-green-600 hover:text-green-500'
                  : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Schemas Tab ── */}
      {tab === 'schemas' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Schema list */}
          <div className="lg:col-span-1 bg-card border border-border rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-foreground">Stored Schemas</h2>
              <button
                onClick={() => { setSchemaEditor(SCHEMA_TEMPLATE); setSchemaEditorMode('new'); setSelectedSchema(null); setSchemaJsonError(''); setSaveMsg(''); }}
                className="text-xs px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded"
              >+ New</button>
            </div>
            {schemasLoading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : schemas.length === 0 ? (
              <p className="text-muted-foreground text-sm">No schemas yet. Click "New" to create one.</p>
            ) : schemas.map(s => (
              <div
                key={s.id}
                onClick={() => { openSchema(s.id); setSaveMsg(''); }}
                className={`cursor-pointer rounded-lg p-3 border transition-colors ${
                  selectedSchema === s.id
                    ? 'border-blue-500 bg-blue-500/10'
                    : 'border-border hover:border-border/80 hover:bg-muted/50'
                }`}
              >
                <div className="font-medium text-foreground text-sm">{s.name}</div>
                <div className="text-xs text-muted-foreground font-mono mt-0.5">{s.id}</div>
                {s.properties && s.properties.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {s.properties.slice(0, 4).map(p => (
                      <span key={p} className="text-xs bg-muted px-1.5 py-0.5 rounded text-muted-foreground">{p}</span>
                    ))}
                    {s.properties.length > 4 && (
                      <span className="text-xs text-muted-foreground">+{s.properties.length - 4}</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Schema editor */}
          <div className="lg:col-span-2 bg-card border border-border rounded-lg p-4 space-y-3">
            {schemaEditorMode === 'view' ? (
              <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
                Select a schema or click "New" to start editing.
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold text-foreground">
                    {schemaEditorMode === 'new' ? 'New Schema' : `Editing: ${selectedSchema}`}
                  </h2>
                  <div className="flex gap-2">
                    {schemaEditorMode === 'edit' && selectedSchema && (
                      pendingDeleteSchema === selectedSchema ? (
                        <>
                          <span className="text-xs text-destructive self-center">Are you sure?</span>
                          <button
                            onClick={() => deleteSchema(selectedSchema)}
                            className="text-xs px-3 py-1 bg-destructive hover:bg-destructive/80 text-destructive-foreground rounded"
                          >Confirm Delete</button>
                          <button
                            onClick={() => setPendingDeleteSchema(null)}
                            className="text-xs px-3 py-1 bg-muted hover:bg-muted/80 text-foreground rounded"
                          >Cancel</button>
                        </>
                      ) : (
                        <button
                          onClick={() => setPendingDeleteSchema(selectedSchema)}
                          className="text-xs px-3 py-1 bg-destructive hover:bg-destructive/80 text-destructive-foreground rounded"
                        >Delete</button>
                      )
                    )}
                    <button
                      onClick={saveSchema}
                      disabled={saving}
                      className="text-xs px-4 py-1 bg-green-600 hover:bg-green-700 text-white rounded disabled:opacity-50"
                    >{saving ? 'Saving…' : 'Save'}</button>
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">
                  Edit the JSON below. The <code className="text-foreground">"schema"</code> field must be a valid JSON Schema.
                  The <code className="text-foreground">"id"</code> field sets the filename.
                  Reference this schema in API calls via <code className="text-foreground">schema_id: "{selectedSchema || 'your_id'}"</code>.
                </p>

                {schemaJsonError && (
                  <div className="p-2 bg-destructive/10 border border-destructive/30 rounded text-destructive text-xs">{schemaJsonError}</div>
                )}
                {saveMsg && (
                  <div className="p-2 bg-green-500/10 border border-green-500/30 rounded text-green-600 dark:text-green-400 text-xs">{saveMsg}</div>
                )}

                <textarea
                  value={schemaEditor}
                  onChange={e => setSchemaEditor(e.target.value)}
                  className="w-full h-96 px-4 py-3 bg-background border border-border rounded-lg font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                  spellCheck={false}
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Function Sets Tab ── */}
      {tab === 'functions' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Function set list */}
          <div className="lg:col-span-1 bg-card border border-border rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-foreground">Function Sets</h2>
              <button
                onClick={() => { setFnEditor(FUNCTION_SET_TEMPLATE); setFnEditorMode('new'); setSelectedFnSet(null); setFnJsonError(''); setSaveMsg(''); }}
                className="text-xs px-3 py-1 bg-green-600 hover:bg-green-700 text-white rounded"
              >+ New</button>
            </div>

            <div className="mb-3 p-3 bg-muted/50 border border-border rounded text-xs text-muted-foreground space-y-1">
              <p className="font-medium text-foreground">How to add functions:</p>
              <ol className="list-decimal list-inside space-y-1">
                <li>Click "New" and define your functions.</li>
                <li>Pass <code className="text-green-600 dark:text-green-400">function_set_id</code> to the function-calling endpoint.</li>
                <li>Execute calls in your bot and return results via <code className="text-green-600 dark:text-green-400">function_results</code>.</li>
              </ol>
            </div>

            {fnSetsLoading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : functionSets.length === 0 ? (
              <p className="text-muted-foreground text-sm">No function sets yet.</p>
            ) : functionSets.map(fs => (
              <div
                key={fs.id}
                onClick={() => { openFnSet(fs.id); setSaveMsg(''); }}
                className={`cursor-pointer rounded-lg p-3 border transition-colors ${
                  selectedFnSet === fs.id
                    ? 'border-green-500 bg-green-500/10'
                    : 'border-border hover:border-border/80 hover:bg-muted/50'
                }`}
              >
                <div className="font-medium text-foreground text-sm">{fs.name}</div>
                <div className="text-xs text-muted-foreground font-mono mt-0.5">{fs.id}</div>
                <div className="mt-1 text-xs text-muted-foreground">{fs.function_count} function{fs.function_count !== 1 ? 's' : ''}</div>
                {fs.function_names.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {fs.function_names.slice(0, 3).map(n => (
                      <span key={n} className="text-xs bg-muted px-1.5 py-0.5 rounded text-muted-foreground font-mono">{n}</span>
                    ))}
                    {fs.function_names.length > 3 && (
                      <span className="text-xs text-muted-foreground">+{fs.function_names.length - 3}</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Function set editor */}
          <div className="lg:col-span-2 bg-card border border-border rounded-lg p-4 space-y-3">
            {fnEditorMode === 'view' ? (
              <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
                Select a function set or click "New" to create one.
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold text-foreground">
                    {fnEditorMode === 'new' ? 'New Function Set' : `Editing: ${selectedFnSet}`}
                  </h2>
                  <div className="flex gap-2">
                    {fnEditorMode === 'edit' && selectedFnSet && (
                      pendingDeleteFnSet === selectedFnSet ? (
                        <>
                          <span className="text-xs text-destructive self-center">Are you sure?</span>
                          <button
                            onClick={() => deleteFnSet(selectedFnSet)}
                            className="text-xs px-3 py-1 bg-destructive hover:bg-destructive/80 text-destructive-foreground rounded"
                          >Confirm Delete</button>
                          <button
                            onClick={() => setPendingDeleteFnSet(null)}
                            className="text-xs px-3 py-1 bg-muted hover:bg-muted/80 text-foreground rounded"
                          >Cancel</button>
                        </>
                      ) : (
                        <button
                          onClick={() => setPendingDeleteFnSet(selectedFnSet)}
                          className="text-xs px-3 py-1 bg-destructive hover:bg-destructive/80 text-destructive-foreground rounded"
                        >Delete</button>
                      )
                    )}
                    <button
                      onClick={saveFnSet}
                      disabled={saving}
                      className="text-xs px-4 py-1 bg-green-600 hover:bg-green-700 text-white rounded disabled:opacity-50"
                    >{saving ? 'Saving…' : 'Save'}</button>
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">
                  Each function in <code className="text-foreground">"functions"</code> must have{' '}
                  <code className="text-foreground">name</code>,{' '}
                  <code className="text-foreground">description</code>, and{' '}
                  <code className="text-foreground">parameters</code> (JSON Schema).
                  Reference this set via <code className="text-foreground">function_set_id: "{selectedFnSet || 'your_id'}"</code>.
                </p>

                {fnJsonError && (
                  <div className="p-2 bg-destructive/10 border border-destructive/30 rounded text-destructive text-xs">{fnJsonError}</div>
                )}
                {saveMsg && (
                  <div className="p-2 bg-green-500/10 border border-green-500/30 rounded text-green-600 dark:text-green-400 text-xs">{saveMsg}</div>
                )}

                <textarea
                  value={fnEditor}
                  onChange={e => setFnEditor(e.target.value)}
                  className="w-full h-96 px-4 py-3 bg-background border border-border rounded-lg font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-green-500 resize-y"
                  spellCheck={false}
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* ── LLM Logs Tab ── */}
      {tab === 'logs' && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex gap-4 items-end flex-wrap">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Filter by endpoint</label>
              <select
                value={logFilter.endpoint}
                onChange={e => setLogFilter(f => ({ ...f, endpoint: e.target.value }))}
                className="px-3 py-1.5 bg-background border border-border rounded text-foreground text-sm focus:outline-none"
              >
                <option value="">All endpoints</option>
                <option value="generate">generate</option>
                <option value="structured">structured</option>
                <option value="function_calling">function_calling</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Filter by model</label>
              <input
                value={logFilter.model}
                onChange={e => setLogFilter(f => ({ ...f, model: e.target.value }))}
                placeholder="e.g. gemini-3.1-flash-lite-preview"
                className="px-3 py-1.5 bg-background border border-border rounded text-foreground text-sm focus:outline-none w-72"
              />
            </div>
            <button
              onClick={loadLogs}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm"
            >Refresh</button>
          </div>

          <div className="text-xs text-muted-foreground">
            Showing {logs.length} of {logsTotal} indexed entries (7-day rolling window)
          </div>

          {logsLoading ? (
            <div className="text-muted-foreground text-sm">Loading logs…</div>
          ) : logs.length === 0 ? (
            <div className="text-muted-foreground text-sm">No logs found. LLM call logs appear here after API calls are made.</div>
          ) : (
            <div className="space-y-2">
              {logs.map(log => (
                <div key={log.id} className="bg-card border border-border rounded-lg p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs px-2 py-0.5 rounded font-mono ${endpointColor(log.endpoint)}`}>
                        {log.endpoint}
                      </span>
                      <span className="text-xs text-muted-foreground font-mono">{log.model}</span>
                      {log.schema_id && (
                        <span className="text-xs bg-purple-500/20 text-purple-600 dark:text-purple-300 px-2 py-0.5 rounded font-mono">
                          schema: {log.schema_id}
                        </span>
                      )}
                      {log.function_set_id && (
                        <span className="text-xs bg-green-500/20 text-green-600 dark:text-green-300 px-2 py-0.5 rounded font-mono">
                          fns: {log.function_set_id}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString()}
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <p className="text-muted-foreground mb-1">Prompt preview</p>
                      <p className="text-foreground font-mono bg-muted rounded p-2 line-clamp-3 whitespace-pre-wrap break-all">
                        {log.prompt_preview || '—'}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground mb-1">Output preview</p>
                      <p className="text-foreground font-mono bg-muted rounded p-2 line-clamp-3 whitespace-pre-wrap break-all">
                        {log.output_preview || '—'}
                      </p>
                    </div>
                  </div>

                  <div className="mt-3 flex gap-6 text-xs text-muted-foreground flex-wrap">
                    <span>↑ {log.prompt_tokens.toLocaleString()} prompt</span>
                    <span>↓ {log.completion_tokens.toLocaleString()} completion</span>
                    {log.thoughts_tokens > 0 && <span>💭 {log.thoughts_tokens.toLocaleString()} thoughts</span>}
                    <span>= {log.total_tokens.toLocaleString()} total</span>
                    <span className="text-green-600 dark:text-green-400">{fmtCost(log.estimated_cost)}</span>
                    <span className="text-blue-600 dark:text-blue-400">{fmtMs(log.latency_ms)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Plugin Prompts Tab ── */}
      {tab === 'plugin-prompts' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Sidebar: plugin → context → file */}
          <div className="lg:col-span-1 bg-card border border-border rounded-lg p-4 space-y-4 overflow-y-auto max-h-[75vh]">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-foreground">Plugin Prompts</h2>
              <button onClick={loadPluginPrompts} className="text-xs text-muted-foreground hover:text-foreground underline">Refresh</button>
            </div>

            {promptsLoading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : promptPlugins.length === 0 ? (
              <div className="space-y-2 text-sm text-muted-foreground">
                <p>No plugin prompts registered yet.</p>
                <p className="text-xs">Install a plugin with <code className="text-violet-600 dark:text-violet-400">components.prompts = true</code> in its <code>plugin.json</code>.</p>
              </div>
            ) : promptPlugins.map(group => (
              <div key={group.plugin_name}>
                {/* Plugin header */}
                <div className="text-xs font-bold text-muted-foreground uppercase tracking-wide px-1 pb-1 pt-2 border-b border-border mb-2">
                  {group.display_name}
                  <span className="ml-1 font-mono font-normal normal-case">({group.plugin_name})</span>
                </div>

                {/* Contexts */}
                {(group.contexts || []).map((ctx: any) => {
                  const ctxKey = `${group.plugin_name}/${ctx.name}`;
                  const isExpanded = expandedContexts.has(ctxKey);
                  return (
                    <div key={ctxKey} className="mb-1">
                      {/* Context row — click to expand */}
                      <button
                        onClick={() => toggleContext(ctxKey)}
                        className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50 text-left transition-colors"
                      >
                        <span className={`text-xs transition-transform ${isExpanded ? 'rotate-90' : ''}`}>▶</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-foreground truncate">{ctx.label || ctx.name}</div>
                          <div className="text-xs font-mono text-muted-foreground">{ctx.name}/</div>
                        </div>
                      </button>

                      {/* Files within this context */}
                      {isExpanded && (
                        <div className="ml-4 mt-0.5 space-y-0.5">
                          {(ctx.files || []).map((f: any) => {
                            const isSelected = selectedFile?.plugin === group.plugin_name
                              && selectedFile?.context === ctx.name
                              && selectedFile?.file === f.name;
                            return (
                              <button
                                key={f.name}
                                onClick={() => openPromptFile(group.plugin_name, ctx.name, f.name, { label: f.label, description: f.description })}
                                className={`w-full flex items-center gap-2 px-3 py-2 rounded border text-left transition-colors ${
                                  isSelected
                                    ? 'border-violet-500 bg-violet-500/10 text-foreground'
                                    : 'border-transparent hover:border-border hover:bg-muted/40 text-muted-foreground hover:text-foreground'
                                }`}
                              >
                                <span className="text-xs">📄</span>
                                <div className="min-w-0">
                                  <div className="text-xs font-medium truncate">{f.label || f.name}</div>
                                  <div className="text-xs font-mono opacity-60">{f.name}.txt</div>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          {/* Editor panel */}
          <div className="lg:col-span-2 bg-card border border-border rounded-lg p-4 space-y-4">
            {!selectedFile ? (
              <div className="flex flex-col items-center justify-center h-72 text-center space-y-3 text-muted-foreground">
                <p className="text-sm">Select a file from the left to edit it.</p>
                <p className="text-xs max-w-sm">
                  Each context folder (e.g. <code className="text-violet-500">ticket_intake/</code>) groups the prompts for one purpose.
                  Files are saved to the host volume — the bot picks up changes on the next call, no restart needed.
                </p>
              </div>
            ) : (
              <>
                {/* Header */}
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-foreground">{promptFileMeta?.label || selectedFile.file}</h3>
                    <div className="text-xs font-mono text-muted-foreground mt-0.5 truncate">
                      {selectedFile.plugin} / {selectedFile.context} / {selectedFile.file}.txt
                    </div>
                    {promptFileMeta?.description && (
                      <p className="text-xs text-muted-foreground mt-1">{promptFileMeta.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {promptSaveMsg && (
                      <span className={`text-xs ${promptSaveMsg.includes('failed') || promptSaveMsg.includes('Failed') ? 'text-red-500' : 'text-green-600 dark:text-green-400'}`}>
                        {promptSaveMsg}
                      </span>
                    )}
                    <button
                      onClick={resetPromptFile}
                      disabled={promptSaving}
                      className="px-3 py-1.5 text-xs border border-border text-muted-foreground hover:border-red-500/50 hover:text-red-500 rounded transition-colors disabled:opacity-50"
                    >Reset to default</button>
                    <button
                      onClick={savePromptFile}
                      disabled={promptSaving}
                      className="px-4 py-1.5 text-xs bg-violet-600 hover:bg-violet-700 text-white rounded disabled:opacity-50"
                    >{promptSaving ? 'Saving…' : 'Save'}</button>
                  </div>
                </div>

                {/* Text editor */}
                <textarea
                  value={promptEditor}
                  onChange={e => { setPromptEditor(e.target.value); setPromptSaveMsg(''); }}
                  rows={22}
                  spellCheck={false}
                  className="w-full font-mono text-sm bg-background border border-border rounded p-3 text-foreground resize-y focus:outline-none focus:ring-1 focus:ring-violet-500"
                  placeholder="Prompt content…"
                />

                <p className="text-xs text-muted-foreground">
                  Saved to{' '}
                  <code className="text-violet-600 dark:text-violet-400">
                    ./data/prompts/{selectedFile.plugin}/{selectedFile.context}/{selectedFile.file}.txt
                  </code>{' '}
                  on the host. Bot reads this file on each call — no restart required.
                </p>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Try: Structured Output Tab ── */}
      {tab === 'try-structured' && (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Send a prompt and select a predefined schema — the LLM returns structured JSON conforming to that schema.
            Calls <code className="text-blue-600 dark:text-blue-400">POST /api/v1/llm/structured</code>. Rate-limited at 5/min.
          </p>

          {/* Schema picker */}
          <div className="grid grid-cols-3 gap-2">
            {STRUCT_SCHEMAS.map(s => (
              <button
                key={s.id}
                onClick={() => { setStructSchemaId(s.id); setStructPrompt(s.example); setStructResult(null); setStructError(''); }}
                className={`p-3 rounded border text-left transition-colors ${
                  structSchemaId === s.id
                    ? 'border-purple-500 bg-purple-500/10 text-purple-600 dark:text-purple-300'
                    : 'border-border bg-card text-muted-foreground hover:border-border/80 hover:bg-muted/50'
                }`}
              >
                <div className="font-medium text-sm">{s.label}</div>
                <div className="text-xs font-mono mt-0.5 opacity-60">{s.id}</div>
              </button>
            ))}
          </div>

          {/* Prompt */}
          <textarea
            value={structPrompt}
            onChange={e => setStructPrompt(e.target.value)}
            rows={3}
            placeholder="Enter your prompt…"
            className="w-full bg-background border border-border rounded-lg p-3 text-sm text-foreground focus:outline-none focus:border-purple-500 resize-y"
          />
          <button
            disabled={structLoading || !structPrompt.trim()}
            onClick={async () => {
              setStructLoading(true); setStructError(''); setStructResult(null);
              try {
                const data = await apiClient.llmStructured(structPrompt, structSchemaId, { provider: 'openai' });
                setStructResult(data);
              } catch (e: any) {
                setStructError(e?.response?.data?.detail || e.message || 'Request failed');
              } finally { setStructLoading(false); }
            }}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded text-sm font-medium text-white transition-colors"
          >
            {structLoading ? 'Generating structured output…' : 'Generate Structured Output'}
          </button>

          {structError && (
            <div className="p-3 bg-destructive/10 border border-destructive/30 rounded text-destructive text-sm">{structError}</div>
          )}
          {structResult && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs bg-green-500/20 text-green-600 dark:text-green-300 px-2 py-0.5 rounded font-bold">✓ OK</span>
                <span className="text-xs text-muted-foreground">schema: <span className="text-purple-600 dark:text-purple-400">{structResult.schema_name}</span></span>
              </div>
              <pre className="bg-muted p-4 rounded overflow-x-auto text-xs text-green-600 dark:text-green-400 max-h-72 overflow-y-auto">
                {JSON.stringify(structResult.output, null, 2)}
              </pre>
              <button onClick={() => setStructShowRaw(!structShowRaw)} className="text-xs text-muted-foreground hover:text-foreground underline">
                {structShowRaw ? 'Hide raw LLM response' : 'Show raw LLM response'}
              </button>
              {structShowRaw && (
                <div className="bg-muted p-3 rounded text-xs text-muted-foreground whitespace-pre-wrap max-h-40 overflow-y-auto">{structResult.raw_content}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Try: Function Calling Tab ── */}
      {tab === 'try-tools' && (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">
            The LLM selects a function, the backend executes it (mocked), then the LLM produces a final answer.
            Calls <code className="text-blue-600 dark:text-blue-400">POST /api/v1/llm/tools</code>. Rate-limited at 5/min.
          </p>

          {/* Scenario picker */}
          <div className="grid grid-cols-3 gap-2">
            {TOOL_SCENARIOS.map(s => (
              <button
                key={s.id}
                onClick={() => { setToolScenario(s.id); setToolPrompt(s.example); setToolResult(null); setToolError(''); }}
                className={`p-3 rounded border text-left transition-colors ${
                  toolScenario === s.id
                    ? 'border-orange-500 bg-orange-500/10 text-orange-600 dark:text-orange-300'
                    : 'border-border bg-card text-muted-foreground hover:border-border/80 hover:bg-muted/50'
                }`}
              >
                <div className="font-medium text-sm">{s.label}</div>
                <div className="text-xs font-mono mt-0.5 opacity-60">{s.fns}</div>
              </button>
            ))}
          </div>

          {/* Prompt */}
          <textarea
            value={toolPrompt}
            onChange={e => setToolPrompt(e.target.value)}
            rows={3}
            placeholder="Enter your prompt…"
            className="w-full bg-background border border-border rounded-lg p-3 text-sm text-foreground focus:outline-none focus:border-orange-500 resize-y"
          />
          <button
            disabled={toolLoading || !toolPrompt.trim()}
            onClick={async () => {
              setToolLoading(true); setToolError(''); setToolResult(null);
              try {
                const data = await apiClient.llmTools(toolPrompt, toolScenario, { provider: 'openai' });
                setToolResult(data);
              } catch (e: any) {
                setToolError(e?.response?.data?.detail || e.message || 'Request failed');
              } finally { setToolLoading(false); }
            }}
            className="px-4 py-2 bg-orange-600 hover:bg-orange-700 disabled:opacity-50 rounded text-sm font-medium text-white transition-colors"
          >
            {toolLoading ? 'Calling tool…' : 'Run Function Call'}
          </button>

          {toolError && (
            <div className="p-3 bg-destructive/10 border border-destructive/30 rounded text-destructive text-sm">{toolError}</div>
          )}
          {toolResult && (
            <div className="space-y-2">
              {/* Step 1 */}
              <div className="bg-card border border-border rounded p-3 text-sm">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-blue-500/20 text-blue-600 dark:text-blue-300 px-2 py-0.5 rounded text-xs font-bold">Step 1</span>
                  <span className="text-muted-foreground text-xs">LLM selects function</span>
                </div>
                <div className="flex flex-wrap gap-2 mb-1">
                  {(toolResult.available_functions as string[]).map((fn: string) => (
                    <span key={fn} className={`px-2 py-0.5 rounded text-xs font-mono ${fn === toolResult.function_called ? 'bg-green-500/20 text-green-600 dark:text-green-300 font-bold' : 'bg-muted text-muted-foreground'}`}>
                      {fn === toolResult.function_called ? '→ ' : ''}{fn}
                    </span>
                  ))}
                </div>
                <div className="text-xs text-muted-foreground">
                  Args: <span className="text-orange-600 dark:text-orange-400 font-mono">{JSON.stringify(toolResult.arguments)}</span>
                </div>
              </div>
              {/* Step 2 */}
              <div className="bg-card border border-border rounded p-3 text-sm">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-purple-500/20 text-purple-600 dark:text-purple-300 px-2 py-0.5 rounded text-xs font-bold">Step 2</span>
                  <span className="text-muted-foreground text-xs">Mock function result</span>
                </div>
                <pre className="bg-muted p-2 rounded text-xs text-green-600 dark:text-green-400 max-h-40 overflow-y-auto">
                  {JSON.stringify(toolResult.function_result, null, 2)}
                </pre>
              </div>
              {/* Step 3 */}
              <div className="bg-card border border-green-500/30 rounded p-3 text-sm">
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-green-500/20 text-green-600 dark:text-green-300 px-2 py-0.5 rounded text-xs font-bold">Step 3</span>
                  <span className="text-muted-foreground text-xs">Final answer</span>
                  <span className="text-xs bg-green-500/20 text-green-600 dark:text-green-300 px-2 py-0.5 rounded font-bold">✓ OK</span>
                </div>
                <p className="text-foreground">{toolResult.final_answer}</p>
              </div>
              <button onClick={() => setToolShowRaw(!toolShowRaw)} className="text-xs text-muted-foreground hover:text-foreground underline">
                {toolShowRaw ? 'Hide raw tool-turn' : 'Show raw tool-turn JSON'}
              </button>
              {toolShowRaw && (
                <div className="bg-muted p-3 rounded text-xs text-muted-foreground whitespace-pre-wrap max-h-40 overflow-y-auto">{toolResult.raw_tool_turn}</div>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  );
}

export default withPermission(LLMConfigsPage, PermissionLevel.DEVELOPER);
