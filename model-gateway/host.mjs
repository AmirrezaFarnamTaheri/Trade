import { State } from './state.mjs';
import { ModelControl } from './control.mjs';
import { GatewayError } from './config.mjs';

const control = new ModelControl(await new State().init());
let pending = Buffer.alloc(0), queue = Promise.resolve(), count = 0;
process.stdin.on('data', chunk => {
  pending = Buffer.concat([pending, chunk]);
  if (pending.length > 2 * 1024 * 1024) { control.close(); process.exit(2); }
  let end;
  while ((end = pending.indexOf(10)) >= 0) {
    const line = pending.subarray(0, end); pending = pending.subarray(end + 1);
    if (++count > 8) { control.close(); process.exit(2); }
    queue = queue.then(async () => {
      let id;
      try {
        const input = JSON.parse(line.toString('utf8'));
        if (!Number.isSafeInteger(input.id) || Object.keys(input).some(k => !['id', 'action', 'value'].includes(k))) throw new GatewayError('invalid_request');
        id = input.id;
        const result = await control.request({ action: input.action, value: input.value });
        process.stdout.write(JSON.stringify({ id, result }) + '\n');
      } catch (error) {
        process.stdout.write(JSON.stringify({ id, error: error instanceof GatewayError ? error.code : 'model_control_failed' }) + '\n');
      } finally { count--; }
    });
  }
});
process.stdin.on('end', () => { control.close(); });
process.once('SIGTERM', () => { control.close(); process.exit(0); });
