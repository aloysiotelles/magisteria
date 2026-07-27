import { defineConfig } from 'vitest/config';

export default defineConfig({
  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify('https://api.example.com'),
    'import.meta.env.PROD': 'true',
  },
  test: {
    environment: 'node',
    include: ['mobile/src/**/*.spec.ts'],
  },
});
