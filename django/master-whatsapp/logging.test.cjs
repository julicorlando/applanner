const {test} = require('node:test');
const assert = require('node:assert/strict');
const pino = require('pino');

test('gateway log preserves error class but never headers, keys or provider exception text', async () => {
  const {loggerOptions} = await import('./logging.js');
  let output = '';
  const logger = pino(loggerOptions, {write: text => {output += text;}});
  const error = new Error('provider echoed sensitive-session-data');
  error.config = {headers: {authorization: 'sensitive-bearer-data'}};
  logger.error({error, headers: {authorization: 'sensitive-bearer-data'},
    auth: {keys: 'sensitive-session-data'}}, 'Gateway unavailable');
  assert.ok(output.includes('Gateway unavailable'));
  assert.ok(output.includes('Error'));
  assert.ok(!output.includes('sensitive-session-data'));
  assert.ok(!output.includes('sensitive-bearer-data'));
});
