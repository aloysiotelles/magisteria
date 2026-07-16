import { API_BASE_URL, API_TIMEOUT_MS } from './config';
import { clearSession, readSession, saveSession } from './auth-store';
import { ApiError, type AskEvent, type MobileUser, type TokenPair } from './types';

type JsonObject = Record<string, unknown>;

async function errorFromResponse(response: Response): Promise<ApiError> {
  let message = `Falha HTTP ${response.status}.`;
  try {
    const body = (await response.json()) as { detail?: string; message?: string };
    message = body.detail || body.message || message;
  } catch {
    // Invalid error responses are represented by the status-only fallback.
  }
  return new ApiError(message, response.status);
}

export class ApiClient {
  private refreshPromise: Promise<boolean> | null = null;
  private readonly pending = new Map<string, Promise<unknown>>();

  private async refresh(): Promise<boolean> {
    if (this.refreshPromise) return this.refreshPromise;
    this.refreshPromise = (async () => {
      const session = await readSession();
      if (!session) return false;
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/mobile/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
          signal: AbortSignal.timeout(API_TIMEOUT_MS),
        });
        if (!response.ok) {
          await clearSession();
          return false;
        }
        await saveSession((await response.json()) as TokenPair);
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      this.refreshPromise = null;
    });
    return this.refreshPromise;
  }

  private async fetchAuthorized(path: string, init: RequestInit, retry = true): Promise<Response> {
    const session = await readSession();
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (session) headers.set('Authorization', `Bearer ${session.accessToken}`);
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (response.status === 401 && retry && (await this.refresh())) {
      return this.fetchAuthorized(path, init, false);
    }
    return response;
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const method = (init.method || 'GET').toUpperCase();
    const key = method === 'GET' ? `${method}:${path}` : '';
    if (key && this.pending.has(key)) return this.pending.get(key) as Promise<T>;
    const operation = (async () => {
      const response = await this.fetchAuthorized(path, init);
      if (!response.ok) throw await errorFromResponse(response);
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    })();
    if (key) this.pending.set(key, operation);
    try {
      return await operation;
    } finally {
      if (key) this.pending.delete(key);
    }
  }

  async login(email: string, password: string): Promise<MobileUser> {
    const response = await fetch(`${API_BASE_URL}/api/v1/mobile/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!response.ok) throw await errorFromResponse(response);
    const tokens = (await response.json()) as TokenPair;
    await saveSession(tokens);
    if (!tokens.user) throw new ApiError('Resposta de autenticação inválida.', 502);
    return tokens.user;
  }

  async register(fullName: string, email: string, password: string): Promise<MobileUser> {
    const response = await fetch(`${API_BASE_URL}/api/v1/mobile/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name: fullName, email, password }),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!response.ok) throw await errorFromResponse(response);
    const tokens = (await response.json()) as TokenPair;
    await saveSession(tokens);
    if (!tokens.user) throw new ApiError('Resposta de cadastro inválida.', 502);
    return tokens.user;
  }

  async logout(): Promise<void> {
    const session = await readSession();
    try {
      if (session) {
        await this.request<void>('/api/v1/mobile/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        });
      }
    } finally {
      await clearSession();
    }
  }

  async askStream(question: string, onEvent: (event: AskEvent) => void): Promise<void> {
    const body: JsonObject = { pergunta: question, historico: [], idioma: 'pt-BR' };
    const response = await this.fetchAuthorized('/api/v1/ask-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw await errorFromResponse(response);
    if (!response.body) throw new ApiError('O servidor não iniciou a resposta.', 502);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        onEvent(JSON.parse(line) as AskEvent);
      }
      if (done) break;
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer) as AskEvent);
  }

  async download(path: string, body: JsonObject): Promise<Blob> {
    const response = await this.fetchAuthorized(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw await errorFromResponse(response);
    return response.blob();
  }

  async uploadDocument(file: File, onProgress: (percent: number) => void): Promise<void> {
    const chunkSize = 1024 * 1024;
    for (let offset = 0; offset < file.size; offset += chunkSize) {
      const end = Math.min(offset + chunkSize, file.size);
      const response = await this.fetchAuthorized('/admin/upload-chunk', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-Path': file.name,
          'X-Offset': String(offset),
          'X-Complete': end === file.size ? '1' : '0',
        },
        body: file.slice(offset, end),
      });
      if (!response.ok) throw await errorFromResponse(response);
      onProgress(Math.round((end / file.size) * 100));
    }
  }
}

export const api = new ApiClient();
