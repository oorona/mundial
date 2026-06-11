'use client';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/app/api-client';
import { usePlugins } from '@/app/plugins';
import { Activity, BarChart2, BookOpen, BrainCircuit, CalendarDays, Database, FileText, Gauge, Globe, Globe2, Info, Lock, Medal, Radio, Settings, Settings2, Shield, Target, Terminal, Trophy, Users } from 'lucide-react';
import { usePermissions } from '@/lib/hooks/use-permissions';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

// Per-card default visibility for the owner-configurable dashboard cards.
// MUST mirror CONFIGURABLE_CARDS in
// app/dashboard/[guildId]/card-visibility/page.tsx. Cards listed here are
// hidden/shown per the guild's saved card-visibility map (with these as the
// fallback when a card has no saved override); cards NOT listed are always
// shown (subject to permission level).
// Cards an owner can show/hide for their members — ONLY cards below Owner level.
// Owner- and Developer-level cards (e.g. Permissions, Audit Logs) are never
// member-configurable and so are not listed here.
const CARD_VISIBILITY_DEFAULTS: Record<string, boolean> = {
  'bot-overview': false,
  'command-reference': true,
  'bot-settings': true,
  'bot-health': true,
};

// Joke Terms of Service ("you may not watch the matches") — pure fun, not legal text.
// Full text lives at /tos (public, shareable); this footer just links to it.
function JokeTos() {
  const { t } = useTranslation();
  return (
    <footer className="mt-10 pb-4 text-center">
      <a href="/tos" className="text-xs text-muted-foreground underline-offset-2 hover:underline">
        {t('fixturesActivity.tosLink')}
      </a>
    </footer>
  );
}

