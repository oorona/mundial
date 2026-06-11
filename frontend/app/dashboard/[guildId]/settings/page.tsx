'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { Save, Shield, AlertCircle } from 'lucide-react';
import { apiClient, SettingsField, SettingsSchema } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

// ─── Field renderers ──────────────────────────────────────────────────────────

interface FieldProps {
    field: SettingsField;
    value: any;
    onChange: (key: string, value: any) => void;
    disabled: boolean;
    channels: { id: string; name: string }[];
    roles: { id: string; name: string; color: number }[];
}

function BooleanField({ field, value, onChange, disabled }: FieldProps) {
    return (
        <div className="flex items-center justify-between">
            <div>
                <label htmlFor={field.key} className="text-sm font-medium cursor-pointer">
                    {field.label}
                </label>
                {field.description && (
                    <p className="text-xs text-muted-foreground mt-0.5">{field.description}</p>
                )}
            </div>
            <input
                id={field.key}
                type="checkbox"
                checked={value ?? field.default ?? false}
                onChange={(e) => onChange(field.key, e.target.checked)}
                disabled={disabled}
                className="w-5 h-5 rounded border-input bg-background checked:bg-primary text-primary focus:ring-ring transition-colors"
            />
        </div>
    );
}

function ChannelSelectField({ field, value, onChange, disabled, channels }: FieldProps) {
    const { t } = useTranslation();
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <select
                value={value ?? ''}
                onChange={(e) => onChange(field.key, e.target.value || null)}
                disabled={disabled}
                className="w-full px-4 py-2 bg-background border border-input rounded-lg focus:ring-2 focus:ring-ring outline-none transition-shadow disabled:opacity-50"
            >
                <option value="">{t('common.selectChannel')}</option>
                {channels.map((ch) => (
                    <option key={ch.id} value={ch.id}>#{ch.name}</option>
                ))}
            </select>
        </div>
    );
}

function RoleSelectField({ field, value, onChange, disabled, roles }: FieldProps) {
    const { t } = useTranslation();
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <select
                value={value ?? ''}
                onChange={(e) => onChange(field.key, e.target.value || null)}
                disabled={disabled}
                className="w-full px-4 py-2 bg-background border border-input rounded-lg focus:ring-2 focus:ring-ring outline-none transition-shadow disabled:opacity-50"
            >
                <option value="">{t('common.selectRole')}</option>
                {roles.map((r) => (
                    <option key={r.id} value={r.id}>@{r.name}</option>
                ))}
            </select>
        </div>
    );
}

function MultiselectField({ field, value, onChange, disabled }: FieldProps) {
    const selected: string[] = value ?? field.default ?? [];
    const choices = field.choices ?? [];

    const toggle = (choiceValue: string, checked: boolean) => {
        const next = checked
            ? [...selected, choiceValue]
            : selected.filter((v) => v !== choiceValue);
        onChange(field.key, next);
    };

    return (
        <div className="space-y-2">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <div className="space-y-2 bg-muted/50 p-4 rounded-lg border border-border">
                {choices.map((choice) => (
                    <div key={choice.value} className="flex items-center gap-3">
                        <input
                            id={`${field.key}_${choice.value}`}
                            type="checkbox"
                            checked={selected.includes(choice.value)}
                            onChange={(e) => toggle(choice.value, e.target.checked)}
                            disabled={disabled}
                            className="w-4 h-4 rounded border-input bg-background text-primary focus:ring-ring"
                        />
                        <label
                            htmlFor={`${field.key}_${choice.value}`}
                            className="text-sm cursor-pointer select-none"
                        >
                            {choice.label}
                        </label>
                    </div>
                ))}
            </div>
        </div>
    );
}

function TextField({ field, value, onChange, disabled }: FieldProps) {
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <input
                type={field.type === 'number' ? 'number' : 'text'}
                value={value ?? field.default ?? ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                disabled={disabled}
                className="w-full px-4 py-2 bg-background border border-input rounded-lg focus:ring-2 focus:ring-ring outline-none transition-shadow disabled:opacity-50"
            />
        </div>
    );
}

