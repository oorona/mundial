'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Search, X, User } from 'lucide-react';
import { apiClient, DiscordMember } from '@/app/api-client';

export interface UserSearchProps {
    guildId: string;
    onSelect: (user: DiscordMember) => void;
    placeholder?: string;
    value?: string;
    onChange?: (value: string) => void;
}

export function UserSearch({ guildId, onSelect, placeholder = "Search for a user...", value, onChange }: UserSearchProps) {
    const [internalQuery, setInternalQuery] = useState('');
    const [results, setResults] = useState<DiscordMember[]>([]);
    const [loading, setLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const wrapperRef = useRef<HTMLDivElement>(null);

    const query = value !== undefined ? value : internalQuery;

    const handleQueryChange = (newQuery: string) => {
        if (onChange) {
            onChange(newQuery);
        } else {
            setInternalQuery(newQuery);
        }
    };

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        const timeoutId = setTimeout(async () => {
            if (query.trim().length < 2) {
                setResults([]);
                return;
            }

            setLoading(true);
            try {
                const members = await apiClient.searchGuildMembers(guildId, query);
                setResults(members);
                setIsOpen(true);
            } catch (error) {
                console.error('Failed to search members:', error);
            } finally {
                setLoading(false);
            }
        }, 500); // Debounce 500ms

        return () => clearTimeout(timeoutId);
    }, [query, guildId]);

    const handleSelect = (user: DiscordMember) => {
        onSelect(user);
        // Set query to username instead of clearing
        if (onChange) {
            onChange(user.username);
        } else {
            setInternalQuery(user.username);
        }
        setResults([]);
        setIsOpen(false);
    };

    return (
        <div ref={wrapperRef} className="relative">
            <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                <input
                    type="text"
                    value={query}
                    onChange={(e) => handleQueryChange(e.target.value)}
                    onFocus={() => query.length >= 2 && setIsOpen(true)}
                    placeholder={placeholder}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors"
                />
                {query && (
                    <button
                        onClick={() => handleQueryChange('')}
                        className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-white"
                    >
                        <X size={16} />
                    </button>
                )}
            </div>

            {isOpen && (results.length > 0 || loading) && (
                <div className="absolute z-50 w-full mt-2 bg-gray-900 border border-gray-700 rounded-lg shadow-xl max-h-60 overflow-y-auto">
                    {loading ? (
                        <div className="p-4 text-center text-gray-400 text-sm">Searching...</div>
                    ) : (
                        <ul>
                            {results.map((user) => (
                                <li
                                    key={user.id}
                                    onClick={() => handleSelect(user)}
                                    className="flex items-center p-3 hover:bg-gray-800 cursor-pointer transition-colors border-b border-gray-800 last:border-0"
                                >
                                    {user.avatar_url ? (
                                        <img src={user.avatar_url} alt={user.username} className="w-8 h-8 rounded-full mr-3" />
                                    ) : (
                                        <div className="w-8 h-8 bg-gray-700 rounded-full flex items-center justify-center mr-3">
                                            <User size={16} className="text-gray-400" />
                                        </div>
                                    )}
                                    <div>
                                        <div className="font-medium text-white">{user.username}</div>
                                        <div className="text-xs text-gray-500">#{user.discriminator} • ID: {user.id}</div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
}
