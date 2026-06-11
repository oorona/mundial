'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { usePlugins } from '@/app/plugins';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';
import { Settings2, Save } from 'lucide-react';

interface BuiltinCard {
    id: string;
    level: PermissionLevel;
    defaultVisible: boolean;
    titleKey: string;
    descKey: string;
}

// Built-in cards, each tagged with its access level.
const ALL_BUILTIN: BuiltinCard[] = [
    { id: 'bot-overview',      level: PermissionLevel.PUBLIC,        defaultVisible: false, titleKey: 'dashboard.cardBotOverviewTitle',  descKey: 'dashboard.cardBotOverviewDesc' },
    { id: 'command-reference', level: PermissionLevel.PUBLIC_DATA,   defaultVisible: true,  titleKey: 'dashboard.cardCommandRefTitle',   descKey: 'dashboard.cardCommandRefDesc' },
    { id: 'bot-health',        level: PermissionLevel.AUTHORIZED,    defaultVisible: true,  titleKey: 'dashboard.cardBotHealthTitle',    descKey: 'dashboard.cardBotHealthDesc' },
    { id: 'bot-settings',      level: PermissionLevel.ADMINISTRATOR, defaultVisible: true,  titleKey: 'dashboard.cardBotSettingsTitle',  descKey: 'dashboard.cardBotSettingsDesc' },
    { id: 'permissions',       level: PermissionLevel.OWNER,         defaultVisible: true,  titleKey: 'dashboard.cardPermissionsTitle',  descKey: 'dashboard.cardPermissionsDesc' },
    { id: 'audit-logs',        level: PermissionLevel.DEVELOPER,     defaultVisible: true,  titleKey: 'dashboard.cardAuditLogsTitle',    descKey: 'dashboard.cardAuditLogsDesc' },
    // Project (WC2026) cards — added to the dashboard's hardcoded `cards` array (not the
    // usePlugins() registry), so they're registered here by their dashboard id so owners
    // can toggle them. Only the below-owner, member-facing ones (USER level) are listed;
    // live_tracker / ai-analyst / platform-status (Developer) and submissions (Owner) are
    // intentionally excluded.
    { id: 'worldcup',          level: PermissionLevel.USER,          defaultVisible: true,  titleKey: 'worldcup.title',     descKey: 'worldcup.description' },
    { id: 'fixtures',          level: PermissionLevel.USER,          defaultVisible: true,  titleKey: 'fixtures.title',     descKey: 'fixtures.description' },
    { id: 'predictions',       level: PermissionLevel.USER,          defaultVisible: true,  titleKey: 'predictions.title',  descKey: 'predictions.description' },
    { id: 'leaderboard',       level: PermissionLevel.USER,          defaultVisible: true,  titleKey: 'leaderboard.title',  descKey: 'leaderboard.description' },
];

// Resolved (translated) card the owner can toggle. Built from built-in cards AND
// plugin nav cards, both filtered to BELOW owner level.
interface ResolvedCard {
    id: string;
    level: PermissionLevel;
    defaultVisible: boolean;
    title: string;
    description: string;
}

