// Dependency-free production static server; only built assets under dist are served.
import http from 'node:http';
import {createReadStream} from 'node:fs';
import {stat, realpath} from 'node:fs/promises';
import {resolve, extname, sep} from 'node:path';
const root = await realpath(resolve('dist'));
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.ico':'image/x-icon','.woff2':'font/woff2','.pdf':'application/pdf'};
export async function locate(url) {
  const pathname = decodeURIComponent(new URL(url, 'http://localhost').pathname);
  if (pathname.includes('\0')) throw new Error('invalid path');
  let file = resolve(root, '.' + pathname);
  if (file !== root && !file.startsWith(root + sep)) throw new Error('invalid path');
  try {if (!(await stat(file)).isFile()) file = resolve(root, 'index.html');}
  catch {file = resolve(root, 'index.html');}
  const actual = await realpath(file);
  if (!actual.startsWith(root + sep)) throw new Error('invalid path');
  return actual;
}
if (!process.env.VMEDA_STATIC_TEST) {
  http.createServer(async (request, response) => {
    if (!['GET','HEAD'].includes(request.method)) {response.writeHead(405); return response.end();}
    try {
      const file = await locate(request.url);
      const info = await stat(file);
      const immutable = /[.-][a-zA-Z0-9_-]{8,}\.(js|css|woff2)$/.test(file);
      response.writeHead(200, {'Content-Type':types[extname(file)] ?? 'application/octet-stream','Content-Length':info.size,'Cache-Control':immutable?'public, max-age=31536000, immutable':'no-cache','X-Content-Type-Options':'nosniff'});
      if (request.method === 'HEAD') return response.end();
      createReadStream(file).on('error', () => response.destroy()).pipe(response);
    } catch {response.writeHead(400);response.end('Invalid request');}
  }).listen(Number(process.env.PORT ?? 3000), '0.0.0.0');
}
