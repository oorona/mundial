'use client';

import { useTranslation } from '@/lib/i18n';
import { ScrollText } from 'lucide-react';

// Joke Terms of Service ("you may not watch the matches") — pure fun, not legal text.
// Public page: no login required, linked from the dashboard footer and shareable.
export default function TosPage() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <ScrollText className="h-8 w-8 shrink-0 text-primary" aria-hidden="true" />
          <h1 className="text-xl font-bold text-foreground">{t('fixturesActivity.tosTitle')}</h1>
        </div>
        <p className="mt-4 text-muted-foreground">{t('fixturesActivity.tosIntro')}</p>
        <ul className="mt-4 space-y-3 text-sm text-foreground">
          {[1, 2, 3, 4, 5, 6].map((n) => <li key={n}>{t(`fixturesActivity.tos${n}`)}</li>)}
        </ul>
        <p className="mt-5 text-sm text-muted-foreground">{t('fixturesActivity.tosAccept')}</p>
        <p className="mt-5 text-xs italic text-muted-foreground">{t('fixturesActivity.tosDisclaimer')}</p>
      </div>
    </main>
  );
}
