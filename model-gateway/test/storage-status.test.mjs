import test from 'node:test';
import assert from 'node:assert/strict';
import { credentialProtection, State } from '../state.mjs';
import { ModelControl } from '../control.mjs';
import { emptyConfig } from '../config.mjs';

test('credential protection reports new-write capability without claiming legacy files were migrated', () => {
  const passphrase = { GYM_GATEWAY_PASSPHRASE: 'synthetic long passphrase' };
  assert.deepEqual(credentialProtection('win32', passphrase), {
    storage: 'WINDOWS_USER_DPAPI', legacy_plaintext_possible: false,
  });
  for (const platform of ['linux', 'darwin']) {
    assert.deepEqual(credentialProtection(platform, passphrase), {
      storage: 'PRIVATE_FILE_PASSPHRASE_SEALED', legacy_plaintext_possible: true,
    });
    assert.deepEqual(credentialProtection(platform, { GYM_GATEWAY_PLAINTEXT: '1' }), {
      storage: 'PRIVATE_FILE_PLAINTEXT', legacy_plaintext_possible: true,
    });
    for (const env of [{}, { GYM_GATEWAY_PASSPHRASE: 'short' }, { GYM_GATEWAY_PLAINTEXT: '0' }]) {
      assert.deepEqual(credentialProtection(platform, env), {
        storage: 'CREDENTIAL_PROTECTION_UNAVAILABLE', legacy_plaintext_possible: true,
      });
    }
    assert.equal(credentialProtection(platform, { ...passphrase, GYM_GATEWAY_PLAINTEXT: '1' }).storage,
      'PRIVATE_FILE_PASSPHRASE_SEALED');
  }
});

test('state owns protection metadata and status forwards it without exposing the passphrase', async () => {
  const state = new State();
  assert.deepEqual(state.protection(), credentialProtection());
  state.config = async () => emptyConfig();
  const control = new ModelControl(state);
  for (const platform of ['win32', 'linux', 'darwin']) {
    for (const env of [{}, { GYM_GATEWAY_PLAINTEXT: '1' }, { GYM_GATEWAY_PASSPHRASE: 'synthetic long passphrase' }]) {
      const expected = credentialProtection(platform, env);
      state.protection = () => expected;
      const status = await control.request({ action: 'status' });
      assert.equal(status.storage, expected.storage);
      assert.equal(status.legacy_plaintext_possible, expected.legacy_plaintext_possible);
      assert.equal(status.funded_authority, false);
      assert.equal(JSON.stringify(status).includes('synthetic long passphrase'), false);
    }
  }
});
