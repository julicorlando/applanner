// Provider error objects may contain request headers or session keys.
// Keep stable diagnostic identifiers; discard provider messages and stacks.
export const loggerOptions = {
  level: 'warn',
  serializers: {
    error: error => ({name: error?.name || 'Error', code: error?.code}),
    err: error => ({name: error?.name || 'Error', code: error?.code}),
  },
  redact: {
    paths: ['auth', 'creds', 'keys', 'token', 'password', 'headers.authorization',
      'req.headers.authorization', '*.password', '*.access_token', '*.token'],
    censor: '[REDACTED]',
  },
};
