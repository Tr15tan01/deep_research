"use client";

import { ThemeProvider } from "next-themes";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";

import { api, refreshSession } from "@/lib/api";
import type { PublicConfig, User } from "@/lib/types";

interface SessionCtx {
  user: User | null;
  status: "loading" | "authenticated" | "anonymous";
  config: PublicConfig | null;
  configError: boolean;
  reloadUser: () => Promise<User | null>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<SessionCtx | null>(null);

export function useSession(): SessionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside <Providers>");
  return v;
}

export function useConfig(): PublicConfig | null {
  return useSession().config;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<SessionCtx["status"]>("loading");
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [configError, setConfigError] = useState(false);

  const reloadUser = useCallback(async () => {
    // /auth/session never 401s: signed-out visitors get `user: null` without console noise.
    const probe = () => api<{ user: User | null; refreshable: boolean }>("/api/v1/auth/session", { retryOn401: false });
    try {
      let d = await probe();
      if (!d.user && d.refreshable && (await refreshSession())) d = await probe();
      setUser(d.user);
      setStatus(d.user ? "authenticated" : "anonymous");
      return d.user;
    } catch {
      setUser(null);
      setStatus("anonymous");
      return null;
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      setStatus("anonymous");
      window.location.replace(new URL("/login", window.location.origin).toString());
    }
  }, []);

  useEffect(() => {
    void reloadUser();
    api<PublicConfig>("/api/v1/public/config")
      .then(setConfig)
      .catch(() => setConfigError(true));
  }, [reloadUser]);

  const value = useMemo(() => ({ user, status, config, configError, reloadUser, signOut }),
    [user, status, config, configError, reloadUser, signOut]);

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <Ctx.Provider value={value}>{children}</Ctx.Provider>
      <Toaster position="bottom-right" toastOptions={{ className: "!bg-surface !text-text !border-line" }} />
    </ThemeProvider>
  );
}
