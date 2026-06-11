'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth-context';
import { GuildSwitcher } from './GuildSwitcher';
import { ThemeToggle } from './ThemeToggle';
import { siteConfig } from '../config';
import { LogOut } from 'lucide-react';
import Link from 'next/link';
import { useTranslation } from '@/lib/i18n';

export function Header() {
    const { user, logout } = useAuth();
    const { t } = useTranslation();
    const [botName, setBotName] = useState<string>(siteConfig.name);

    useEffect(() => {
        fetch('/api/v1/bot-info/public')
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data?.name) setBotName(data.name); })
            .catch(() => {});
    }, []);

    return (
        <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
            <div className="container mx-auto px-4 h-16 flex items-center justify-between">
                <div className="flex items-center gap-6">
                    <Link href="/" className="text-xl font-bold bg-gradient-to-r from-indigo-500 to-purple-500 bg-clip-text text-transparent hover:opacity-80 transition-opacity">
                        {botName}
                    </Link>

                    {user && (
                        <div className="hidden md:block w-64">
                            <GuildSwitcher />
                        </div>
                    )}
                </div>

                <div className="flex items-center gap-4">
                    {user && (
                        <Link href="/dashboard/account" title={t('header.accountSettings')} className="flex items-center gap-3 pl-4 border-l border-border cursor-pointer hover:opacity-80 transition-opacity">
                            {user.avatar_url ? (
                                <img src={user.avatar_url} alt={user.username} className="w-8 h-8 rounded-full" />
                            ) : (
                                <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold">
                                    {user.username.substring(0, 2).toUpperCase()}
                                </div>
                            )}
                            <div className="hidden sm:flex flex-col">
                                <span className="text-sm font-medium leading-none">{user.username}</span>
                                <span className="text-xs text-muted-foreground">
                                    {user.is_admin ? t('header.admin') : t('header.user')}
                                </span>
                            </div>
                        </Link>
                    )}

                    <div className="flex items-center gap-2">
                        <ThemeToggle />
                        {user && (
                            <button
                                onClick={logout}
                                className="p-2 text-muted-foreground hover:text-destructive transition-colors rounded-md hover:bg-destructive/10"
                                title={t('header.logoutTitle')}
                            >
                                <LogOut size={20} />
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </header>
    );
}
