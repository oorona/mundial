'use client';

import { useState, useEffect } from 'react';
import { Check, ChevronsUpDown, PlusCircle } from 'lucide-react';
import { cn } from '../utils';
import { apiClient } from '../api-client';
import { usePathname, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth-context';
import { useTranslation } from '@/lib/i18n';

interface Guild {
    id: string;
    name: string;
    icon?: string;
    bot_not_added?: boolean;
}

export function GuildSwitcher({ currentGuildId }: { currentGuildId?: string }) {
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const [isOpen, setIsOpen] = useState(false);
    const [guilds, setGuilds] = useState<Guild[]>([]);
    const [loading, setLoading] = useState(true);
    const [baseInviteUrl, setBaseInviteUrl] = useState<string>('');
    const { user } = useAuth();
    const { t } = useTranslation();

    useEffect(() => {
        fetch('/api/v1/bot-info/public')
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data?.invite_url) setBaseInviteUrl(data.invite_url); })
            .catch(() => null);
    }, []);

    useEffect(() => {
        if (!user) { setLoading(false); return; }
        apiClient.getGuilds()
            .then(setGuilds)
            .catch(() => null)
            .finally(() => setLoading(false));
    }, [user]);

    const paramGuildId = searchParams.get('guild_id');
    const pathGuildId = pathname?.match(/\/dashboard\/(\d+)/)?.[1];
    const effectiveGuildId = currentGuildId || paramGuildId || pathGuildId || user?.preferences?.default_guild_id || guilds[0]?.id;

    const currentGuild = guilds.find((g) => g.id === effectiveGuildId && !g.bot_not_added);

    const activeGuilds  = guilds.filter(g => !g.bot_not_added);
    const pendingGuilds = guilds.filter(g =>  g.bot_not_added);

    const getTargetHref = (targetGuildId: string) => {
        if (pathname === '/') return `/?guild_id=${targetGuildId}`;
        if (effectiveGuildId && pathname?.includes(effectiveGuildId))
            return pathname.replace(effectiveGuildId, targetGuildId);
        return `/dashboard/${targetGuildId}/settings`;
    };

    const inviteUrl = (guildId: string) => {
        if (!baseInviteUrl) return '#';
        return `${baseInviteUrl}&guild_id=${guildId}`;
    };

    return (
        <div className="relative">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center justify-between w-full px-4 py-2 text-sm bg-secondary rounded-lg hover:bg-secondary/80 transition-colors border border-border"
                disabled={loading}
            >
                <span className="truncate">
                    {loading
                        ? t('common.loading')
                        : currentGuild
                        ? currentGuild.name
                        : t('guildSwitcher.selectServer')}
                </span>
                <ChevronsUpDown size={16} className="ml-2 opacity-50 shrink-0" />
            </button>

            {isOpen && (
                <>
                    <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
                    <div className="absolute z-20 w-full mt-2 bg-card border border-border rounded-lg shadow-lg max-h-72 overflow-auto">

                        {/* Guilds where bot is active */}
                        {activeGuilds.map((guild) => (
                            <Link
                                key={guild.id}
                                href={getTargetHref(guild.id)}
                                className={cn(
                                    'flex items-center justify-between px-4 py-3 hover:bg-muted transition-colors',
                                    guild.id === effectiveGuildId && 'bg-muted'
                                )}
                                onClick={() => setIsOpen(false)}
                            >
                                <span className="text-sm truncate">{guild.name}</span>
                                {guild.id === effectiveGuildId && (
                                    <Check size={16} className="text-green-500 shrink-0" />
                                )}
                            </Link>
                        ))}

                        {/* Guilds where bot needs to be added */}
                        {pendingGuilds.length > 0 && (
                            <>
                                {activeGuilds.length > 0 && (
                                    <div className="px-4 py-2 border-t border-border">
                                        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                                            {t('guildSwitcher.addBot')}
                                        </p>
                                    </div>
                                )}
                                {pendingGuilds.map((guild) => (
                                    <a
                                        key={guild.id}
                                        href={inviteUrl(guild.id)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center justify-between px-4 py-3 hover:bg-muted transition-colors"
                                        onClick={() => setIsOpen(false)}
                                    >
                                        <span className="text-sm truncate text-muted-foreground">{guild.name}</span>
                                        <PlusCircle size={16} className="text-primary shrink-0 ml-2" />
                                    </a>
                                ))}
                            </>
                        )}

                        {guilds.length === 0 && !loading && (
                            <p className="p-4 text-sm text-muted-foreground">{t('guildSwitcher.noServers')}</p>
                        )}
                    </div>
                </>
            )}
        </div>
    );
}