function NumberField({ field, value, onChange, disabled }: FieldProps) {
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <input
                type="number"
                value={value ?? field.default ?? ''}
                min={field.min}
                max={field.max}
                step={field.step}
                onChange={(e) => onChange(field.key, e.target.value === '' ? null : Number(e.target.value))}
                disabled={disabled}
                className="w-full px-4 py-2 bg-background border border-input rounded-lg focus:ring-2 focus:ring-ring outline-none transition-shadow disabled:opacity-50"
            />
        </div>
    );
}

function SelectField({ field, value, onChange, disabled }: FieldProps) {
    const choices = field.choices ?? field.options ?? [];
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <select
                value={value ?? field.default ?? ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                disabled={disabled}
                className="w-full px-4 py-2 bg-background border border-input rounded-lg focus:ring-2 focus:ring-ring outline-none transition-shadow disabled:opacity-50"
            >
                {choices.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                ))}
            </select>
        </div>
    );
}

function ColorField({ field, value, onChange, disabled }: FieldProps) {
    const v = (value ?? field.default ?? '#000000') as string;
    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <div className="flex items-center gap-2">
                <input
                    type="color"
                    value={v}
                    onChange={(e) => onChange(field.key, e.target.value)}
                    disabled={disabled}
                    className="h-9 w-12 rounded border border-input bg-background disabled:opacity-50"
                />
                <input
                    type="text"
                    value={v}
                    onChange={(e) => onChange(field.key, e.target.value)}
                    disabled={disabled}
                    className="w-32 px-3 py-2 bg-background border border-input rounded-lg font-mono text-sm disabled:opacity-50"
                />
            </div>
        </div>
    );
}

