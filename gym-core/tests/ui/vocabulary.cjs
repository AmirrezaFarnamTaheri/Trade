// The UI's single vocabulary (workspace-config.js) as a plain object, for component tests that run one script alone.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../src/gym/ui/workspace-config.js'), 'utf8');
const start = source.indexOf('const vocabulary = {');
const end = source.indexOf('const T = Object.fromEntries(');
const tail = source.slice(end, source.indexOf(';', source.indexOf(']));', end)) + 1);
const sandbox = {};
vm.runInNewContext(source.slice(start, end) + tail + '\nglobalThis.T = T;', sandbox);
module.exports = { T: sandbox.T };
