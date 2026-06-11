# Adding Frontend Pages

This guide explains how to add new dashboard pages to the Next.js frontend.

## Overview

The frontend uses:
- **Next.js 16** with App Router
- **TypeScript** for type safety
- **Tailwind CSS** for styling (semantic tokens only — see Design System below)
- **React Hooks** for state management

## The Golden Rule — `withPermission`

**Every page inside `frontend/app/dashboard/` MUST be exported via `withPermission`.**

This HOC:
1. Enforces the correct permission level (redirects if the user lacks access)
2. Automatically injects the `← Dashboard` breadcrumb link at the top of every page

```tsx
// ✅ CORRECT — always do this
function MyFeaturePage() {
    return <div>...</div>;
}
export default withPermission(MyFeaturePage, PermissionLevel.AUTHORIZED);

// ❌ WRONG — never do this inside /dashboard/
export default function MyFeaturePage() {
    return <div>...</div>;
}
```

## Step 1: Create a New Page

Pages for guild-specific features go in `frontend/app/dashboard/[guildId]/your-feature/page.tsx`.

### Basic Page

```tsx
// frontend/app/dashboard/[guildId]/music/page.tsx
'use client';

import { useParams } from 'next/navigation';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function MusicPage() {
    const params = useParams();
    const guildId = params.guildId as string;

    return (
        <div className="max-w-4xl mx-auto p-8 space-y-6">
            <h1 className="text-3xl font-bold text-foreground">Music Settings</h1>
            <p className="text-muted-foreground">Configure music features for this server.</p>
        </div>
    );
}

export default withPermission(MusicPage, PermissionLevel.AUTHORIZED);
```

### Page with Data Fetching

```tsx
'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function MusicPage() {
    const params = useParams();
    const guildId = params.guildId as string;
    const [settings, setSettings] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!guildId) return;
        apiClient.get(`/guilds/${guildId}/music`)
            .then(setSettings)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, [guildId]);

    if (loading) {
        return (
            <div className="flex items-center justify-center p-12">
                <span className="text-muted-foreground">Loading...</span>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto p-8 space-y-6">
            <h1 className="text-3xl font-bold text-foreground">Music Settings</h1>
            {/* your content */}
        </div>
    );
}

export default withPermission(MusicPage, PermissionLevel.AUTHORIZED);
```

## Step 2: Making API Calls from Plugin Pages

Use the generic methods on `apiClient` — **do not add named methods to `api-client.ts`**, that file is core infrastructure:

```typescript
import { apiClient } from '@/app/api-client';

// Always provide a type parameter — omitting it gives `unknown` and TypeScript
// will reject any property access on the result.

// GET
const data = await apiClient.get<{ items: MyItem[] }>(`/guilds/${guildId}/myplugin/items`);

// POST
const result = await apiClient.post<{ id: string }>(`/guilds/${guildId}/myplugin/items`, payload);

// PUT
await apiClient.put<void>(`/guilds/${guildId}/myplugin/items/123`, payload);

// DELETE
await apiClient.delete<void>(`/guilds/${guildId}/myplugin/items/123`);
```

> **The base URL already includes `/api/v1`.** Do NOT write `/api/v1/guilds/...` — that produces a double-prefix (`/api/v1/api/v1/guilds/...`) and every request will 404.
>
> ```typescript
> // ✅ Correct
> apiClient.get<T>(`/guilds/${guildId}/myplugin/settings`)
>
> // ❌ Wrong — double /api/v1/
> apiClient.get<T>(`/api/v1/guilds/${guildId}/myplugin/settings`)
> ```
>
> The validator will reject any path starting with `/api/`.

All four methods route through the shared auth interceptor (Bearer token + 401/403 handling). Never use raw `fetch()` or `axios` directly — the validator will reject them. Untyped calls (no `<T>`) will also be rejected by the validator.

## Step 3: Register the Navigation Card

Add an entry to the `cards` array in `frontend/app/page.tsx`:

```tsx
{
    id: 'music',
    title: 'Music',
    description: 'Configure music playback and queuing for your server.',
    icon: Music2,           // from lucide-react
    href: `/dashboard/${activeGuildId}/music`,
    level: PermissionLevel.AUTHORIZED,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'group-hover:border-emerald-500/50',
    isAdminOnly: false,
},
```

