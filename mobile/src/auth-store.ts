import { SecureStorage } from '@aparajita/capacitor-secure-storage';
import type { StoredSession, TokenPair } from './types';

const SESSION_KEY = 'magisteria.mobile.session.v1';

export async function readSession(): Promise<StoredSession | null> {
  const value = await SecureStorage.get(SESSION_KEY);
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<StoredSession>;
  if (!candidate.accessToken || !candidate.refreshToken || !candidate.expiresAt) return null;
  return candidate as StoredSession;
}

export async function saveSession(tokens: TokenPair): Promise<StoredSession> {
  const session: StoredSession = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
  };
  await SecureStorage.set(SESSION_KEY, { ...session } as Record<string, unknown>);
  return session;
}

export async function clearSession(): Promise<void> {
  await SecureStorage.remove(SESSION_KEY);
}
