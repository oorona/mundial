'use client';

import { useTranslation } from '@/lib/i18n';
import {
  Trophy, Target, BarChart2, Radio, Bot, Gamepad2,
  ShieldCheck, Lock, Check, X, ArrowLeft,
} from 'lucide-react';

export default function AboutPage() {
  const { t } = useTranslation();

  const features = [
    { icon: Target, title: t('about.fPredict'), desc: t('about.fPredictDesc') },
    { icon: BarChart2, title: t('about.fLeaderboard'), desc: t('about.fLeaderboardDesc') },
    { icon: Radio, title: t('about.fLive'), desc: t('about.fLiveDesc') },
    { icon: Bot, title: t('about.fAI'), desc: t('about.fAIDesc') },
    { icon: Gamepad2, title: t('about.fActivity'), desc: t('about.fActivityDesc') },
  ];

  const perms = [
    { name: t('botPerms.viewChannel'), why: t('about.permViewChannelWhy') },
    { name: t('botPerms.sendMessages'), why: t('about.permSendMessagesWhy') },
    { name: t('botPerms.embedLinks'), why: t('about.permEmbedLinksWhy') },
    { name: t('botPerms.readHistory'), why: t('about.permReadHistoryWhy') },
    { name: t('botPerms.createThreads'), why: t('about.permCreateThreadsWhy') },
    { name: t('botPerms.sendInThreads'), why: t('about.permSendInThreadsWhy') },
    { name: t('botPerms.manageThreads'), why: t('about.permManageThreadsWhy'), optional: true },
    { name: t('botPerms.mentionRoles'), why: t('about.permMentionRolesWhy'), optional: true },
  ];

  const never = [
    t('about.neverAdmin'),
    t('about.neverKickBan'),
    t('about.neverManage'),
    t('about.neverDelete'),
    t('about.neverDms'),
  ];

  return (
    <div className="min-h-screen bg-background">
      <main className="max-w-3xl mx-auto px-4 py-12">
        <a href="/welcome" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-8">
          <ArrowLeft className="w-4 h-4" /> {t('about.backHome')}
        </a>

        <div className="flex items-center gap-3 mb-3">
          <Trophy className="w-8 h-8 text-amber-500" />
          <h1 className="text-3xl font-extrabold text-foreground">{t('about.title')}</h1>
        </div>
        <p className="text-lg text-muted-foreground mb-10">{t('about.intro')}</p>

        {/* Features */}
        <h2 className="text-xl font-bold text-foreground mb-4">{t('about.featuresTitle')}</h2>
        <div className="grid sm:grid-cols-2 gap-4 mb-12">
          {features.map((f, i) => {
            const Icon = f.icon;
            return (
              <div key={i} className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon className="w-5 h-5 text-primary" />
                  <h3 className="font-semibold text-foreground">{f.title}</h3>
                </div>
                <p className="text-sm text-muted-foreground">{f.desc}</p>
              </div>
            );
          })}
        </div>

        {/* Permissions */}
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck className="w-6 h-6 text-emerald-500" />
          <h2 className="text-xl font-bold text-foreground">{t('about.permsTitle')}</h2>
        </div>

        {/* Least-privilege trust callout */}
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 mb-5">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck className="w-5 h-5 text-emerald-500 shrink-0" />
            <h3 className="font-semibold text-foreground">{t('about.leastPrivilege')}</h3>
          </div>
          <p className="text-sm text-muted-foreground">{t('about.leastPrivilegeText')}</p>
        </div>

        <p className="text-sm text-muted-foreground mb-4">{t('about.permsIntro')}</p>
        <ul className="space-y-2 mb-10">
          {perms.map((p, i) => (
            <li key={i} className="flex items-start gap-3 rounded-lg border border-border bg-card px-4 py-3">
              <Check className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <div className="text-sm">
                <span className="font-semibold text-foreground">{p.name}</span>
                {p.optional && (
                  <span className="ml-2 text-[10px] uppercase tracking-wide text-muted-foreground">({t('about.optional')})</span>
                )}
                <p className="text-muted-foreground mt-0.5">{p.why}</p>
              </div>
            </li>
          ))}
        </ul>

        {/* What it never asks for */}
        <div className="rounded-xl border border-border bg-card p-5 mb-10">
          <h3 className="font-semibold text-foreground mb-3">{t('about.neverTitle')}</h3>
          <ul className="space-y-2">
            {never.map((n, i) => (
              <li key={i} className="flex items-center gap-2 text-sm text-muted-foreground">
                <X className="w-4 h-4 text-red-500 shrink-0" />
                {n}
              </li>
            ))}
          </ul>
        </div>

        {/* Privacy / data */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 mb-1">
            <Lock className="w-5 h-5 text-primary shrink-0" />
            <h3 className="font-semibold text-foreground">{t('about.privacyTitle')}</h3>
          </div>
          <p className="text-sm text-muted-foreground">{t('about.privacyText')}</p>
        </div>

        <div className="mt-10">
          <a href="/welcome" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="w-4 h-4" /> {t('about.backHome')}
          </a>
        </div>
      </main>
    </div>
  );
}
