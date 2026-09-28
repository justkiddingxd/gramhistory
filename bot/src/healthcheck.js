import { readFileSync } from 'node:fs';
try {
  const health = JSON.parse(readFileSync('/tmp/gramhistory-health.json', 'utf8'));
  if (Date.now() - health.updated_at > 45000 || Date.now() - health.last_poll_at > 120000) process.exit(1);
} catch { process.exit(1); }