function ColorListField({ field, value, onChange, disabled }: FieldProps) {
    const defaults = Array.isArray(field.default) ? (field.default as string[]) : [];
    const base: string[] = Array.isArray(value) ? value : defaults;
    const length = field.count ?? base.length;
    const colors: string[] = Array.from({ length }, (_, i) => base[i] ?? '#000000');
    const setAt = (i: number, c: string) => {
        const next = [...colors];
        next[i] = c;
        onChange(field.key, next);
    };
    return (
        <div className="space-y-2">
            <label className="block text-sm font-medium">{field.label}</label>
            {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            <div className="flex flex-wrap gap-2">
                {colors.map((c, i) => (
                    <input
                        key={i}
                        type="color"
                        value={c}
                        onChange={(e) => setAt(i, e.target.value)}
                        disabled={disabled}
                        className="h-9 w-9 rounded border border-input bg-background disabled:opacity-50"
                        title={`#${i + 1}`}
                    />
                ))}
            </div>
        </div>
    );
}

function SchemaField(props: FieldProps) {
    switch (props.field.type) {
        case 'boolean':        return <BooleanField {...props} />;
        case 'channel_select': return <ChannelSelectField {...props} />;
        case 'role_select':    return <RoleSelectField {...props} />;
        case 'multiselect':    return <MultiselectField {...props} />;
        case 'number':         return <NumberField {...props} />;
        case 'select':         return <SelectField {...props} />;
        case 'color':          return <ColorField {...props} />;
        case 'color_list':     return <ColorListField {...props} />;
        default:               return <TextField {...props} />;
    }
}

// ─── Public site (slug) section ─────────────────────────────────────────────

function PublicSiteSection({ guildId, initialSlug, disabled }: { guildId: string; initialSlug: string | null; disabled: boolean }) {
    const { t } = useTranslation();
    const [slug, setSlug] = useState(initialSlug ?? '');
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
    const prefix = process.env.NEXT_PUBLIC_SLUG_PREFIX || '/p';

    const save = async () => {
        setSaving(true);
        setMsg(null);
        try {
            const res = await apiClient.setGuildSlug(guildId, slug.trim().toLowerCase());
            setSlug(res.slug);
            setMsg({ type: 'success', text: t('publicSite.slugSaved') });
        } catch (e: any) {
            const status = e?.response?.status;
            setMsg({ type: 'error', text: status === 409 ? t('publicSite.slugTaken') : t('publicSite.slugInvalid') });
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="bg-card border border-border rounded-xl p-6 shadow-sm space-y-4">
            <div className="border-b border-border pb-4">
                <h2 className="text-xl font-semibold">{t('publicSite.settingsTitle')}</h2>
                <p className="text-sm text-muted-foreground mt-1">
                    {t('publicSite.settingsDesc', { url: `${prefix}/${slug || ''}` })}
                </p>
            </div>
            <div className="space-y-1">
                <label className="block text-sm font-medium">{t('publicSite.slugLabel')}</label>
                <p className="text-xs text-muted-foreground">{t('publicSite.slugHint')}</p>
                <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground font-mono">{prefix}/</span>
                    <input
                        type="text"
                        value={slug}
                        disabled={disabled}
                        onChange={(e) => setSlug(e.target.value)}
                        className="flex-1 px-4 py-2 bg-background border border-input rounded-lg font-mono text-sm focus:ring-2 focus:ring-ring outline-none disabled:opacity-50"
                    />
                    <button
                        type="button"
                        onClick={save}
                        disabled={disabled || saving}
                        className="bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
                    >
                        {t('publicSite.slugSave')}
                    </button>
                </div>
            </div>
            {msg && (
                <div className={`text-sm font-medium ${msg.type === 'success' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                    {msg.text}
                </div>
            )}
        </div>
    );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function GuildSettingsPage() {
    const { t } = useTranslation();
    const params = useParams();
    const guildId = params.guildId as string;

    const [schemas, setSchemas] = useState<SettingsSchema[]>([]);
    const [settings, setSettings] = useState<Record<string, any>>({});
    const [channels, setChannels] = useState<{ id: string; name: string }[]>([]);
    const [roles, setRoles] = useState<{ id: string; name: string; color: number }[]>([]);
    const [canModify, setCanModify] = useState(false);
    const [currentSlug, setCurrentSlug] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            if (!guildId) return;
            try {
                const [settingsData, guildData, channelsData, rolesData, schemaData] = await Promise.all([
                    apiClient.getGuildSettings(guildId),
                    apiClient.getGuild(guildId),
                    apiClient.getGuildChannels(guildId),
                    apiClient.getGuildRoles(guildId),
                    apiClient.getSettingsSchema(),
                ]);

                setSettings(settingsData.settings || {});
                setCanModify(
                    guildData.permission_level === 'owner' ||
                    guildData.permission_level === 'admin' ||
                    settingsData.can_modify_level_3 === true
                );
                setChannels(
                    channelsData
                        .filter((c: any) => c.type === 0)
                        .map((c: any) => ({ id: String(c.id), name: c.name }))
                );
                setRoles(
                    (rolesData ?? [])
                        .filter((r: any) => r.name !== '@everyone')
                        .map((r: any) => ({ id: String(r.id), name: r.name, color: r.color ?? 0 }))
                );
                setSchemas(schemaData.schemas || []);
                setCurrentSlug(guildData.slug ?? null);
            } catch (err) {
                console.error('Failed to load settings:', err);
                setMessage({ type: 'error', text: t('guildSettings.loadError') });
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [guildId]);

    const handleChange = (key: string, value: any) => {
        setSettings((prev) => ({ ...prev, [key]: value }));
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);
        try {
            await apiClient.updateGuildSettings(guildId, settings);
            setMessage({ type: 'success', text: t('guildSettings.savedSuccess') });
        } catch {
            setMessage({ type: 'error', text: t('guildSettings.saveError') });
        } finally {
            setSaving(false);
        }
    };

    const isReadOnly = !canModify;

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <div className="text-muted-foreground animate-pulse">{t('guildSettings.loading')}</div>
            </div>
        );
    }

    // If no schemas are published yet (bot hasn't connected), show a placeholder
    const content =
        schemas.length === 0 ? (
            <div className="bg-card border border-border rounded-xl p-8 text-center text-muted-foreground space-y-2">
                <AlertCircle className="mx-auto w-8 h-8 opacity-40" />
                <p className="font-medium">{t('guildSettings.noSchemas')}</p>
                <p className="text-sm">{t('guildSettings.noSchemasHint')}</p>
            </div>
        ) : (
            schemas.map((schema) => (
                <div key={schema.id} className="bg-card border border-border rounded-xl p-6 shadow-sm space-y-5">
                    <div className="border-b border-border pb-4">
                        <h2 className="text-xl font-semibold">{t(schema.label)}</h2>
                        {schema.description && (
                            <p className="text-sm text-muted-foreground mt-1">{t(schema.description)}</p>
                        )}
                    </div>
                    <div className="space-y-6">
                        {schema.fields.map((field) => {
                            // Labels/descriptions may be i18n keys (e.g. "worldcup_data.settings.x")
                            // or raw strings. t() translates keys and falls back to the raw string,
                            // so the settings form follows the selected language instead of mixing.
                            const tField = {
                                ...field,
                                label: t(field.label),
                                description: field.description ? t(field.description) : field.description,
                                choices: field.choices?.map((c: any) => ({ ...c, label: t(c.label) })),
                            };
                            return (
                                <SchemaField
                                    key={field.key}
                                    field={tField}
                                    value={settings[field.key]}
                                    onChange={handleChange}
                                    disabled={isReadOnly}
                                    channels={channels}
                                    roles={roles}
                                />
                            );
                        })}
                    </div>
                </div>
            ))
        );

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">{t('guildSettings.title')}</h1>
                <p className="text-muted-foreground mt-2">{t('guildSettings.subtitle')}</p>
            </div>

            {isReadOnly && (
                <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-yellow-600 dark:text-yellow-400 text-sm flex items-center gap-2">
                    <Shield size={16} />
                    {t('guildSettings.readOnlyBanner')}
                </div>
            )}

            {message && (
                <div className={`p-4 rounded-lg text-sm font-medium ${
                    message.type === 'success'
                        ? 'bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20'
                        : 'bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20'
                }`}>
                    {message.text}
                </div>
            )}

            <PublicSiteSection guildId={guildId} initialSlug={currentSlug} disabled={isReadOnly} />

            {/* Required Discord permissions — so owners know what to grant the bot per channel. */}
            <div className="rounded-lg border border-border bg-card p-5">
                <div className="mb-1 flex items-center gap-2">
                    <Shield size={18} className="text-primary" />
                    <h2 className="text-xl font-semibold">{t('botPerms.title')}</h2>
                </div>
                <p className="text-sm text-muted-foreground">{t('botPerms.desc')}</p>
                <ul className="mt-3 space-y-2">
                    {([
                        ['viewChannel', 'viewChannelDesc'],
                        ['sendMessages', 'sendMessagesDesc'],
                        ['embedLinks', 'embedLinksDesc'],
                        ['readHistory', 'readHistoryDesc'],
                        ['createThreads', 'createThreadsDesc'],
                        ['sendInThreads', 'sendInThreadsDesc'],
                        ['manageThreads', 'manageThreadsDesc'],
                    ] as const).map(([k, d]) => (
                        <li key={k} className="flex gap-2 text-sm">
                            <span className="mt-0.5 text-green-500">✓</span>
                            <span>
                                <span className="font-medium text-foreground">{t(`botPerms.${k}`)}</span>
                                {' — '}
                                <span className="text-muted-foreground">{t(`botPerms.${d}`)}</span>
                            </span>
                        </li>
                    ))}
                </ul>
                <p className="mt-3 text-xs text-muted-foreground">{t('botPerms.note')}</p>
            </div>

            <form onSubmit={handleSave} className="space-y-8">
                {content}

                {schemas.length > 0 && (
                    <div className="flex justify-end pt-4">
                        <button
                            type="submit"
                            disabled={saving || isReadOnly}
                            className="bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-8 py-3 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shadow-sm"
                        >
                            {saving ? (
                                <>
                                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    {t('guildSettings.saving')}
                                </>
                            ) : (
                                <>
                                    <Save className="w-5 h-5" />
                                    {t('guildSettings.saveButton')}
                                </>
                            )}
                        </button>
                    </div>
                )}
            </form>
        </div>
    );
}

// Level 4: Administrator
export default withPermission(GuildSettingsPage, PermissionLevel.ADMINISTRATOR);
