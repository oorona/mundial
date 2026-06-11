'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { apiClient, AuthorizedRole } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { UserPlus, Trash2, Shield, Settings as SettingsIcon, Check } from 'lucide-react';
import { UserSearch } from '@/app/components/UserSearch';
import { useTranslation } from '@/lib/i18n';

interface AuthorizedUser {
    user_id: string;
    username?: string;
    discriminator?: string;
    avatar_url?: string;
    permission_level: string;
    created_at: string;
}

interface GuildSettings {
    level_2_allow_everyone?: boolean;
    level_2_roles?: string[];
}

interface DiscordRole {
    id: string;
    name: string;
    color: number;
    position: number;
}

// Level 4: Owner Only
function PermissionsPage() {
    const { t } = useTranslation();
    const params = useParams();
    const guildId = params.guildId as string;

    const [users, setUsers] = useState<AuthorizedUser[]>([]);
    const [authRoles, setAuthRoles] = useState<AuthorizedRole[]>([]);
    const [roles, setRoles] = useState<DiscordRole[]>([]);
    const [settings, setSettings] = useState<GuildSettings>({});

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    const [newUserId, setNewUserId] = useState('');
    const [searchQuery, setSearchQuery] = useState('');
    const [addingUser, setAddingUser] = useState(false);

    const [selectedRoleId, setSelectedRoleId] = useState('');
    const [addingRole, setAddingRole] = useState(false);

    const [pendingRemoveUser, setPendingRemoveUser] = useState<string | null>(null);
    const [pendingRemoveRole, setPendingRemoveRole] = useState<string | null>(null);

    useEffect(() => {
        fetchAllData();
    }, [guildId]);

    const fetchAllData = async () => {
        setLoading(true);
        try {
            const [usersData, rolesData, authRolesData, settingsData] = await Promise.all([
                apiClient.getAuthorizedUsers(guildId),
                apiClient.getGuildRoles(guildId),
                apiClient.getAuthorizedRoles(guildId),
                apiClient.getGuildSettings(guildId)
            ]);

            setUsers(usersData);
            setRoles(rolesData.sort((a, b) => b.position - a.position)); // Sort by position desc
            setAuthRoles(authRolesData);
            setSettings(settingsData.settings || {});

            setError(null);
        } catch (err: any) {
            console.error(err);
            setError(err.response?.data?.detail || t('permissions.loadError'));
        } finally {
            setLoading(false);
        }
    };

    const showSuccess = (msg: string) => {
        setSuccess(msg);
        setTimeout(() => setSuccess(null), 3000);
    };

    // --- Users ---
    const handleAddUser = async () => {
        if (!newUserId.trim()) return;
        setAddingUser(true);
        setError(null);
        try {
            await apiClient.addAuthorizedUser(guildId, newUserId);
            setNewUserId('');
            setSearchQuery('');
            showSuccess(t('permissions.successUserAdded'));
            fetchAllData();
        } catch (err: any) {
            setError(err.response?.data?.detail || t('permissions.errorAddUser'));
        } finally {
            setAddingUser(false);
        }
    };

    const handleRemoveUser = async (userId: string) => {
        try {
            await apiClient.removeAuthorizedUser(guildId, userId);
            setPendingRemoveUser(null);
            showSuccess(t('permissions.successUserRemoved'));
            fetchAllData();
        } catch (err: any) {
            setPendingRemoveUser(null);
            setError(err.response?.data?.detail || t('permissions.errorRemoveUser'));
        }
    };

    // --- Roles (L3) ---
    const handleAddAuthRole = async () => {
        if (!selectedRoleId) return;
        setAddingRole(true);
        setError(null);
        try {
            await apiClient.addAuthorizedRole(guildId, selectedRoleId);
            setSelectedRoleId('');
            showSuccess(t('permissions.successRoleAdded'));
            fetchAllData();
        } catch (err: any) {
            setError(err.response?.data?.detail || t('permissions.errorAddRole'));
        } finally {
            setAddingRole(false);
        }
    };

    const handleRemoveAuthRole = async (roleId: string) => {
        try {
            await apiClient.removeAuthorizedRole(guildId, roleId);
            setPendingRemoveRole(null);
            showSuccess(t('permissions.successRoleRemoved'));
            fetchAllData();
        } catch (err: any) {
            setPendingRemoveRole(null);
            setError(err.response?.data?.detail || t('permissions.errorRemoveRole'));
        }
    };

    // --- Settings (L2) ---
    const updateSettings = async (newSettingsPartial: GuildSettings) => {
        const updated = { ...settings, ...newSettingsPartial };
        try {
            await apiClient.updateGuildSettings(guildId, updated);
            setSettings(updated);
            showSuccess(t('permissions.successSettingsUpdated'));
        } catch (err: any) {
            setError(err.response?.data?.detail || t('permissions.errorUpdateSettings'));
            fetchAllData();
        }
    };

    const toggleL2Everyone = async () => {
        const current = settings.level_2_allow_everyone ?? true; // Default true
        await updateSettings({ level_2_allow_everyone: !current });
    };

    const toggleL2Role = async (roleId: string) => {
        const currentRoles = settings.level_2_roles || [];
        let newRoles;
        if (currentRoles.includes(roleId)) {
            newRoles = currentRoles.filter(id => id !== roleId);
        } else {
            newRoles = [...currentRoles, roleId];
        }
        await updateSettings({ level_2_roles: newRoles });
    };

    const getRoleName = (id: string) => roles.find(r => r.id === id)?.name || id;

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-muted-foreground animate-pulse">{t('permissions.loading')}</div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
            <div>
                <h1 className="text-3xl font-bold mb-2">{t('permissions.title')}</h1>
                <p className="text-muted-foreground">{t('permissions.subtitle')}</p>
            </div>

            {error && (
                <div className="p-4 bg-red-500/10 border border-red-500 rounded-lg text-red-500 flex items-center">
                    <span className="mr-2">⚠️</span> {error}
                </div>
            )}

            {success && (
                <div className="p-4 bg-green-500/10 border border-green-500 rounded-lg text-green-500 flex items-center">
                    <Check size={18} className="mr-2" /> {success}
                </div>
            )}

            {/* Level 2 Configuration */}
            <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
                <div className="flex items-center mb-4">
                    <div className="p-2 bg-blue-500/20 rounded-lg mr-3">
                        <SettingsIcon size={24} className="text-blue-500" />
                    </div>
                    <div>
                        <h2 className="text-xl font-semibold text-foreground">{t('permissions.sectionL2Title')}</h2>
                        <p className="text-sm text-muted-foreground">{t('permissions.sectionL2Desc')}</p>
                    </div>
                </div>

                <div className="space-y-4">
                    <div className="flex items-center justify-between p-4 bg-muted/30 rounded-lg border border-border">
                        <div>
                            <div className="font-medium text-foreground">{t('permissions.allowEveryone')}</div>
                            <div className="text-sm text-muted-foreground">{t('permissions.allowEveryoneDesc')}</div>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                            <input
                                type="checkbox"
                                className="sr-only peer"
                                checked={settings.level_2_allow_everyone !== false} // Default true
                                onChange={toggleL2Everyone}
                            />
                            <div className="w-11 h-6 bg-muted border border-border peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                    </div>

                    {(settings.level_2_allow_everyone === false) && (
                        <div className="mt-4 animate-in fade-in slide-in-from-top-1 duration-200">
                            <h3 className="text-sm font-semibold text-foreground mb-2">{t('permissions.allowedRolesTitle')}</h3>
                            <p className="text-xs text-muted-foreground mb-3">{t('permissions.allowedRolesDesc')}</p>

                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-60 overflow-y-auto p-2 border border-border rounded-lg">
                                {roles.map(role => (
                                    <label key={role.id} className="flex items-center space-x-2 p-2 hover:bg-muted rounded cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={(settings.level_2_roles || []).includes(role.id)}
                                            onChange={() => toggleL2Role(role.id)}
                                            className="rounded border-border text-blue-600 focus:ring-blue-500 bg-background"
                                        />
                                        <span className="text-sm truncate" style={{ color: role.color ? `#${role.color.toString(16).padStart(6, '0')}` : 'inherit' }}>
                                            {role.name}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Level 3 Authorized Roles */}
            <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
                <div className="p-6 border-b border-border bg-muted/10">
                    <div className="flex items-center mb-1">
                        <div className="p-2 bg-purple-500/20 rounded-lg mr-3">
                            <Shield size={24} className="text-purple-500" />
                        </div>
                        <div>
                            <h2 className="text-xl font-semibold text-foreground">{t('permissions.sectionL3RolesTitle')}</h2>
                            <p className="text-sm text-muted-foreground">{t('permissions.sectionL3RolesDesc')}</p>
                        </div>
                    </div>
                </div>

                <div className="p-6 pt-4">
                    <div className="flex gap-2 mb-6">
                        <select
                            className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-purple-500"
                            value={selectedRoleId}
                            onChange={(e) => setSelectedRoleId(e.target.value)}
                        >
                            <option value="">{t('permissions.selectRolePlaceholder')}</option>
                            {roles
                                .filter(r => r.name !== '@everyone') // Filter out @everyone for L3
                                .filter(r => !authRoles.some(ar => ar.role_id === r.id)) // Filter out already authorized
                                .map(role => (
                                    <option key={role.id} value={role.id}>
                                        {role.name}
                                    </option>
                                ))}
                        </select>
                        <button
                            onClick={handleAddAuthRole}
                            disabled={!selectedRoleId || addingRole}
                            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
                        >
                            {addingRole ? t('permissions.authorizingButton') : t('permissions.authorizeButton')}
                        </button>
                    </div>

                    <div className="space-y-2">
                        {authRoles.length === 0 ? (
                            <div className="text-center py-6 text-muted-foreground bg-muted/20 rounded-lg border border-dashed border-border">
                                {t('permissions.noRoles')}
                            </div>
                        ) : (
                            authRoles.map(ar => (
                                <div key={ar.id} className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
                                    <div className="font-medium text-foreground">
                                        {getRoleName(ar.role_id)}
                                    </div>
                                    {pendingRemoveRole === ar.role_id ? (
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-red-400">{t('permissions.confirmRemove')}</span>
                                            <button
                                                onClick={() => handleRemoveAuthRole(ar.role_id)}
                                                className="text-xs px-2 py-1 bg-red-600 hover:bg-red-500 text-white rounded"
                                            >{t('permissions.confirmButton')}</button>
                                            <button
                                                onClick={() => setPendingRemoveRole(null)}
                                                className="text-xs px-2 py-1 bg-muted hover:bg-muted/80 text-foreground rounded"
                                            >{t('permissions.cancelButton')}</button>
                                        </div>
                                    ) : (
                                        <button
                                            onClick={() => setPendingRemoveRole(ar.role_id)}
                                            className="text-red-500 hover:text-red-400 p-2"
                                            title="Remove Permission"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>

            {/* Level 3 Authorized Users */}
            <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
                <div className="p-6 border-b border-border bg-muted/10">
                    <div className="flex items-center mb-1">
                        <div className="p-2 bg-green-500/20 rounded-lg mr-3">
                            <UserPlus size={24} className="text-green-500" />
                        </div>
                        <div>
                            <h2 className="text-xl font-semibold text-foreground">{t('permissions.sectionL3UsersTitle')}</h2>
                            <p className="text-sm text-muted-foreground">{t('permissions.sectionL3UsersDesc')}</p>
                        </div>
                    </div>
                </div>

                <div className="p-6 pt-4">
                    <div className="flex gap-2 mb-6">
                        <div className="flex-1">
                            <UserSearch
                                guildId={guildId}
                                value={searchQuery}
                                onChange={(val) => {
                                    setSearchQuery(val);
                                    if (!val) setNewUserId('');
                                }}
                                onSelect={(user) => {
                                    setNewUserId(user.id);
                                    setSearchQuery(user.username);
                                }}
                                placeholder={t('permissions.searchUserPlaceholder')}
                            />
                        </div>
                        <button
                            onClick={handleAddUser}
                            disabled={!newUserId || addingUser}
                            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
                        >
                            {addingUser ? t('permissions.authorizingButton') : t('permissions.authorizeButton')}
                        </button>
                    </div>

                    <div className="divide-y divide-border border border-border rounded-lg overflow-hidden">
                        {users.length === 0 ? (
                            <div className="p-6 text-center text-muted-foreground">
                                {t('permissions.noUsers')}
                            </div>
                        ) : (
                            users.map((user) => (
                                <div key={user.user_id} className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors bg-card">
                                    <div className="flex items-center">
                                        {user.avatar_url ? (
                                            <img src={user.avatar_url} alt={user.username} className="w-8 h-8 rounded-full mr-3" />
                                        ) : (
                                            <div className="w-8 h-8 bg-muted rounded-full flex items-center justify-center mr-3">
                                                <span className="text-muted-foreground text-xs">?</span>
                                            </div>
                                        )}
                                        <div>
                                            <div className="font-medium text-foreground">{user.username || user.user_id}</div>
                                            <div className="text-xs text-muted-foreground">
                                                {t('permissions.elevatedAccess')} • {new Date(user.created_at).toLocaleDateString()}
                                            </div>
                                        </div>
                                    </div>
                                    {pendingRemoveUser === user.user_id ? (
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-red-400">{t('permissions.confirmRemove')}</span>
                                            <button
                                                onClick={() => handleRemoveUser(user.user_id)}
                                                className="text-xs px-2 py-1 bg-red-600 hover:bg-red-500 text-white rounded"
                                            >{t('permissions.confirmButton')}</button>
                                            <button
                                                onClick={() => setPendingRemoveUser(null)}
                                                className="text-xs px-2 py-1 bg-muted hover:bg-muted/80 text-foreground rounded"
                                            >{t('permissions.cancelButton')}</button>
                                        </div>
                                    ) : (
                                        <button
                                            onClick={() => setPendingRemoveUser(user.user_id)}
                                            className="text-red-500 hover:text-red-400 p-2"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

export default withPermission(PermissionsPage, PermissionLevel.OWNER) as any;
