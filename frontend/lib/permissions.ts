export enum PermissionLevel {
    PUBLIC = 0,         // Landing Page
    PUBLIC_DATA = 1,    // Static Data Page
    USER = 2,           // Login Required (Generic) - Configurable Roles
    AUTHORIZED = 3,     // Authorized Users/Roles (Bot Settings) - Strictly Controlled
    ADMINISTRATOR = 4,  // Guild Administrator (Discord admin permission, not owner)
    OWNER = 5,          // Guild Owner Only (Permissions, billing, destructive config)
    DEVELOPER = 6       // Platform Admin — full cross-guild access
}

export const PERMISSION_LABELS: Record<PermissionLevel, string> = {
    [PermissionLevel.PUBLIC]: "Public",
    [PermissionLevel.PUBLIC_DATA]: "Public Data",
    [PermissionLevel.USER]: "User (Login Required)",
    [PermissionLevel.AUTHORIZED]: "Authorized",
    [PermissionLevel.ADMINISTRATOR]: "Administrator",
    [PermissionLevel.OWNER]: "Owner",
    [PermissionLevel.DEVELOPER]: "Developer"
};
