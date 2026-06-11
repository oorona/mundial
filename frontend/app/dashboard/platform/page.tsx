'use client';

import { useEffect, useState } from 'react';
import { Save, Shield } from 'lucide-react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

function PlatformSettingsPage() {
    const { t } = useTranslation();
    const [settings, setSettings] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const settingsData = await apiClient.getPlatformSettings();
                setSettings(settingsData.settings || {});
            } catch (err) {
                console.error('Failed to load platform settings:', err);
                setMessage({ type: 'error', text: t('platform.loadError') });
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, []);

    const handleSettingChange = (key: string, value: any) => {
        setSettings((prev: Record<string, any>) => ({
            ...prev,
            [key]: value
        }));
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);

        try {
            await apiClient.updatePlatformSettings(settings);
            setMessage({ type: 'success', text: t('platform.savedSuccess') });
        } catch (err) {
            console.error('Failed to save settings:', err);
            setMessage({ type: 'error', text: t('platform.saveError') });
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return <div className="p-8 text-muted-foreground">{t('platform.loading')}</div>;
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="mb-8">
                <h1 className="text-3xl font-bold mb-2 text-foreground">{t('platform.title')}</h1>
                <p className="text-muted-foreground">{t('platform.subtitle')}</p>
            </div>

            {message && (
                <div className={`p-4 rounded-lg mb-6 ${message.type === 'success' ? 'bg-green-500/10 text-green-500' : 'bg-destructive/10 text-destructive'
                    }`}>
                    {message.text}
                </div>
            )}

            <form onSubmit={handleSave} className="space-y-8">
                <div className="space-y-6 border-b border-border pb-8">
                    <div className="flex items-center gap-2 mb-4">
                        <Shield className="text-yellow-500" size={20} />
                        <h2 className="text-xl font-semibold text-yellow-500">{t('platform.sectionGlobal')}</h2>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                        {t('platform.sectionGlobalDesc')}
                    </p>

                    <div>
                        <label className="block text-sm font-medium mb-2 text-foreground">{t('platform.systemPromptLabel')}</label>
                        <textarea
                            value={settings?.system_prompt || ''}
                            onChange={(e) => handleSettingChange('system_prompt', e.target.value)}
                            className="w-full px-4 py-2 bg-background border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent h-32 text-foreground"
                            placeholder={t('platform.systemPromptPlaceholder')}
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2 text-foreground">{t('platform.modelLabel')}</label>
                        <select
                            value={settings?.model || 'openai'}
                            onChange={(e) => handleSettingChange('model', e.target.value)}
                            className="w-full px-4 py-2 bg-background border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent text-foreground"
                        >
                            <option value="openai">OpenAI (GPT-4)</option>
                            <option value="anthropic">Anthropic (Claude 3)</option>
                            <option value="google">Google (Gemini Pro)</option>
                            <option value="xai">xAI (Grok)</option>
                        </select>
                    </div>
                </div>

                <div className="pt-6">
                    <button
                        type="submit"
                        disabled={saving}
                        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-medium py-3 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                    >
                        {saving ? (
                            <>
                                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                {t('platform.saving')}
                            </>
                        ) : (
                            <>
                                <Save className="w-5 h-5" />
                                <span className="text-primary-foreground">{t('platform.saveButton')}</span>
                            </>
                        )}
                    </button>
                </div>
            </form>
        </div>
    );
}

export default withPermission(PlatformSettingsPage, PermissionLevel.DEVELOPER);
