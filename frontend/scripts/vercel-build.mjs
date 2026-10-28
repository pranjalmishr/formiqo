import {cp, mkdir, rm, writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

// Vercel hosts the React app, not the long-running Python conversion workers.
// Keep /api same-origin using an edge rewrite to the user's persistent backend.
// Build Output API routes accept full destination URLs; using it lets the backend
// origin come from a project environment variable instead of hard-coded source.
export function apiOrigin(value) {
  let url;
  try { url = new URL(value); } catch {
    throw new Error('Set FORMIQO_API_ORIGIN to the public HTTPS origin of your deployed backend.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('FORMIQO_API_ORIGIN must be an HTTPS origin only (no credentials, path, query, or fragment).');
  }
  const host = url.hostname.toLowerCase();
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal') ||
      /^\d+(\.\d+){3}$/.test(host) || host.includes(':')) {
    throw new Error('FORMIQO_API_ORIGIN must use the public DNS hostname of your backend, not a local address.');
  }
  return url.origin;
}

export function outputConfig(value) {
  const origin = apiOrigin(value);
  return {
    version: 3,
    routes: [
      {src: '/(.*)', headers: {
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      }, continue: true},
      // Stop API paths here; never turn an API error into the SPA HTML document.
      {src: '/api(?:/(.*))?', dest: `${origin}/api/$1`, headers: {'Cache-Control': 'private, no-store'}},
      {src: '/assets/(.*)', headers: {'Cache-Control': 'public, max-age=31536000, immutable'}, continue: true},
      {handle: 'filesystem'},
      {src: '/(.*)', dest: '/index.html', headers: {'Cache-Control': 'no-cache'}},
    ],
  };
}

export async function build() {
  // Fail before building rather than publish a frontend pointed at localhost.
  const config = outputConfig(process.env.FORMIQO_API_ORIGIN);
  const root = fileURLToPath(new URL('../', import.meta.url));
  execFileSync('npm', ['run', 'build'], {cwd: root, stdio: 'inherit'});
  const output = path.join(root, '.vercel/output');
  await rm(output, {recursive: true, force: true});
  await mkdir(output, {recursive: true});
  await cp(path.join(root, 'dist'), path.join(output, 'static'), {recursive: true});
  await writeFile(path.join(output, 'config.json'), JSON.stringify(config, null, 2) + '\n');
  console.log('Vercel static output prepared with a same-origin /api rewrite.');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  build().catch(error => { console.error(error.message); process.exitCode = 1; });
}
