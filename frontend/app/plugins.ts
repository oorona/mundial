/**
 * Frontend Plugin System
 * 
 * Allows bot developers to register custom pages and navigation items
 */

import { Plugin, PluginRoute, NavItem } from './plugins/types';
// Initialize plugins immediately
// if (typeof window !== 'undefined' || process.env.NODE_ENV === 'development') {
//     // Only register once if possible, or simple registry handles duplicates
//     // registerPlugins();
// }
// Validation: Initialization is handled in layout.tsx to avoid circular dependency

// Interfaces moved to ./plugins/types.ts to avoid circular dependencies

class PluginRegistry {
    private plugins: Map<string, Plugin> = new Map();

    /**
     * Register a new plugin
     */
    register(plugin: Plugin) {
        if (this.plugins.has(plugin.id)) {
            console.warn(`Plugin ${plugin.id} is already registered`);
            return;
        }

        this.plugins.set(plugin.id, plugin);
        console.log(`Plugin registered: ${plugin.name} (${plugin.id})`);
    }

    /**
     * Unregister a plugin
     */
    unregister(pluginId: string) {
        this.plugins.delete(pluginId);
    }

    /**
     * Get all registered plugins
     */
    getAll(): Plugin[] {
        return Array.from(this.plugins.values());
    }

    /**
     * Get routes from all plugins
     */
    getAllRoutes(): PluginRoute[] {
        return this.getAll().flatMap(plugin => plugin.routes || []);
    }

    /**
     * Get navigation items from all plugins
     */
    getAllNavItems(): NavItem[] {
        return this.getAll().flatMap(plugin => plugin.navItems || []);
    }

    /**
     * Get a specific plugin
     */
    get(pluginId: string): Plugin | undefined {
        return this.plugins.get(pluginId);
    }
}

// Singleton instance
export const pluginRegistry = new PluginRegistry();

/**
 * Hook to use plugins in React components
 */
export function usePlugins() {
    return {
        plugins: pluginRegistry.getAll(),
        routes: pluginRegistry.getAllRoutes(),
        navItems: pluginRegistry.getAllNavItems(),
    };
}

// Example usage:
// import { pluginRegistry } from '@/app/plugins';
// import { RoleResponderPlugin } from './plugins/role-responder';

// pluginRegistry.register(RoleResponderPlugin);

// pluginRegistry.register({
//   id: 'my-custom-plugin',
//   name: 'My Custom Plugin',
//   routes: [
//     {
//       path: '/custom-page',
//       component: MyCustomPage,
//       title: 'Custom Page',
//     },
//   ],
//   navItems: [
//     {
//       name: 'Custom',
//       href: '/custom-page',
//       icon: CustomIcon,
//     },
//   ],
// });
