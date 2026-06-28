'use client';

// The "how points work" explainer was removed. This route is no longer linked from
// anywhere; kept as a thin page (just a link back to the hub) so /activity/reglas does
// not 404 for an old bookmark.
import { useTranslation } from '@/lib/i18n';
import { withActivityPage } from '@/lib/components/with-activity-page';

function RulesActivity() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <a href="/activity/inicio" className="inline-block text-sm text-muted-foreground hover:text-foreground">← {t('fixturesActivity.navHome')}</a>
    </div>
  );
}

export default withActivityPage(RulesActivity);