function DashboardContent() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { navItems: pluginNavItems } = usePlugins();

  const [guilds, setGuilds] = useState<any[]>([]);
  const [loadingGuilds, setLoadingGuilds] = useState(true);
  const [cardVisibility, setCardVisibility] = useState<Record<string, boolean>>({});

  // Determine Guild ID
  // Priority: URL Param > LocalStorage > Default > First in List
  const paramGuildId = searchParams.get('guild_id');
  const [activeGuildId, setActiveGuildId] = useState<string | null>(null);

  // Permission Hook
  const { hasAccess, permissionLevel, loading: permLoading } = usePermissions(activeGuildId || undefined);

  // First-time login detection: redirect to Account Settings only if the user has
  // never saved a language preference.
  //
  // IMPORTANT: check the AUTHORITATIVE source (GET /users/me/settings, which reads
  // User.preferences from the DB), NOT `user.preferences` from /auth/me — the
  // current-user/session payload does not include preferences, so it is always
  // empty and would re-prompt on every login even after the user saved settings.
  // The sessionStorage flag avoids re-checking on every dashboard mount within a
  // session (also set by the account page on save/skip).
  useEffect(() => {
    if (authLoading || !user) return;
    if (typeof window !== 'undefined' &&
        sessionStorage.getItem('firstLoginSetupDone') === '1') return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.getUserSettings();
        if (cancelled) return;
        if (data?.settings?.language) {
          // Already configured — don't prompt, and skip re-checks this session.
          sessionStorage.setItem('firstLoginSetupDone', '1');
        } else {
          router.push('/dashboard/account?firstLogin=1');
        }
      } catch {
        // Don't trap the user in a redirect loop if the settings fetch fails.
      }
    })();
    return () => { cancelled = true; };
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) {
      setLoadingGuilds(false);
      return;
    }

    apiClient.getGuilds().then(data => {
      setGuilds(data);
      const activeGuilds = data.filter((g: any) => !g.bot_not_added);
      if (activeGuilds.length === 0) {
        router.push('/welcome');
        return;
      }

      // Resolve Active Guild
      let resolvedId = null;
      if (paramGuildId && activeGuilds.find((g: any) => g.id === paramGuildId)) {
        resolvedId = paramGuildId;
      } else {
        const stored = localStorage.getItem('lastGuildId');
        if (stored && activeGuilds.find((g: any) => g.id === stored)) {
          resolvedId = stored;
        } else if (user.preferences?.default_guild_id && activeGuilds.find((g: any) => g.id === user.preferences.default_guild_id)) {
          resolvedId = user.preferences.default_guild_id;
        } else {
          resolvedId = activeGuilds[0].id;
        }
      }

      if (resolvedId) {
        setActiveGuildId(resolvedId);
      }
    }).catch(err => {
      console.error("Failed to fetch guilds:", err);
    }).finally(() => {
      setLoadingGuilds(false);
    });
  }, [user, paramGuildId]);

  // Load the guild's owner-configured card visibility. Falls back to defaults
  // on any error (e.g. a backend that predates the card-visibility endpoint).
  useEffect(() => {
    if (!activeGuildId) return;
    apiClient.getCardVisibility(activeGuildId)
      .then(setCardVisibility)
      .catch(() => setCardVisibility({}));
  }, [activeGuildId]);

  if (authLoading || loadingGuilds || permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-muted-foreground animate-pulse">{t('common.loadingDashboard')}</p>
        </div>
      </div>
    );
  }

  if (!user) {
    router.push('/welcome');
    return null;
  }

  // Define Cards
  interface DashboardCard {
    id: string;
    title: string;
    description: string;
    icon: any;
    href: string;
    level: PermissionLevel;
    color: string;
    bgColor: string;
    borderColor: string;
    isAdminOnly?: boolean;
  }

  const cards: DashboardCard[] = [
    {
      id: 'bot-overview',
      title: t('dashboard.cardBotOverviewTitle'),
      description: t('dashboard.cardBotOverviewDesc'),
      icon: Globe,
      href: '/welcome?noRedirect=1',
      level: PermissionLevel.PUBLIC,
      color: 'text-slate-400',
      bgColor: 'bg-slate-500/10',
      borderColor: 'group-hover:border-slate-500/50',
      isAdminOnly: false
    },
    {
      id: 'command-reference',
      title: t('dashboard.cardCommandRefTitle'),
      description: t('dashboard.cardCommandRefDesc'),
      icon: BookOpen,
      href: '/commands',
      level: PermissionLevel.PUBLIC_DATA,
      color: 'text-sky-400',
      bgColor: 'bg-sky-500/10',
      borderColor: 'group-hover:border-sky-500/50',
      isAdminOnly: false,
    },
    {
      id: 'bot-settings',
      title: t('dashboard.cardBotSettingsTitle'),
      description: t('dashboard.cardBotSettingsDesc'),
      icon: Settings,
      href: `/dashboard/${activeGuildId}/settings`,
      level: PermissionLevel.ADMINISTRATOR,
      color: 'text-blue-500',
      bgColor: 'bg-blue-500/10',
      borderColor: 'group-hover:border-blue-500/50',
      isAdminOnly: false,
    },
    {
      id: 'permissions',
      title: t('dashboard.cardPermissionsTitle'),
      description: t('dashboard.cardPermissionsDesc'),
      icon: Shield,
      href: `/dashboard/${activeGuildId}/permissions`,
      level: PermissionLevel.OWNER,
      color: 'text-purple-500',
      bgColor: 'bg-purple-500/10',
      borderColor: 'group-hover:border-purple-500/50',
      isAdminOnly: false
    },
    {
      id: 'bot-health',
      title: t('dashboard.cardBotHealthTitle'),
      description: t('dashboard.cardBotHealthDesc'),
      icon: Activity,
      href: `/dashboard/bot-health`,
      level: PermissionLevel.AUTHORIZED,
      color: 'text-green-500',
      bgColor: 'bg-green-500/10',
      borderColor: 'group-hover:border-green-500/50',
      isAdminOnly: false
    },
    {
      id: 'card-visibility',
      title: t('dashboard.cardCardVisibilityTitle'),
      description: t('dashboard.cardCardVisibilityDesc'),
      icon: Settings2,
      href: `/dashboard/${activeGuildId}/card-visibility`,
      level: PermissionLevel.OWNER,
      color: 'text-orange-500',
      bgColor: 'bg-orange-500/10',
      borderColor: 'group-hover:border-orange-500/50',
      isAdminOnly: false
    },
    {
      id: 'submissions',
      title: t('dashboard.cardSubmissionsTitle'),
      description: t('dashboard.cardSubmissionsDesc'),
      icon: Users,
      href: `/dashboard/${activeGuildId}/submissions`,
      level: PermissionLevel.OWNER,
      color: 'text-amber-500',
      bgColor: 'bg-amber-500/10',
      borderColor: 'group-hover:border-amber-500/50',
      isAdminOnly: false
    },
    {
      id: 'daily_scores',
      title: t('dailyScores.title'),
      description: t('dailyScores.description'),
      icon: CalendarDays,
      href: `/dashboard/${activeGuildId}/daily-scores`,
      level: PermissionLevel.OWNER,
      color: 'text-rose-500',
      bgColor: 'bg-rose-500/10',
      borderColor: 'group-hover:border-rose-500/50',
      isAdminOnly: false
    },
    {
      id: 'audit-logs',
      title: t('dashboard.cardAuditLogsTitle'),
      description: t('dashboard.cardAuditLogsDesc'),
      icon: FileText,
      href: `/dashboard/${activeGuildId}/audit-logs`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-orange-500',
      bgColor: 'bg-orange-500/10',
      borderColor: 'group-hover:border-orange-500/50',
      isAdminOnly: false
    },
    {
      id: 'ai-analytics',
      title: t('dashboard.cardAiAnalyticsTitle'),
      description: t('dashboard.cardAiAnalyticsDesc'),
      icon: BarChart2,
      href: `/dashboard/ai-analytics`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-cyan-500',
      bgColor: 'bg-cyan-500/10',
      borderColor: 'group-hover:border-cyan-500/50',
      isAdminOnly: true
    },
    {
      id: 'system-config',
      title: t('dashboard.cardSystemConfigTitle'),
      description: t('dashboard.cardSystemConfigDesc'),
      icon: Settings2,
      href: `/dashboard/config`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-red-500',
      bgColor: 'bg-red-500/10',
      borderColor: 'group-hover:border-red-500/50',
      isAdminOnly: true
    },
    {
      id: 'database',
      title: t('dashboard.cardDatabaseTitle'),
      description: t('dashboard.cardDatabaseDesc'),
      icon: Database,
      href: `/dashboard/database`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-yellow-600',
      bgColor: 'bg-yellow-500/10',
      borderColor: 'group-hover:border-yellow-600/50',
      isAdminOnly: true
    },
    {
      id: 'instrumentation',
      title: t('dashboard.cardInstrumentationTitle'),
      description: t('dashboard.cardInstrumentationDesc'),
      icon: Gauge,
      href: `/dashboard/instrumentation`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-orange-500',
      bgColor: 'bg-orange-500/10',
      borderColor: 'group-hover:border-orange-500/50',
      isAdminOnly: true
    },
    {
      id: 'llm-configs',
      title: t('dashboard.cardLlmConfigsTitle'),
      description: t('dashboard.cardLlmConfigsDesc'),
      icon: BrainCircuit,
      href: `/dashboard/llm-configs`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-violet-500',
      bgColor: 'bg-violet-500/10',
      borderColor: 'group-hover:border-violet-500/50',
      isAdminOnly: true
    },
    {
      id: 'worldcup',
      title: t('worldcup.title'),
      description: t('worldcup.description'),
      icon: Trophy,
      href: `/dashboard/${activeGuildId}/worldcup`,
      level: PermissionLevel.USER,
      color: 'text-amber-500',
      bgColor: 'bg-amber-500/10',
      borderColor: 'group-hover:border-amber-500/50',
      isAdminOnly: false,
    },
    {
      id: 'fixtures',
      title: t('fixtures.title'),
      description: t('fixtures.description'),
      icon: Globe2,
      href: `/dashboard/${activeGuildId}/fixtures`,
      level: PermissionLevel.USER,
      color: 'text-sky-500',
      bgColor: 'bg-sky-500/10',
      borderColor: 'group-hover:border-sky-500/50',
      isAdminOnly: false,
    },
    {
      id: 'predictions',
      title: t('predictions.title'),
      description: t('predictions.description'),
      icon: Target,
      href: `/dashboard/${activeGuildId}/predictions`,
      level: PermissionLevel.USER,
      color: 'text-emerald-500',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'group-hover:border-emerald-500/50',
      isAdminOnly: false,
    },
    {
      id: 'leaderboard',
      title: t('leaderboard.title'),
      description: t('leaderboard.description'),
      icon: Medal,
      href: `/dashboard/${activeGuildId}/leaderboard`,
      level: PermissionLevel.USER,
      color: 'text-yellow-500',
      bgColor: 'bg-yellow-500/10',
      borderColor: 'group-hover:border-yellow-500/50',
      isAdminOnly: false,
    },
    {
      id: 'live_tracker',
      title: t('liveTracker.title'),
      description: t('liveTracker.description'),
      icon: Radio,
      href: `/dashboard/${activeGuildId}/live-tracker`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-red-500',
      bgColor: 'bg-red-500/10',
      borderColor: 'group-hover:border-red-500/50',
      isAdminOnly: true,
    },
    {
      id: 'cog-manager',
      title: t('dashboard.cardCogManagerTitle'),
      description: t('dashboard.cardCogManagerDesc'),
      icon: Terminal,
      href: `/dashboard/cogs`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-slate-400',
      bgColor: 'bg-slate-500/10',
      borderColor: 'group-hover:border-slate-500/50',
      isAdminOnly: true,
    },
    {
      id: 'ai-analyst',
      title: t('aiPlayer.cardTitle'),
      description: t('aiPlayer.cardDesc'),
      icon: BrainCircuit,
      href: `/dashboard/platform/ai-analyst`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-fuchsia-500',
      bgColor: 'bg-fuchsia-500/10',
      borderColor: 'group-hover:border-fuchsia-500/50',
      isAdminOnly: true,
    },
    {
      id: 'platform-status',
      title: t('dashboard.cardPlatformStatusTitle'),
      description: t('dashboard.cardPlatformStatusDesc'),
      icon: Activity,
      href: `/dashboard/platform-status`,
      level: PermissionLevel.DEVELOPER,
      color: 'text-teal-500',
      bgColor: 'bg-teal-500/10',
      borderColor: 'group-hover:border-teal-500/50',
      isAdminOnly: true
    },
    // Plugins — titles come from plugin definitions; descriptions are translated
    ...pluginNavItems.map((plugin: any) => ({
      id: `plugin-${plugin.id || plugin.name}`,
      title: plugin.name,
      description: t('dashboard.cardPluginDesc'),
      icon: plugin.icon || Terminal,
      href: plugin.href.replace('[guildId]', activeGuildId || ''),
      level: plugin.level || PermissionLevel.USER,
      color: 'text-orange-500',
      bgColor: 'bg-orange-500/10',
      borderColor: 'group-hover:border-orange-500/50',
      isAdminOnly: plugin.adminOnly
    }))
  ];

  // Filter Cards
  const visibleCards = cards.filter(card => {
    if (card.isAdminOnly && !user.is_admin) return false;
    if (!hasAccess(card.level)) return false;
    // Owner-configurable visibility (see /dashboard/[guildId]/card-visibility).
    // Built-in below-owner cards have a curated default; plugin cards (and any
    // other below-owner card) are also owner-controllable, defaulting to visible.
    if (card.id in CARD_VISIBILITY_DEFAULTS) {
      return cardVisibility[card.id] ?? CARD_VISIBILITY_DEFAULTS[card.id];
    }
    if (card.level < PermissionLevel.OWNER) {
      return cardVisibility[card.id] ?? true;
    }
    return true;
  });

  const activeGuild = guilds.find(g => g.id === activeGuildId);

  return (
    <div className="max-w-7xl mx-auto space-y-12">

      {/* Hero / Welcome Section */}
      <div className="text-center space-y-4 py-8">
        <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent">
          {activeGuild
            ? t('dashboard.manageServer', { serverName: activeGuild.name })
            : t('dashboard.welcomeUser', { username: user.username })}
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          {t('dashboard.selectTool')}
        </p>
        {activeGuild && (
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-muted/50 border border-border text-sm text-muted-foreground">
            <span>{t('dashboard.currentPermission')}</span>
            <span className="font-semibold text-foreground">
              {user.is_admin ? t('dashboard.permDeveloper') :
                permissionLevel === PermissionLevel.OWNER ? t('dashboard.permOwner') :
                  permissionLevel === PermissionLevel.ADMINISTRATOR ? t('dashboard.permAdministrator') :
                    permissionLevel === PermissionLevel.AUTHORIZED ? t('dashboard.permAuthorized') :
                      permissionLevel === PermissionLevel.USER ? t('dashboard.permUser') : t('dashboard.permGuest')
              }
            </span>
          </div>
        )}
      </div>

      {/* Grouped Card Sections */}
      {(() => {
        interface LevelMeta { label: string; description: string; accentText: string; borderAccent: string; sectionBg: string; badge: string }
        const levelMeta: Record<number, LevelMeta> = {
          0: { label: t('dashboard.sectionPublicLabel'),     description: t('dashboard.sectionPublicDesc'),     accentText: 'text-slate-400',   borderAccent: 'border-slate-500/50',   sectionBg: 'bg-slate-500/5',   badge: 'bg-slate-500/20 text-slate-300' },
          1: { label: t('dashboard.sectionPublicDataLabel'), description: t('dashboard.sectionPublicDataDesc'), accentText: 'text-sky-400',     borderAccent: 'border-sky-500/50',     sectionBg: 'bg-sky-500/5',     badge: 'bg-sky-500/20 text-sky-300' },
          2: { label: t('dashboard.sectionUserLabel'),       description: t('dashboard.sectionUserDesc'),       accentText: 'text-emerald-400', borderAccent: 'border-emerald-500/50', sectionBg: 'bg-emerald-500/5', badge: 'bg-emerald-500/20 text-emerald-300' },
          3: { label: t('dashboard.sectionAuthorizedLabel'),     description: t('dashboard.sectionAuthorizedDesc'),     accentText: 'text-blue-400',    borderAccent: 'border-blue-500/50',    sectionBg: 'bg-blue-500/5',    badge: 'bg-blue-500/20 text-blue-300' },
          4: { label: t('dashboard.sectionAdministratorLabel'), description: t('dashboard.sectionAdministratorDesc'), accentText: 'text-purple-400',  borderAccent: 'border-purple-500/50',  sectionBg: 'bg-purple-500/5',  badge: 'bg-purple-500/20 text-purple-300' },
          5: { label: t('dashboard.sectionOwnerLabel'),          description: t('dashboard.sectionOwnerDesc'),          accentText: 'text-orange-500',  borderAccent: 'border-orange-500/50',  sectionBg: 'bg-orange-500/5',  badge: 'bg-orange-500/20 text-orange-500' },
          6: { label: t('dashboard.sectionDeveloperLabel'),      description: t('dashboard.sectionDeveloperDesc'),      accentText: 'text-red-400',     borderAccent: 'border-red-500/50',     sectionBg: 'bg-red-500/5',     badge: 'bg-red-500/20 text-red-300' },
        };

        const cardsByLevel = visibleCards.reduce((acc, card) => {
          if (!acc[card.level]) acc[card.level] = [];
          acc[card.level].push(card);
          return acc;
        }, {} as Record<number, typeof visibleCards>);

        const sortedLevels = Object.keys(cardsByLevel).map(Number).sort((a, b) => b - a);
        const showSectionHeaders = sortedLevels.length > 1;

        return (
          <div className="space-y-10">
            {sortedLevels.map(level => {
              const meta = levelMeta[level] ?? { label: '', description: '', accentText: 'text-muted-foreground', borderAccent: 'border-border', sectionBg: 'bg-muted/5', badge: 'bg-muted text-muted-foreground' };
              const levelCards = [...cardsByLevel[level]].sort((a, b) => a.title.localeCompare(b.title));
              return (
                <div key={level} className="space-y-4">
                  {showSectionHeaders && (
                    <div className={`flex items-center gap-4 pl-4 border-l-4 ${meta.borderAccent}`}>
                      {/* Only the section name shows; the category explanation is a hover tooltip. */}
                      <h2
                        title={meta.description}
                        className={`text-base font-semibold tracking-wide uppercase ${meta.accentText} inline-flex items-center gap-1.5 cursor-help`}
                      >
                        {meta.label}
                        <Info size={13} className="opacity-50" />
                      </h2>
                    </div>
                  )}
                  <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-5 rounded-2xl ${showSectionHeaders ? meta.sectionBg : ''}`}>
                    {levelCards.map((card, index) => (
                      <div
                        key={index}
                        onClick={() => {
                          apiClient.trackCardClick(card.id, activeGuildId);
                          router.push(card.href);
                        }}
                        className={`group relative bg-card border border-border ${card.borderColor} rounded-xl p-8 cursor-pointer transition-all duration-300 hover:shadow-lg hover:-translate-y-1 flex flex-col h-full`}
                      >
                        <div className={`absolute top-6 right-6 p-3 rounded-xl ${card.bgColor} ${card.color} transition-colors group-hover:scale-110 duration-300`}>
                          <card.icon size={28} />
                        </div>

                        <div className="mt-4 mb-auto pr-16">
                          <h3 className="text-2xl font-bold mb-3 group-hover:text-primary transition-colors">{card.title}</h3>
                          <p className="text-muted-foreground leading-relaxed">{card.description}</p>
                        </div>

                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}

      {visibleCards.length === 0 && (
        <div className="text-center py-20 bg-muted/20 rounded-xl border border-dashed border-border">
          <Lock className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
          <h3 className="text-xl font-medium mb-2">{t('dashboard.accessRestricted')}</h3>
          <p className="text-muted-foreground">
            {t('dashboard.noAccessBody')}<br />
            {t('dashboard.currentAccessLevel', { level: String(permissionLevel) })}
          </p>
        </div>
      )}
      <JokeTos />
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-muted-foreground animate-pulse">{/* loading */}</p>
        </div>
      </div>
    }>
      <DashboardContent />
    </Suspense>
  );
}
