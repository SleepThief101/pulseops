import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiError, apiClient } from "../lib/api";
import type { UserOrganization, UserProfile } from "../types/api";

interface AuthContextValue {
  token: string | null;
  user: UserProfile | null;
  organizations: UserOrganization[];
  activeOrg: UserOrganization | null;
  loading: boolean;
  sessionError: string | null;
  retrySession: () => Promise<void>;
  setActiveOrgId: (orgId: string) => void;
  loginWithToken: (accessToken: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const TOKEN_KEY = "pulseops_access_token";
const ORG_KEY = "pulseops_active_org_id";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<UserProfile | null>(null);
  const [organizations, setOrganizations] = useState<UserOrganization[]>([]);
  const [activeOrgId, setActiveOrgIdState] = useState<string | null>(() =>
    localStorage.getItem(ORG_KEY)
  );
  const [loading, setLoading] = useState<boolean>(Boolean(localStorage.getItem(TOKEN_KEY)));
  const [sessionError, setSessionError] = useState<string | null>(null);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ORG_KEY);
    setToken(null);
    setUser(null);
    setOrganizations([]);
    setActiveOrgIdState(null);
    setSessionError(null);
  }, []);

  const hydrate = useCallback(
    async (accessToken: string) => {
      setLoading(true);
      setSessionError(null);
      try {
        const [profile, orgs] = await Promise.all([
          apiClient.getMe(accessToken, logout),
          apiClient.getMyOrganizations(accessToken, logout),
        ]);
        setUser(profile);
        setOrganizations(orgs);
        const storedOrg = localStorage.getItem(ORG_KEY);
        const validStored = orgs.find((o) => o.organization_id === storedOrg);
        const chosen = validStored?.organization_id ?? orgs[0]?.organization_id ?? null;
        if (chosen) {
          localStorage.setItem(ORG_KEY, chosen);
        }
        setActiveOrgIdState(chosen);
      } finally {
        setLoading(false);
      }
    },
    [logout]
  );

  const handleHydrateFailure = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
        logout();
        return;
      }
      const msg =
        err instanceof ApiError
          ? err.message
          : "Unable to connect to PulseOps API. If using Render free tier, the service may be waking up.";
      setSessionError(msg);
    },
    [logout]
  );

  useEffect(() => {
    if (token) {
      hydrate(token).catch(handleHydrateFailure);
    }
  }, [token, hydrate, handleHydrateFailure]);

  const retrySession = useCallback(async () => {
    if (!token) return;
    try {
      await hydrate(token);
    } catch (err) {
      handleHydrateFailure(err);
    }
  }, [token, hydrate, handleHydrateFailure]);

  const loginWithToken = useCallback(
    async (accessToken: string) => {
      localStorage.setItem(TOKEN_KEY, accessToken);
      setToken(accessToken);
      await hydrate(accessToken);
    },
    [hydrate]
  );

  const setActiveOrgId = useCallback((orgId: string) => {
    localStorage.setItem(ORG_KEY, orgId);
    setActiveOrgIdState(orgId);
  }, []);

  const activeOrg =
    organizations.find((o) => o.organization_id === activeOrgId) ?? organizations[0] ?? null;

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        organizations,
        activeOrg,
        loading,
        sessionError,
        retrySession,
        setActiveOrgId,
        loginWithToken,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
