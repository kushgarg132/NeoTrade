import React, { createContext, useContext, useEffect, useState } from 'react';
import api, { endpoints, AUTH_TOKEN_STORAGE_KEY } from '../utils/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            // No early-return on a missing/expired local access token: the
            // long-lived refresh cookie may still be good from a previous
            // visit, and api.js's response interceptor silently refreshes
            // and retries this call on a 401 -- that's the whole
            // mechanism that keeps a returning user from seeing the Google
            // button again.
            // Only a 401 (the interceptor already tried the refresh cookie) ends the session. A network blip or
            // a 5xx keeps the token: retry once, and if it still fails the user lands on /login with the token
            // intact, so a reload signs them back in.
            for (let attempt = 0; attempt < 2 && !cancelled; attempt += 1) {
                try {
                    const res = await api.get(endpoints.auth.me, { cache: false });
                    if (!cancelled) setUser(res.data);
                    break;
                } catch (err) {
                    if (err?.response?.status === 401) {
                        if (!cancelled) {
                            localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
                            setUser(null);
                        }
                        break;
                    }
                    if (attempt === 0) await new Promise((r) => setTimeout(r, 1500));
                }
            }
            if (!cancelled) setLoading(false);
        })();
        return () => { cancelled = true; };
    }, []);

    const login = async (idToken) => {
        const res = await api.post(endpoints.auth.google, { id_token: idToken });
        localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, res.data.token);
        setUser(res.data.user);
    };

    const logout = async () => {
        try {
            await api.post(endpoints.auth.logout);
        } catch {
            // The server-side revocation is best-effort from the client's
            // point of view -- the local session ends either way.
        }
        localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, loading, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
};

// Co-locating the hook with its Provider is the standard React context
// pattern; this rule only affects Fast Refresh granularity, not correctness.
// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth must be used within AuthProvider');
    return ctx;
};
