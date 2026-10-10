// Native integration fixture: the SDK owns a real Desktop Commander stdio child.
// Only the test unit has a private network namespace; production stays on the host.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [release, home, user, expectedUid] = process.argv.slice(2);
const sdk = path.join(release, 'mcp/node_modules/@modelcontextprotocol/sdk/dist/esm');
const { Client } = await import(pathToFileURL(path.join(sdk, 'client/index.js')));
const { StdioClientTransport } = await import(pathToFileURL(path.join(sdk, 'client/stdio.js')));
const transport = new StdioClientTransport({
  command: path.join(release, 'node/bin/node'),
  args: [path.join(release, 'mcp/dist/index.js'), '--no-onboarding'],
  cwd: home,
  env: {
    HOME: home, USER: user, LOGNAME: user, SHELL: '/bin/bash',
    PATH: path.join(release, 'node/bin') + ':/usr/local/bin:/usr/bin:/bin',
    NODE_ENV: 'production', LANG: 'C.UTF-8'
  },
  stderr: 'pipe'
});
transport.stderr?.on('data', () => {});
const client = new Client({ name: 'dcmcp-native-validation', version: '1.0.0' });
client.onerror = () => {};
process.once('SIGTERM', () => process.exit(0));
setTimeout(() => {
  console.error('Native MCP fixture timed out.');
  process.exit(1);
}, 45000).unref();

try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  for (const name of ['get_config', 'list_directory', 'start_process']) {
    if (!tools.some(tool => tool.name === name)) throw new Error('Missing tool');
  }
  const config = await client.callTool({ name: 'get_config', arguments: {} });
  if (config.isError) throw new Error('Config call failed');
  const directory = await client.callTool({
    name: 'list_directory', arguments: { path: home, depth: 1 }
  });
  if (directory.isError || !JSON.stringify(directory.content).includes('native-test-marker')) {
    throw new Error('Directory call failed');
  }
  const identity = await client.callTool({
    name: 'start_process',
    arguments: { command: 'id -u && sudo -n true', shell: '/bin/bash', timeout_ms: 2000 }
  });
  if (identity.isError || !identity.content.some(item =>
      typeof item.text === 'string' && item.text.split(/\s+/).includes(expectedUid))) {
    throw new Error('Existing user/sudo probe failed');
  }
  // Leave a long-lived tool process to exercise KillMode=control-group.
  const child = await client.callTool({
    name: 'start_process',
    arguments: { command: 'sleep 300', shell: '/bin/bash', timeout_ms: 500 }
  });
  if (child.isError) throw new Error('Long-lived child call failed');
  await fs.writeFile(path.join(home, 'native-ready.json'), JSON.stringify({
    parent_pid: process.pid, mcp_pid: transport.pid, tools_count: tools.length,
    calls: ['get_config', 'list_directory', 'start_process']
  }), { mode: 0o600 });
  // systemd stops this parent, the MCP child and all tool processes together.
  setInterval(() => {}, 1000);
} catch {
  console.error('Native MCP initialization, discovery or tool call failed.');
  process.exit(1);
}