Cards are grouped by `level` and displayed highest-level first (so developer/admin tools appear at the top for users who can see them).

## Step 4: Create Reusable Components (Optional)

Put shared components in `frontend/lib/components/` or inline them in the page:

```tsx
// frontend/lib/components/SettingsCard.tsx
interface SettingsCardProps {
    title: string;
    description: string;
    children: React.ReactNode;
}

export function SettingsCard({ title, description, children }: SettingsCardProps) {
    return (
        <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-semibold text-foreground mb-1">{title}</h2>
            <p className="text-sm text-muted-foreground mb-4">{description}</p>
            {children}
        </div>
    );
}
```

## Form Handling Pattern

```tsx
'use client';

import { useState } from 'react';
import { Save } from 'lucide-react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function MusicSettingsPage() {
    const params = useParams();
    const guildId = params.guildId as string;
    const [volume, setVolume] = useState(100);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<string | null>(null);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);
        try {
            await apiClient.post(`/guilds/${guildId}/music`, { volume });
            setMessage('Settings saved!');
        } catch {
            setMessage('Failed to save settings.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="max-w-2xl mx-auto p-8">
            <h1 className="text-3xl font-bold mb-6 text-foreground">Music Settings</h1>

            {message && (
                <div className="p-4 rounded-lg mb-6 bg-primary/10 text-primary">{message}</div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
                <div>
                    <label className="block text-sm font-medium mb-2 text-foreground">
                        Default Volume
                    </label>
                    <input
                        type="number"
                        value={volume}
                        onChange={(e) => setVolume(Number(e.target.value))}
                        className="w-full bg-background border border-input rounded-lg p-3 text-foreground focus:ring-2 focus:ring-ring"
                        min={0} max={200}
                    />
                </div>

                <button
                    type="submit"
                    disabled={saving}
                    className="w-full bg-primary hover:bg-primary/90 text-primary-foreground py-3 rounded-lg disabled:opacity-50 flex items-center justify-center gap-2"
                >
                    {saving ? (
                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                        <Save className="w-5 h-5" />
                    )}
                    {saving ? 'Saving…' : 'Save Settings'}
                </button>
            </form>
        </div>
    );
}

export default withPermission(MusicSettingsPage, PermissionLevel.AUTHORIZED);
```

## Real-time / Polling Pattern

```tsx
useEffect(() => {
    if (!guildId) return;
    const id = setInterval(() => {
        apiClient.get(`/guilds/${guildId}/music`).then(setSettings).catch(() => {});
    }, 30000);
    return () => clearInterval(id);
}, [guildId]);
```

## Design System — Semantic Tokens

**Never use hardcoded colors.** Always use these tokens so pages work in both light and dark themes:

```tsx
// ✅ Correct
<div className="bg-card border border-border text-foreground">
<p className="text-muted-foreground">
<button className="bg-primary text-primary-foreground">
<span className="text-destructive">

// ❌ Wrong
<div className="bg-white text-black border-gray-200">
<p className="text-gray-500">
<button className="bg-blue-600 text-white">
```

Common layout patterns:
```tsx
<div className="max-w-4xl mx-auto p-8 space-y-6">   {/* Page container */}
<div className="bg-card rounded-xl border border-border p-6">  {/* Card/panel */}
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">  {/* Responsive grid */}
<input className="w-full bg-background border border-input rounded-lg p-3 text-foreground focus:ring-2 focus:ring-ring">
```

## Permission Levels Quick Reference

| Level | Name | Use for |
| :---- | :--- | :------ |
| 0 | PUBLIC | Unauthenticated pages (landing, login) |
| 1 | PUBLIC_DATA | Read-only public data, no login needed |
| 2 | USER | Any logged-in member |
| 3 | AUTHORIZED | Write actions, moderation (default choice) |
| 4 | ADMINISTRATOR | Add/remove authorized users/roles (guild admin+) |
| 5 | OWNER | Guild owner only — destructive config, billing |
| 6 | DEVELOPER | Platform admin — full cross-guild access |

**Default to Level 3 (AUTHORIZED) when in doubt.**

## Next Steps

- See `docs/integration/04-backend-endpoints.md` to create the API endpoints your page calls
- Review existing pages in `frontend/app/dashboard/` for real examples
- Read [Next.js documentation](https://nextjs.org/docs)
