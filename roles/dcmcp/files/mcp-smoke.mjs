// Exercise the same stdio handshake and file listing used on the native VM.
import { execFileSync } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const mcp = resolve(process.argv[2]);
const sdk = join(mcp, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client');
const { Client } = await import(pathToFileURL(join(sdk, 'index.js')));
const { StdioClientTransport } = await import(pathToFileURL(join(sdk, 'stdio.js')));
const { getRipgrepPath } = await import(pathToFileURL(join(mcp, 'dist/utils/ripgrep-resolver.js')));
const rg = await getRipgrepPath();
const version = execFileSync(rg, ['--version'], { encoding: 'utf8', timeout: 10000 }).split('\n')[0];

const fixture = await mkdtemp(join(tmpdir(), 'dcmcp-smoke-'));
const client = new Client({ name: 'dcmcp-native-smoke', version: '1.0.0' });
try {
  const config = join(fixture, '.claude-server-commander');
  await mkdir(config, { mode: 0o700 });
  await writeFile(join(config, 'config.json'), JSON.stringify({
    allowedDirectories: [fixture],
    telemetryEnabled: false,
    pendingWelcomeOnboarding: false,
    welcomeOnboardingEligible: false
  }), { mode: 0o600 });
  await writeFile(join(fixture, 'dcmcp-marker.txt'), 'MCP fixture\n');
  await client.connect(new StdioClientTransport({
    command: process.execPath,
    args: [join(mcp, 'dist/index.js'), '--no-onboarding'],
    cwd: fixture,
    env: { HOME: fixture, PATH: process.env.PATH, NODE_ENV: 'production' }
  }));
  const { tools } = await client.listTools();
  const result = await client.callTool({
    name: 'list_directory',
    arguments: { path: fixture, depth: 1 }
  });
  if (result.isError || !JSON.stringify(result.content).includes('dcmcp-marker.txt')) {
    throw new Error('The native MCP tool could not list the fixture file.');
  }
  console.log('PASS: ' + version + ', MCP initialized, ' + tools.length + ' tools and fixture file listed.');
} finally {
  await client.close().finally(() => rm(fixture, { recursive: true, force: true }));
}
