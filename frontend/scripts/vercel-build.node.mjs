// Node-only deployment checks; kept outside Vitest's .test/.spec patterns.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {apiOrigin, outputConfig} from './vercel-build.mjs';

test('accepts an HTTPS backend origin and normalizes its trailing slash', () => {
  assert.equal(apiOrigin('https://api.formiqo.example/'), 'https://api.formiqo.example');
});

test('refuses missing, local, credential-bearing, or path-prefixed backend origins', () => {
  for (const value of [undefined, '', 'http://api.example.com', 'https://localhost:8010', 'https://127.0.0.1',
    'https://10.0.0.4', 'https://[::1]', 'https://service.local', 'https://user:password@api.example.com',
    'https://api.example.com/api', 'https://api.example.com/?token=secret', 'https://api.example.com/#token']) {
    assert.throws(() => apiOrigin(value), undefined, String(value));
  }
});

test('API paths are proxied before SPA fallback, including the unprefixed /api path', () => {
  const config = outputConfig('https://api.formiqo.example');
  assert.equal(config.version, 3);
  const proxy = config.routes.find(route => route.dest?.startsWith('https://'));
  assert.equal(proxy.dest, 'https://api.formiqo.example/api/$1');
  assert.equal(proxy.headers['Cache-Control'], 'private, no-store');
  const pattern = new RegExp(`^${proxy.src}$`);
  assert.ok(pattern.test('/api'));
  assert.ok(pattern.test('/api/records/export'));
  assert.equal(pattern.test('/application'), false);
  assert.ok(config.routes.indexOf(proxy) < config.routes.findIndex(route => route.handle === 'filesystem'));
  assert.equal(config.routes.at(-1).dest, '/index.html');
});

test('static assets are immutable and responses have baseline security headers', () => {
  const config = outputConfig('https://api.formiqo.example');
  assert.equal(config.routes[0].headers['X-Content-Type-Options'], 'nosniff');
  assert.match(config.routes.find(route => route.src?.startsWith('/assets/')).headers['Cache-Control'], /immutable/);
});
