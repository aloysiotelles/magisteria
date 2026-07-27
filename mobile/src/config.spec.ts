import { describe, expect, it } from 'vitest';
import { validateApiBaseUrl } from './config';

describe('validateApiBaseUrl', () => {
  it('accepts local HTTP only for development', () => {
    expect(validateApiBaseUrl('http://127.0.0.1:8000/', false)).toBe('http://127.0.0.1:8000');
    expect(() => validateApiBaseUrl('http://127.0.0.1:8000', true)).toThrow();
  });

  it('accepts a production HTTPS origin', () => {
    expect(validateApiBaseUrl('https://api.example.com', true)).toBe('https://api.example.com');
  });
});
