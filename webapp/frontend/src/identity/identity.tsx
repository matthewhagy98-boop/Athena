import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiPost } from "../api/client";

const STORAGE_KEY = "athena_user_id";

interface IdentityState {
  userId: string | null;
  error: boolean;
}

const IdentityContext = createContext<IdentityState>({ userId: null, error: false });

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));
  const [error, setError] = useState(false);

  useEffect(() => {
    if (userId !== null) return;
    apiPost<{ user_id: string }>("/users/anonymous")
      .then(({ user_id }) => {
        localStorage.setItem(STORAGE_KEY, user_id);
        setUserId(user_id);
      })
      .catch(() => setError(true));
  }, [userId]);

  return <IdentityContext.Provider value={{ userId, error }}>{children}</IdentityContext.Provider>;
}

export function useIdentity(): IdentityState {
  return useContext(IdentityContext);
}
