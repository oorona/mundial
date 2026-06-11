'use client';

import { useEffect, useState } from 'react';
import { User, Globe, Moon, Sun, Monitor, Save, Server, Languages } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useSearchParams, useRouter } from 'next/navigation';
import { apiClient, UserSettings } from '@/app/api-client';
import { useAuth } from '@/lib/auth-context';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

interface Guild {
    id: string;
    name: string;
}

function AccountPage() {
    const { user, refreshUser } = useAuth();
    const { theme, setTheme } = useTheme();
    const { t, language, setLanguage } = useTranslation();
    const searchParams = useSearchParams();
    const router = useRouter();
    const isFirstLogin = searchParams.get('firstLogin') === '1';
    const [settings, setSettings] = useState<UserSettings>({
        theme: 'system',
        // Pre-populate from the current UI language (set by welcome page or localStorage)
        // so first-time users see their already-chosen language pre-selected.
        language,
        default_guild_id: ''
    });
    const [guilds, setGuilds] = useState<Guild[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    useEffect(() => {
        const loadData = async () => {
            try {
                const [userData, guildsData] = await Promise.all([
                    apiClient.getUserSettings(),
                    apiClient.getGuilds()
                ]);

                if (userData.settings) {
                    setSettings(prev => ({
                        ...prev,
                        ...userData.settings,
                        // If backend has no language saved yet, keep the UI language
                        // that was set via the welcome page / localStorage.
                        language: userData.settings.language || prev.language,
                    }));
                    // Sync backend theme preference
                    if (userData.settings.theme) {
                        setTheme(userData.settings.theme);
                    }
                }
                setGuilds(guildsData);
            } catch (err) {
                console.error('Failed to load data', err);
            } finally {
                setLoading(false);
            }
        };
        loadData();
    }, []);

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);

        try {
            await apiClient.updateUserSettings(settings);
            // Refresh the user object so preferences.language is up-to-date
            // before any navigation — prevents the first-login redirect loop.
            await refreshUser();
            // Apply theme immediately
            if (settings.theme) {
                setTheme(settings.theme);
            }
            // Apply language immediately
            if (settings.language) {
                setLanguage(settings.language as 'en' | 'es');
            }
            if (isFirstLogin) {
                // Mark setup as done so the dashboard skip the first-login check
                // even if refreshUser hasn't propagated yet.
                sessionStorage.setItem('firstLoginSetupDone', '1');
                router.push('/');
                return;
            }
            setMessage({ type: 'success', text: t('account.savedSuccess') });
        } catch (err) {
            console.error('Failed to save settings', err);
            setMessage({ type: 'error', text: t('account.savedError') });
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="p-8 text-gray-400">{t('account.loadingProfile')}</div>;

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div className="mb-8">
                <h1 className="text-3xl font-bold mb-2 text-foreground">{t('account.title')}</h1>
                <p className="text-muted-foreground">{t('account.subtitle')}</p>
            </div>

            {/* First-login welcome banner */}
            {isFirstLogin && (
                <div className="mb-6 flex items-start gap-4 p-5 rounded-xl bg-primary/10 border border-primary/30">
                    <div className="shrink-0 p-2 rounded-lg bg-primary/20">
                        <Languages className="w-6 h-6 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <p className="font-semibold text-foreground mb-1">{t('account.firstLoginTitle')}</p>
                        <p className="text-sm text-muted-foreground">{t('account.firstLoginMessage')}</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => {
                            sessionStorage.setItem('firstLoginSetupDone', '1');
                            router.push('/');
                        }}
                        className="shrink-0 text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline transition-colors"
                    >
                        {t('account.firstLoginSkip')}
                    </button>
                </div>
            )}

            {message && (
                <div className={`p-4 rounded-lg mb-6 ${message.type === 'success' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'
                    }`}>
                    {message.text}
                </div>
            )}

            <form onSubmit={handleSave} className="space-y-8">
                {/* Profile Section */}
                <div className="bg-card rounded-xl p-6 border border-border">
                    <h2 className="text-xl font-semibold mb-6 flex items-center gap-2 text-foreground">
                        <User className="text-primary" /> {t('account.sectionProfile')}
                    </h2>
                    <div className="flex items-center gap-4 mb-6">
                        {user?.avatar_url && (
                            <img
                                src={user.avatar_url}
                                alt="Avatar"
                                className="w-16 h-16 rounded-full border-2 border-border"
                            />
                        )}
                        <div>
                            <div className="text-foreground font-medium text-lg">{user?.username}</div>
                            <div className="text-muted-foreground text-sm">ID: {user?.user_id}</div>
                        </div>
                    </div>
                </div>

                {/* Default Server Section */}
                <div className="bg-card rounded-xl p-6 border border-border">
                    <h2 className="text-xl font-semibold mb-6 flex items-center gap-2 text-foreground">
                        <Server className="text-primary" /> {t('account.sectionDefaultServer')}
                    </h2>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">{t('account.startupServerLabel')}</label>
                        <select
                            value={settings.default_guild_id || ''}
                            onChange={(e) => setSettings({ ...settings, default_guild_id: e.target.value })}
                            className="w-full px-4 py-2 bg-background border border-border rounded-lg focus:ring-2 focus:ring-primary text-foreground"
                        >
                            <option value="">{t('account.noDefaultServer')}</option>
                            {guilds.map(guild => (
                                <option key={guild.id} value={guild.id}>
                                    {guild.name}
                                </option>
                            ))}
                        </select>
                        <p className="text-sm text-muted-foreground mt-2">
                            {t('account.startupServerHint')}
                        </p>
                    </div>
                </div>

                {/* Appearance Section */}
                <div className="bg-card rounded-xl p-6 border border-border">
                    <h2 className="text-xl font-semibold mb-6 flex items-center gap-2 text-foreground">
                        <Monitor className="text-primary" /> {t('account.sectionAppearance')}
                    </h2>

                    <div className="space-y-4">
                        <label className="block text-sm font-medium text-foreground mb-2">{t('account.themeLabel')}</label>
                        <div className="grid grid-cols-3 gap-4">
                            {(['light', 'dark', 'system'] as const).map((themeOption) => {
                                const isActive = settings.theme === themeOption;
                                const label =
                                    themeOption === 'light' ? t('account.themeLight') :
                                    themeOption === 'dark'  ? t('account.themeDark')  :
                                                              t('account.themeSystem');
                                return (
                                    <button
                                        key={themeOption}
                                        type="button"
                                        onClick={() => {
                                            setSettings(prev => ({ ...prev, theme: themeOption }));
                                            setTheme(themeOption);
                                        }}
                                        className={`flex flex-col items-center justify-center p-4 rounded-lg border-2 transition-all text-foreground ${isActive
                                            ? 'border-primary bg-primary/10'
                                            : 'border-border hover:border-primary/50 bg-secondary'
                                            }`}
                                    >
                                        {themeOption === 'light'  && <Sun     className="w-6 h-6 mb-2" />}
                                        {themeOption === 'dark'   && <Moon    className="w-6 h-6 mb-2" />}
                                        {themeOption === 'system' && <Monitor className="w-6 h-6 mb-2" />}
                                        <span>{label}</span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Language Section */}
                <div className="bg-card rounded-xl p-6 border border-border">
                    <h2 className="text-xl font-semibold mb-6 flex items-center gap-2 text-foreground">
                        <Globe className="text-primary" /> {t('account.sectionLanguage')}
                    </h2>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-2">{t('account.interfaceLanguageLabel')}</label>
                        <select
                            value={settings.language}
                            onChange={(e) => setSettings({ ...settings, language: e.target.value as 'en' | 'es' })}
                            className="w-full px-4 py-2 bg-background border border-border rounded-lg focus:ring-2 focus:ring-primary text-foreground"
                        >
                            <option value="en">English (US)</option>
                            <option value="es">Español (ES)</option>
                        </select>
                        <p className="text-sm text-muted-foreground mt-2">
                            {settings.language === 'es'
                                ? t('account.langHintEs')
                                : t('account.langHintEn')}
                        </p>
                    </div>
                </div>

                <div className="pt-4">
                    <button
                        type="submit"
                        disabled={saving}
                        className="w-full bg-primary hover:opacity-90 text-primary-foreground font-medium py-3 rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                    >
                        {saving ? (
                            <>
                                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                {t('account.saving')}
                            </>
                        ) : (
                            <>
                                <Save className="w-5 h-5" />
                                {isFirstLogin ? t('account.continueButton') : t('account.saveButton')}
                            </>
                        )}
                    </button>
                </div>
            </form>
        </div>
    );
}

export default withPermission(AccountPage, PermissionLevel.USER);
