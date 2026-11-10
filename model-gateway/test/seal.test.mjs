// S-1: off Windows, credentials are sealed under a user-held passphrase, or refused; never silently plaintext.
import test from 'node:test';
import assert from 'node:assert/strict';
import { passphraseSeal, passphraseUnseal } from '../state.mjs';

function env(values, body) {
  const keys = ['GYM_GATEWAY_PASSPHRASE', 'GYM_GATEWAY_PLAINTEXT'];
  const saved = Object.fromEntries(keys.map(k => [k, process.env[k]]));
  for (const k of keys) delete process.env[k];
  Object.assign(process.env, values);
  return Promise.resolve(body()).finally(() => { for (const k of keys) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; } });
}

const secret = Buffer.from('{"type":"oauth","access":"a-very-secret-token","refresh":"r","expires":1}');

test('sealed blobs hide the secret and round-trip with the passphrase only', () => env({ GYM_GATEWAY_PASSPHRASE: 'correct horse battery' }, async () => {
  const blob = await passphraseSeal(secret);
  assert.ok(!blob.includes(Buffer.from('a-very-secret-token')));
  assert.deepEqual(await passphraseUnseal(blob), secret);
  const other = await passphraseSeal(secret);
  assert.notDeepEqual(blob, other); // fresh salt and nonce every time
  process.env.GYM_GATEWAY_PASSPHRASE = 'a different passphrase';
  await assert.rejects(passphraseUnseal(blob), { code: 'credential_storage_failed' });
  const tampered = Buffer.from(blob); tampered[tampered.length - 1] ^= 1;
  process.env.GYM_GATEWAY_PASSPHRASE = 'correct horse battery';
  await assert.rejects(passphraseUnseal(tampered), { code: 'credential_storage_failed' });
}));

test('without a passphrase storage is refused unless plaintext is explicitly accepted', () => env({}, async () => {
  await assert.rejects(passphraseSeal(secret), { code: 'credential_protection_unavailable' });
  process.env.GYM_GATEWAY_PLAINTEXT = '1';
  assert.deepEqual(await passphraseSeal(secret), secret);
  assert.deepEqual(await passphraseUnseal(secret), secret); // a legacy plaintext blob is still readable
}));

test('a sealed blob cannot be opened once the passphrase is gone', () => env({ GYM_GATEWAY_PASSPHRASE: 'correct horse battery' }, async () => {
  const blob = await passphraseSeal(secret);
  delete process.env.GYM_GATEWAY_PASSPHRASE;
  await assert.rejects(passphraseUnseal(blob), { code: 'credential_protection_unavailable' });
}));
