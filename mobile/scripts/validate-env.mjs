import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const mode = process.env.NODE_ENV === 'development' ? 'development' : 'production';
let fileValue = '';
try {
  const contents = readFileSync(resolve(`mobile/.env.${mode}`), 'utf8');
  fileValue = contents.match(/^VITE_API_BASE_URL=(.+)$/m)?.[1]?.trim() || '';
} catch {
  // The explicit process environment remains a supported CI override.
}
const raw = process.env.VITE_API_BASE_URL || fileValue;

if (!raw) {
  console.error('VITE_API_BASE_URL is required. Use mobile/.env.production or mobile/.env.development.');
  process.exit(1);
}

let api;
try {
  api = new URL(raw);
} catch {
  console.error('VITE_API_BASE_URL must be an absolute URL.');
  process.exit(1);
}

const localHosts = new Set(['localhost', '127.0.0.1', '::1']);
if (mode !== 'development' && (api.protocol !== 'https:' || localHosts.has(api.hostname))) {
  console.error('A production mobile build requires a non-local HTTPS API URL.');
  process.exit(1);
}
