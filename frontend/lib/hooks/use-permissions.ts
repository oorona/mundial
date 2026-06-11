import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/app/api-client';
import { PermissionLevel } from '../permissions';
import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';

const PERM_CACHE_KEY = 'lastGuildPermLevel';

export function usePermissions(guildId?: string) {
    const { user, loading: authLoading } = useAuth();

    // Fetch Guild Info (which includes calculated permission_level)
    const { data: guild, isLoading: guildLoading, error: guildError } = useQuery({
        queryKey: ['guild', guildId],
        queryFn: () => guildId ? apiClient.getGuild(guildId) : null,
        enabled: !!guildId && !!user,
        retry: 1, // Don't retry too much on 403
    });

    const currentPermissionLevel = (() => {
        if (!user) return PermissionLevel.PUBLIC;

        // Platform Admin Override
        if (user.is_admin) return PermissionLevel.DEVELOPER;

        // Global Context (No Guild ID) — fall back to the highest permission
        // the user had in their last active guild so that global pages
        // (e.g. /dashboard/bot-health) respect the user's real role.
        if (!guildId) {
            if (typeof window !== 'undefined') {
                const cached = parseInt(sessionStorage.getItem(PERM_CACHE_KEY) ?? '', 10);
                if (!isNaN(cached) && cached >= PermissionLevel.USER) {
                    return cached as PermissionLevel;
                }
            }
            return PermissionLevel.USER;
        }

        // Valid Guild Context but guild not loaded yet
        if (!guild) return PermissionLevel.PUBLIC;

        // Map backend string to Level
        // Backend returns: "owner", "administrator", "ADMIN", "USER", "LEVEL_2"
        const pLevel = (guild as any).permission_level;

        if (pLevel === 'owner') return PermissionLevel.OWNER;
        if (pLevel === 'administrator') return PermissionLevel.ADMINISTRATOR;
        if (pLevel === 'admin' || pLevel === 'ADMIN') return PermissionLevel.ADMINISTRATOR;
        if (pLevel === 'user' || pLevel === 'USER') return PermissionLevel.USER;
        if (pLevel === 'level_2' || pLevel === 'LEVEL_2') return PermissionLevel.USER;

        return PermissionLevel.USER; // Fallback for guild members
    })();

    // Cache the user's permission level whenever we have a guild context.
    // This allows global pages (no guildId) to use the cached level.
    useEffect(() => {
        if (guildId && guild && currentPermissionLevel >= PermissionLevel.USER) {
            if (typeof window !== 'undefined') {
                sessionStorage.setItem(PERM_CACHE_KEY, String(currentPermissionLevel));
            }
        }
    }, [guildId, guild, currentPermissionLevel]);

    const hasAccess = (requiredLevel: PermissionLevel) => {
        if (requiredLevel <= PermissionLevel.PUBLIC_DATA) return true;
        if (!user) return false;
        return currentPermissionLevel >= requiredLevel;
    };

    return {
        permissionLevel: currentPermissionLevel,
        hasAccess,
        loading: authLoading || (!!guildId && guildLoading),
        error: guildError,
        guild
    };
}
