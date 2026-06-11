'use client';

import { useTranslation } from '@/lib/i18n';
import { Home } from 'lucide-react';

export default function NotFound() {
  const { t } = useTranslation();
  return (
    // Full-screen overlay (z above the sticky header, which is z-50) so the 404 is
    // chromeless — the platform header doesn't show, matching the welcome page.
    <div className="fixed inset-0 z-[60] overflow-auto flex flex-col items-center justify-center bg-background px-4 py-12 text-center">
      {/* World Cup–themed 404 art (public/404.webp). */}
      <img
        src="/404.webp"
        alt=""
        className="w-full max-w-md rounded-2xl shadow-lg shadow-black/20 mb-8"
      />
      <h1 className="text-6xl font-extrabold text-foreground tracking-tight mb-2">404</h1>
      <h2 className="text-xl font-semibold text-foreground mb-2">{t('notFound.title')}</h2>
      <p className="text-muted-foreground max-w-md mb-8">{t('notFound.message')}</p>
      <a
        href="/"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors"
      >
        <Home className="w-4 h-4" />
        {t('notFound.backHome')}
      </a>
    </div>
  );
}
