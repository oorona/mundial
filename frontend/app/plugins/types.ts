
import React from 'react';

import { PermissionLevel } from '@/lib/permissions';

export interface Plugin {
    id: string;
    name: string;
    defaultPermissionLevel?: PermissionLevel;
    routes: PluginRoute[];
    navItems?: NavItem[];
    settingsComponent?: React.ComponentType<{
        guildId: string;
        settings: Record<string, any>;
        onUpdate: (key: string, value: any) => void;
        isReadOnly: boolean;
    }>;
    pageComponent?: React.ComponentType<{
        guildId: string;
        settings: Record<string, any>; // added generic settings prop
    }>;
}

export interface PluginRoute {
    path: string;
    component: React.ComponentType<any>;
    title?: string;
    level?: PermissionLevel;
}

export interface NavItem {
    name: string;
    href: string;
    icon?: React.ComponentType<{ size?: number }>;
    adminOnly?: boolean;
    level?: PermissionLevel;
}
