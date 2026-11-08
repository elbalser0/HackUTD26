/**
 * Google sign-in through Firebase Auth. The ONLY module that touches Firebase.
 *
 * - Config comes from public VITE_FIREBASE_* values (identifiers, not secrets).
 *   Missing config, or fixture mode, means "not configured": no sign-in UI,
 *   and requests go out exactly as before.
 * - The session lasts until the tab closes (browserSessionPersistence). The
 *   Firebase SDK keeps it; this app never stores an ID token itself.
 * - A fresh ID token is fetched for EACH request (`getIdToken()` refreshes
 *   automatically), sent only as `Authorization: Bearer`, never in a URL.
 * - Sign-in proves who submitted an explanation, not who made the change.
 */
import { createContext, useContext } from "react";
import { usingFixtures } from "./api";

export interface AuthUser {
  email: string;
  name: string | null;
  /** Google profile photo URL, if any (display only). */
  photoUrl?: string | null;
}

export interface AuthClient {
  /** Calls `cb` with the current user right away and on every change. */
  onChange(cb: (user: AuthUser | null) => void): () => void;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  /** A fresh ID token for the signed-in user, or null when signed out. */
  getIdToken(): Promise<string | null>;
}

const env = import.meta.env;
const firebaseConfig = {
  apiKey: env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: env.VITE_FIREBASE_APP_ID as string | undefined,
};
const configured =
  !usingFixtures && Object.values(firebaseConfig).every((v) => typeof v === "string" && v.length > 0);

/** Real client. Firebase is loaded lazily so tests and unconfigured builds never touch it. */
function firebaseClient(): AuthClient {
  const ready = (async () => {
    const { initializeApp, getApps } = await import("firebase/app");
    const a = await import("firebase/auth");
    const app = getApps()[0] ?? initializeApp(firebaseConfig);
    const auth = a.getAuth(app);
    await a.setPersistence(auth, a.browserSessionPersistence);
    return { a, auth };
  })();
  const toUser = (
    u: { email: string | null; displayName: string | null; photoURL: string | null } | null,
  ): AuthUser | null =>
    u && u.email ? { email: u.email, name: u.displayName, photoUrl: u.photoURL } : null;
  return {
    onChange(cb) {
      let unsub: (() => void) | null = null;
      let live = true;
      ready.then(({ a, auth }) => {
        if (live) unsub = a.onAuthStateChanged(auth, (u) => cb(toUser(u)));
      });
      return () => {
        live = false;
        unsub?.();
      };
    },
    async signIn() {
      const { a, auth } = await ready;
      await a.signInWithPopup(auth, new a.GoogleAuthProvider());
    },
    async signOut() {
      const { a, auth } = await ready;
      await a.signOut(auth);
    },
    async getIdToken() {
      const { auth } = await ready;
      return auth.currentUser ? auth.currentUser.getIdToken() : null;
    },
  };
}

// undefined = default (real client when configured); null = force "not configured" (tests).
let override: AuthClient | null | undefined;
let real: AuthClient | null = null;
/** Test hook. */
export function setAuthClient(c: AuthClient | null | undefined) {
  override = c;
}
export function currentClient(): AuthClient | null {
  if (override !== undefined) return override;
  if (!configured) return null;
  return (real ??= firebaseClient());
}

export interface AuthState {
  configured: boolean;
  /** False until Firebase has reported the restored session (avoids a sign-in flash). */
  ready: boolean;
  user: AuthUser | null;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  getIdToken(): Promise<string | null>;
}
export const none: AuthState = {
  configured: false,
  ready: true,
  user: null,
  signIn: async () => {},
  signOut: async () => {},
  getIdToken: async () => null,
};
export const AuthContext = createContext<AuthState>(none);

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

