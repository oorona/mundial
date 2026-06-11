'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { apiClient } from '../app/api-client';

interface AuthContextType {
    user: any;
    loading: boolean;
    logout: () => void;
    logoutAll: () => void;
    /** Re-fetches the current user from the API and updates the in-memory user
     *  object.  Call this after saving user settings so the rest of the app
     *  sees the updated preferences without a full page reload. */
    refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        checkAuth();
    }, []);

    const checkAuth = async () => {
        // Check for token in URL (from OAuth callback)
        if (typeof window !== 'undefined') {
            const params = new URLSearchParams(window.location.search);
            const token = params.get('token');
            if (token) {
                // Save token to localStorage
                localStorage.setItem('access_token', token);

                // Remove token from URL for cleaner history
                const newUrl = window.location.pathname + window.location.hash;
                window.history.replaceState({}, '', newUrl);
            }
        }

        // If we are on the login page, skip auth check to avoid infinite loop
        if (typeof window !== 'undefined' && (window.location.pathname === '/login' || window.location.pathname === '/access-denied')) {
            setLoading(false);
            return;
        }

        // No token stored — user is definitely not logged in, skip the API call
        const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
        if (!token) {
            setLoading(false);
            return;
        }

        try {
            const data = await apiClient.getCurrentUser();
            setUser(data);
            setLoading(false);
        } catch (error: any) {
            console.error('Auth check failed:', error);
            // Token was invalid/expired — clear it and stop loading
            if (typeof window !== 'undefined') {
                localStorage.removeItem('access_token');
            }
            setLoading(false);
        }
    };

    const logout = async () => {
        try {
            await apiClient.logout();
        } catch (error) {
            console.error('Logout failed:', error);
        } finally {
            setUser(null);
            if (typeof window !== 'undefined') {
                localStorage.removeItem('access_token');
                window.location.href = '/welcome';
            }
        }
    };

    const refreshUser = async () => {
        const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
        if (!token) return;
        try {
            const data = await apiClient.getCurrentUser();
            setUser(data);
        } catch (error) {
            console.error('Failed to refresh user:', error);
        }
    };

    const logoutAll = async () => {
        try {
            await apiClient.logoutAll();
        } catch (error) {
            console.error('Logout all failed:', error);
        } finally {
            setUser(null);
            if (typeof window !== 'undefined') {
                localStorage.removeItem('access_token');
                window.location.href = '/welcome';
            }
        }
    };

    return (
        <AuthContext.Provider value={{ user, loading, logout, logoutAll, refreshUser }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
