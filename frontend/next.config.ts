import type { NextConfig } from 'next';

const origin = process.env.DJANGO_API_ORIGIN || 'http://127.0.0.1:8000';
const upstream = new URL(origin);
if (!['http:', 'https:'].includes(upstream.protocol) || upstream.username || upstream.password || upstream.pathname !== '/' || upstream.search || upstream.hash) {
  throw new Error('DJANGO_API_ORIGIN must be an HTTP(S) origin without credentials or a path.');
}
const config: NextConfig = {
  logging: { incomingRequests: { ignore: [/\/api\/v1\/integrations\/google-contacts\/callback/] } },
  poweredByHeader: false,
  trailingSlash: false,
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return { beforeFiles: [{ source: '/api/v1/:path*', destination: `${upstream.origin}/api/v1/:path*/` }] };
  },
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Referrer-Policy', value: 'same-origin' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
    ] }];
  },
};
export default config;