function CardVisibilityPage() {
    const params = useParams();
    const guildId = params?.guildId as string;
    const { t } = useTranslation();
    const { navItems: pluginNavItems } = usePlugins();

    // Owners may only control cards BELOW owner level (Administrator and down) —
    // built-in cards AND cards introduced by plugins. Owner-/Developer-level cards
    // (Permissions, Audit Logs) are not member-facing, so they are not theirs to hide.
    const cards: ResolvedCard[] = useMemo(() => {
        const builtin = ALL_BUILTIN
            .filter(c => c.level < PermissionLevel.OWNER)
            .map(c => ({
                id: c.id,
                level: c.level,
                defaultVisible: c.defaultVisible,
                title: t(c.titleKey as any),
                description: t(c.descKey as any),
            }));
        const plugins = (pluginNavItems || [])
            .filter((p: any) => (p.level ?? PermissionLevel.USER) < PermissionLevel.OWNER)
            .map((p: any) => ({
                id: `plugin-${p.id || p.name}`,
                level: (p.level ?? PermissionLevel.USER) as PermissionLevel,
                defaultVisible: true,
                title: p.name,
                description: p.description || t('dashboard.cardPluginDesc'),
            }));
        return [...builtin, ...plugins];
    }, [pluginNavItems, t]);

    const [visibility, setVisibility] = useState<Record<string, boolean>>({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

    useEffect(() => {
        if (!guildId) return;
        const load = async () => {
            try {
                const data = await apiClient.getCardVisibility(guildId);
                // Merge with defaults: API values override defaults
                setVisibility(prev => ({ ...prev, ...data }));
            } catch (err: any) {
                // 404 = endpoint not yet deployed on the backend — use defaults silently
                if (err?.response?.status !== 404) {
                    setMessage({ type: 'error', text: t('cardVisibility.loadingError') });
                }
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [guildId]);

    const toggle = (cardId: string) => {
        setVisibility(prev => ({ ...prev, [cardId]: !prev[cardId] }));
        // Clear any lingering message when user makes a change
        setMessage(null);
    };

    const handleSave = async () => {
        if (!guildId) return;
        setSaving(true);
        setMessage(null);
        try {
            await apiClient.updateCardVisibility(guildId, visibility);
            setMessage({ type: 'success', text: t('cardVisibility.savedSuccess') });
        } catch {
            setMessage({ type: 'error', text: t('cardVisibility.savedError') });
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
                {[...Array(4)].map((_, i) => (
                    <div key={i} className="animate-pulse bg-card border border-border rounded-xl p-5 flex items-center justify-between">
                        <div className="space-y-2 flex-1">
                            <div className="h-4 bg-muted rounded w-1/3" />
                            <div className="h-3 bg-muted rounded w-2/3" />
                        </div>
                        <div className="h-6 w-11 bg-muted rounded-full ml-4" />
                    </div>
                ))}
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            {/* Header */}
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
                    <Settings2 className="text-primary" />
                    {t('cardVisibility.title')}
                </h1>
                <p className="text-muted-foreground mt-1">{t('cardVisibility.subtitle')}</p>
            </div>

            {/* Hint */}
            <p className="text-sm text-muted-foreground mb-6 p-4 bg-muted/30 rounded-lg border border-border">
                {t('cardVisibility.hint')}
            </p>

            {/* Message */}
            {message && (
                <div className={`mb-6 p-4 rounded-lg ${message.type === 'success' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}`}>
                    {message.text}
                </div>
            )}

            {/* Card list */}
            <div className="space-y-3 mb-8">
                {cards.map(card => {
                    const enabled = visibility[card.id] ?? card.defaultVisible;
                    return (
                        <div
                            key={card.id}
                            className="bg-card border border-border rounded-xl p-5 flex items-center justify-between gap-4 transition-colors hover:border-primary/30"
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="font-medium text-foreground">
                                        {card.title}
                                    </span>
                                    {!card.defaultVisible && (
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/25 font-medium">
                                            {t('cardVisibility.offByDefault')}
                                        </span>
                                    )}
                                </div>
                                <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">
                                    {card.description}
                                </p>
                                <p className="text-xs mt-1 font-medium">
                                    <span className={enabled ? 'text-green-500' : 'text-muted-foreground'}>
                                        {enabled ? t('cardVisibility.enabled') : t('cardVisibility.disabled')}
                                    </span>
                                </p>
                            </div>

                            {/* Toggle switch */}
                            <button
                                type="button"
                                onClick={() => toggle(card.id)}
                                className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background ${enabled ? 'bg-primary' : 'bg-muted'}`}
                                aria-label={`${card.title} — ${enabled ? t('cardVisibility.enabled') : t('cardVisibility.disabled')}`}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`}
                                />
                            </button>
                        </div>
                    );
                })}
            </div>

            {/* Save button */}
            <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="w-full bg-primary hover:opacity-90 text-primary-foreground font-medium py-3 rounded-lg transition-opacity disabled:opacity-50 flex items-center justify-center gap-2"
            >
                {saving ? (
                    <>
                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        {t('cardVisibility.saving')}
                    </>
                ) : (
                    <>
                        <Save className="w-5 h-5" />
                        {t('cardVisibility.saveButton')}
                    </>
                )}
            </button>
        </div>
    );
}

export default withPermission(CardVisibilityPage, PermissionLevel.OWNER);
