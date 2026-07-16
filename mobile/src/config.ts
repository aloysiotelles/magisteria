const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

export function validateApiBaseUrl(raw: string, production: boolean): string {
  const value = raw.trim().replace(/\/$/, '');
  if (!value) throw new Error('VITE_API_BASE_URL não foi configurada.');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('A URL da API deve usar HTTP ou HTTPS.');
  }
  if (production && (url.protocol !== 'https:' || LOCAL_HOSTS.has(url.hostname))) {
    throw new Error('Build móvel de produção exige API HTTPS não local.');
  }
  return url.toString().replace(/\/$/, '');
}

export const API_BASE_URL = validateApiBaseUrl(
  import.meta.env.VITE_API_BASE_URL ?? '',
  import.meta.env.PROD,
);

export const API_TIMEOUT_MS = 25_000;
export const ALLOWED_EXTERNAL_HOSTS = new Set([
  new URL(API_BASE_URL).hostname,
  'developer.apple.com',
  'support.google.com',
]);
