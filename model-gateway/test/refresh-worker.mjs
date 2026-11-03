import { State } from '../state.mjs';
import { createModels, createProvider } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { setTimeout as sleep } from 'node:timers/promises';
const state = await new State(process.argv[2], { seal: async b => b, unseal: async b => b }).init();
const c = { id: 'account', provider: 'test' };
if (process.argv[3] === 'hold') {
  await state.credentials(c).modify('test', async old => { console.log('locked'); await sleep(60000); return old; });
} else {
  const models = createModels({ credentials: state.credentials(c), authContext: { env: async () => undefined, fileExists: async () => false } });
  models.setProvider(createProvider({ id: 'test', models: [], api: openAICompletionsApi(), auth: { oauth: {
    name: 'test', login: async () => { throw new Error('not used'); },
    refresh: async old => { await sleep(150); return { ...old, access: 'refreshed', expires: Date.now() + 3600000, refreshCount: (old.refreshCount || 0) + 1 }; },
    toAuth: async c => ({ apiKey: c.access }),
  } } }));
  await models.getAuth('test');
  console.log('done');
}
