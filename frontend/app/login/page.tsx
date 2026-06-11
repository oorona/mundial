'use client';

import { LogIn } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { useTranslation } from '@/lib/i18n';

interface BotInfo {
    name: string;
    tagline: string;
    logo_url: string;
}

async function fetchBotInfo(lang: string): Promise<BotInfo> {
    const res = await fetch(`/api/v1/bot-info/public?lang=${lang}`);
    if (!res.ok) throw new Error('Failed to load bot info');
    return res.json();
}

function LoginContent() {
    const searchParams = useSearchParams();
    const error = searchParams.get('error');
    const details = searchParams.get('details');
    const [loggingIn, setLoggingIn] = useState(false);
    const [botInfo, setBotInfo] = useState<BotInfo | null>(null);
    const [serviceDown, setServiceDown] = useState(false);
    const { t, setLanguage, language } = useTranslation();

    useEffect(() => {
        fetchBotInfo(language)
            .then(info => { setBotInfo(info); setServiceDown(false); })
            .catch(() => setServiceDown(true));
    }, [language]);

    // Apply ?lang= query param on first render so shareable URLs work.
    useEffect(() => {
        const lang = searchParams.get('lang');
        if (lang === 'en' || lang === 'es') setLanguage(lang);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const botName = botInfo?.name || '';
    const tagline = botInfo?.tagline || '';

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            console.log('Message received on login page:', event.data);
            console.log('Message origin:', event.origin);

            if (event.data.type === 'DISCORD_LOGIN_SUCCESS' && event.data.token) {
                console.log('Discord login success! Token:', event.data.token);
                localStorage.setItem('access_token', event.data.token);
                setLoggingIn(false);
                // Use window.location instead of router.push for more reliable redirect
                window.location.href = `/?token=${event.data.token}`;
            } else if (event.data.type === 'DISCORD_SILENT_LOGIN_SUCCESS' && event.data.token) {
                console.log('Discord silent login success! Token:', event.data.token);
                localStorage.setItem('access_token', event.data.token);
                setLoggingIn(false);
                window.location.href = `/?token=${event.data.token}`;
            }
        };

        console.log('Setting up message listener for Discord login');
        window.addEventListener('message', handleMessage);
        return () => {
            console.log('Cleaning up message listener');
            window.removeEventListener('message', handleMessage);
        };
    }, []); // Empty dependency array - listener stays active for component lifetime

    const handleLogin = (useRedirect: boolean = false) => {
        console.log('Starting login, useRedirect:', useRedirect);
        setLoggingIn(true);

        // Use simple redirect instead of popup for now (more reliable)
        if (useRedirect) {
            window.location.href = '/api/v1/auth/discord/login';
            return;
        }

        const width = 500;
        const height = 700;
        const left = window.screen.width / 2 - width / 2;
        const top = window.screen.height / 2 - height / 2;

        // Use a unique window name each time to avoid caching issues
        const windowName = `discord-login-${Date.now()}`;

        const popup = window.open(
            '/api/v1/auth/discord/login?state=popup',
            windowName,
            `width=${width},height=${height},left=${left},top=${top}`
        );

        if (!popup) {
            console.error('Failed to open popup - may be blocked by browser');
            setLoggingIn(false);
            alert(t('login.popupBlocked'));
            return;
        }

        console.log('Popup opened successfully with name:', windowName);

        // Check if popup was closed manually
        const checkPopup = setInterval(() => {
            if (popup && popup.closed) {
                console.log('Popup was closed');
                clearInterval(checkPopup);
                setLoggingIn(false);
            }
        }, 500);
    };

    // ...

    return (
        <div className="min-h-screen flex items-center justify-center bg-background p-4">
            <div className="bg-card rounded-2xl p-8 shadow-xl border border-border max-w-md w-full">
                <div className="text-center mb-8">
                    {botName && <h1 className="text-4xl font-bold text-foreground mb-2">{botName}</h1>}
                    {tagline && <p className="text-muted-foreground">{tagline}</p>}
                </div>

                {serviceDown && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-600 dark:text-yellow-400 px-4 py-3 rounded-lg mb-4 text-sm text-center">
                        {t('login.serviceUnavailable')}
                    </div>
                )}

                {error && (
                    <div className="bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 rounded-lg relative mb-4" role="alert">
                        <strong className="font-bold">{t('login.loginFailed')} </strong>
                        <span className="block sm:inline">
                            {error === 'discord_error' && details?.includes('rate limit')
                                ? t('login.rateLimitError')
                                : error === 'discord_error'
                                ? t('login.discordError')
                                : error === 'internal_error'
                                ? t('login.unexpectedError')
                                : t('login.unexpectedError')}
                        </span>
                        {details && !details.includes('rate limit') && (
                            <div className="mt-2 text-xs bg-black/10 p-2 rounded overflow-auto max-h-20 text-destructive font-mono">
                                {t('login.detailsLabel', { details: decodeURIComponent(details) })}
                            </div>
                        )}
                    </div>
                )}

                <button
                    onClick={() => handleLogin(true)}
                    disabled={loggingIn}
                    className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-4 px-6 rounded-xl transition-all duration-200 flex items-center justify-center gap-3 shadow-md hover:shadow-lg hover:scale-[1.02] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {loggingIn ? (
                        <>
                            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                            {t('login.loggingIn')}
                        </>
                    ) : (
                        <>
                            <LogIn className="w-5 h-5" />
                            {t('login.loginButton')}
                        </>
                    )}
                </button>

                <button
                    onClick={() => window.location.href = '/api/v1/auth/discord/login?prompt=consent'}
                    className="w-full mt-4 bg-secondary hover:bg-secondary/80 text-secondary-foreground font-semibold py-3 px-6 rounded-xl transition-all duration-200 flex items-center justify-center gap-3 border border-border"
                >
                    {t('login.switchAccount')}
                </button>

                <p className="text-muted-foreground text-sm text-center mt-6">
                    {t('login.signInPrompt')}
                </p>
            </div>
        </div>
    );
}

export default function LoginPage() {
    return (
        <Suspense fallback={<div>{/* loading */}</div>}>
            <LoginContent />
        </Suspense>
    );
}
