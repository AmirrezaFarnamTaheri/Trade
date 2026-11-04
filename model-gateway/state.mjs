import { DatabaseSync } from 'node:sqlite';
import { constants } from 'node:fs';
import { mkdir, lstat, open, rename, unlink } from 'node:fs/promises';
import { join, resolve, dirname, parse } from 'node:path';
import { homedir, userInfo } from 'node:os';
import { randomUUID, randomBytes, createHmac } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { setTimeout as sleep } from 'node:timers/promises';
import { check, GatewayError, parseConfig, emptyConfig, MAX_CONFIG, validate } from './config.mjs';

const exec = promisify(execFile);
const HELPER = resolve(import.meta.dirname, '../gym-core/src/gym/adapters/model_credentials.py');
export const defaultHome = () => process.env.GYM_MODEL_HOME || (process.platform === 'win32'
  ? join(process.env.LOCALAPPDATA || join(homedir(), 'AppData/Local'), 'TradingGYM/models')
  : join(process.env.XDG_STATE_HOME || join(homedir(), '.local/state'), 'tradinggym/models'));

async function noLinks(path) {
  let p = resolve(path);
  for (;;) {
    try { check(!(await lstat(p)).isSymbolicLink(), 'unsafe_state_path'); }
    catch (e) { if (e.code !== 'ENOENT') throw e; }
    if (p === parse(p).root) break;
    p = dirname(p);
  }
}
async function privateFile(path) {
  await noLinks(path);
  const s = await lstat(path);
  check(s.isFile() && s.nlink === 1, 'unsafe_state_file');
  if (process.platform !== 'win32') check(s.uid === userInfo().uid && !(s.mode & 0o077), 'unsafe_state_permissions');
}
export async function boundedRead(path, limit) {
  const f = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
  try {
    check((await f.stat()).isFile(), 'invalid_file');
    const b = Buffer.alloc(limit + 1);
    let n = 0;
    while (n < b.length) { const r = await f.read(b, n, b.length - n, null); if (!r.bytesRead) break; n += r.bytesRead; }
    check(n <= limit, 'input_too_large');
    return b.subarray(0, n);
  } finally { await f.close(); }
}
export async function atomicWrite(path, bytes, { exclusive = false } = {}) {
  await noLinks(path);
  const temp = `${path}.${randomUUID()}.tmp`;
  const f = await open(temp, 'wx', 0o600);
  try {
    await f.writeFile(bytes); await f.sync(); await f.close();
    if (exclusive) {
      const { link } = await import('node:fs/promises');
      await link(temp, path); await unlink(temp);
    } else await rename(temp, path);
  } catch (e) { await f.close().catch(() => {}); await unlink(temp).catch(() => {}); throw e; }
}
async function dpapi(mode, bytes) {
  check(bytes.length <= 65536, 'credential_too_large');
  const python = process.env.GYM_MODEL_PYTHON;
  check(python, 'credential_helper_unavailable');
  return new Promise((resolvePromise, reject) => {
    const child = execFile(python, [HELPER, mode], { timeout: 15000, maxBuffer: 65536, encoding: 'buffer', windowsHide: true }, (error, stdout) => {
      if (error || !stdout.length || stdout.length > 65536) reject(new GatewayError('credential_storage_failed'));
      else resolvePromise(stdout);
    });
    child.stdin.on('error', () => {});
    child.stdin.end(bytes);
  });
}
function credential(value) {
  check(value && value.type === 'oauth' && typeof value.access === 'string' && value.access.length > 0 && typeof value.refresh === 'string' && value.refresh.length > 0 && Number.isFinite(value.expires), 'corrupt_credentials');
  check(Buffer.byteLength(JSON.stringify(value)) <= 65536, 'credential_too_large');
  return value;
}
export class State {
  constructor(home = defaultHome(), { seal, unseal, allowLoopback = false } = {}) {
    this.home = resolve(home);
    this.options = { allowLoopback };
    this.seal = seal || (process.platform === 'win32' ? b => dpapi('encrypt', b) : async b => b);
    this.unseal = unseal || (process.platform === 'win32' ? b => dpapi('decrypt', b) : async b => b);
  }
  async init() {
    await noLinks(this.home);
    await mkdir(this.home, { recursive: true, mode: 0o700 });
    const s = await lstat(this.home);
    check(s.isDirectory(), 'unsafe_state_path');
    const stateFiles = ['config.json', 'state.sqlite', 'state.sqlite-journal', 'state.sqlite-wal', 'state.sqlite-shm'];
    for (const name of stateFiles) {
      try { await privateFile(join(this.home, name)); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    }
    if (process.platform === 'win32') {
      const encodedPath = Buffer.from(this.home, 'utf8').toString('base64');
      const script = `
$ErrorActionPreference='Stop'
$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedPath}'))
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
if ([IO.Directory]::GetAccessControl($p).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'owner' }
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')))
[IO.Directory]::SetAccessControl($p,$acl)
foreach ($name in @('config.json','state.sqlite','state.sqlite-journal','state.sqlite-wal','state.sqlite-shm')) {
  $file=Join-Path $p $name
  if (Test-Path -LiteralPath $file) {
    if ([IO.File]::GetAccessControl($file).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'owner' }
    $f=New-Object Security.AccessControl.FileSecurity
    $f.SetOwner($sid)
    $f.SetAccessRuleProtection($true,$false)
    $f.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow')))
    [IO.File]::SetAccessControl($file,$f)
  }
}`;
      await exec(join(process.env.SystemRoot || 'C:/Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], { windowsHide: true, timeout: 15000, maxBuffer: 4096 });
    } else check(s.uid === userInfo().uid && !(s.mode & 0o077), 'unsafe_state_permissions');
    const path = join(this.home, 'state.sqlite');
    try { const f = await open(path, 'wx', 0o600); await f.close(); } catch (e) { if (e.code !== 'EEXIST') throw e; }
    await this.tx(async db => {
      db.exec('CREATE TABLE IF NOT EXISTS credentials (namespace TEXT PRIMARY KEY, value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS pools (scope TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
      db.prepare('INSERT OR IGNORE INTO meta VALUES (?, ?)').run('salt', randomBytes(32).toString('hex'));
      db.prepare('INSERT OR IGNORE INTO meta VALUES (?, ?)').run('device', randomUUID());
    });
    return this;
  }
  async tx(fn, { signal } = {}) {
    signal?.throwIfAborted();
    await privateFile(join(this.home, 'state.sqlite'));
    const db = new DatabaseSync(join(this.home, 'state.sqlite'));
    let begun = false;
    const until = Date.now() + 15000;
    try {
      db.exec('PRAGMA busy_timeout=0; PRAGMA trusted_schema=OFF');
      for (;;) {
        signal?.throwIfAborted();
        try { db.exec('BEGIN IMMEDIATE'); begun = true; break; }
        catch (e) {
          if (!String(e.message).includes('locked') || Date.now() >= until) throw new GatewayError('state_busy');
          await sleep(15, undefined, { signal });
        }
      }
      const value = await fn(db);
      signal?.throwIfAborted();
      db.exec('COMMIT'); begun = false;
      return value;
    } finally { try { if (begun) db.exec('ROLLBACK'); } finally { db.close(); } }
  }
  async config() {
    const path = join(this.home, 'config.json');
    try { await privateFile(path); return parseConfig(await boundedRead(path, MAX_CONFIG), this.options); }
    catch (e) { if (e.code === 'ENOENT') return emptyConfig(); throw e; }
  }
  async saveConfig(config) {
    const next = validate(config, this.options);
    await this.tx(() => atomicWrite(join(this.home, 'config.json'), JSON.stringify(next, null, 2) + '\n'));
    return next;
  }
  credentials(connection) {
    const namespace = JSON.stringify([connection.id, connection.provider]);
    const scoped = provider => check(provider === connection.provider, 'credential_scope_mismatch');
    const read = async db => {
      const row = db.prepare('SELECT value FROM credentials WHERE namespace=?').get(namespace);
      if (!row) return undefined;
      try { return credential(JSON.parse(Buffer.from(await this.unseal(Buffer.from(row.value))).toString('utf8'))); }
      catch { throw new GatewayError('corrupt_credentials'); }
    };
    return {
      read: (provider, options) => { scoped(provider); return this.tx(read, options); },
      list: options => this.tx(async db => { const c = await read(db); return c ? [{ providerId: connection.provider, type: c.type }] : []; }, options),
      modify: (provider, fn, options) => {
        scoped(provider);
        return this.tx(async db => {
          const current = await read(db);
          const next = await fn(current);
          if (next === undefined) return current;
          const bytes = await this.seal(Buffer.from(JSON.stringify(credential(next))));
          check(bytes.length > 0 && bytes.length <= 65536, 'credential_storage_failed');
          db.prepare('INSERT OR REPLACE INTO credentials VALUES (?, ?)').run(namespace, bytes);
          return next;
        }, options);
      },
      delete: (provider, options) => { scoped(provider); return this.tx(db => { db.prepare('DELETE FROM credentials WHERE namespace=?').run(namespace); }, options); },
    };
  }
  async apiKeys(connection, keys, options) {
    check(connection.auth.type === 'api_key' && connection.auth.stored === true, 'stored_keys_unavailable');
    const namespace = JSON.stringify(['api_keys', connection.id, connection.provider]);
    const valid = values => Array.isArray(values) && values.length <= 100 && values.every(k =>
      typeof k === 'string' && k.trim().length > 0 && Buffer.byteLength(k) <= 16384 && !/[\x00-\x1f\x7f]/.test(k));
    if (keys !== undefined) check(valid(keys) && new Set(keys).size === keys.length, 'invalid_api_keys');
    return this.tx(async db => {
      if (keys !== undefined) {
        if (!keys.length) db.prepare('DELETE FROM credentials WHERE namespace=?').run(namespace);
        else {
          const raw = Buffer.from(JSON.stringify(keys));
          check(raw.length <= 65536, 'credential_too_large');
          const bytes = await this.seal(raw);
          check(bytes.length > 0 && bytes.length <= 65536, 'credential_storage_failed');
          db.prepare('INSERT OR REPLACE INTO credentials VALUES (?, ?)').run(namespace, bytes);
        }
        return keys;
      }
      const row = db.prepare('SELECT value FROM credentials WHERE namespace=?').get(namespace);
      if (!row) return [];
      try {
        const values = JSON.parse(Buffer.from(await this.unseal(Buffer.from(row.value))).toString('utf8'));
        check(valid(values), 'corrupt_credentials');
        return values;
      } catch { throw new GatewayError('corrupt_credentials'); }
    }, options);
  }
  async deviceId() { return this.tx(db => db.prepare('SELECT value FROM meta WHERE key=?').get('device').value); }
  async fingerprints(values, options) {
    return this.tx(db => {
      const salt = db.prepare('SELECT value FROM meta WHERE key=?').get('salt').value;
      check(typeof salt === 'string' && /^[a-f0-9]{64}$/.test(salt), 'corrupt_state');
      return values.map(value => createHmac('sha256', salt).update(value).digest('hex'));
    }, options);
  }
  async pool(scope, fingerprints, change, options) {
    return this.tx(db => {
      const row = db.prepare('SELECT value FROM pools WHERE scope=?').get(scope);
      let p;
      try { p = row ? JSON.parse(row.value) : { cursor: 0, health: {} }; } catch { throw new GatewayError('corrupt_pool'); }
      check(Number.isSafeInteger(p.cursor) && p.cursor >= 0 && p.health && typeof p.health === 'object' && !Array.isArray(p.health), 'corrupt_pool');
      p.health = Object.fromEntries(fingerprints.map(fp => {
        const h = p.health[fp] || { invalid: false, until: 0 };
        check(typeof h.invalid === 'boolean' && Number.isFinite(h.until) && h.until >= 0, 'corrupt_pool');
        return [fp, h];
      }));
      const result = change(p);
      db.prepare('INSERT OR REPLACE INTO pools VALUES (?, ?)').run(scope, JSON.stringify(p));
      return result;
    }, options);
  }
}
