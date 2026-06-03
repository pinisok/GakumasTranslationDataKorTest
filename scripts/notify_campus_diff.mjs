#!/usr/bin/env node
/**
 * Send campus diff notifications to Discord.
 *
 * The message is split by target and file type so very large diffs remain readable.
 * Large groups are automatically chunked to stay under Discord's message limit.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const WORKDIR = path.resolve(__dirname, '..');
const MANIFEST_DIR = path.join(WORKDIR, 'res', '.manifest');
const DEFAULT_ENV_CANDIDATES = [
  process.env.NANOCLAW_ENV_FILE || '',
  '/workspace/extra/host-worker/nanoclaw-v2/.env',
  '/root/worker/nanoclaw-v2/.env',
].filter(Boolean);
const DEFAULT_DM_CHANNEL_ID = '1509419779516268615';
const DISCORD_API = 'https://discord.com/api/v10';
const DISCORD_SAFE_LIMIT = 1800;

function loadEnvFile(envPath) {
  const env = {};
  if (!fs.existsSync(envPath)) return env;
  try {
    const content = fs.readFileSync(envPath, 'utf8');
    for (const raw of content.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const idx = line.indexOf('=');
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
      env[key] = value;
    }
  } catch (e) {
    console.error(`[notify] failed to read env file ${envPath}: ${e}`);
  }
  return env;
}

const envFile = Object.assign({}, ...DEFAULT_ENV_CANDIDATES.map((p) => loadEnvFile(p)));

function getSetting(name, fallback = '') {
  const v = (process.env[name] || '').trim();
  if (v) return v;
  return (envFile[name] || fallback).trim();
}

function loadDiff(target) {
  const file = path.join(MANIFEST_DIR, `${target}.diff.json`);
  if (!fs.existsSync(file)) return null;
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    console.error(`[notify] failed to parse ${file}: ${e}`);
    return null;
  }
}

function campusVersion(diff) {
  const prev = diff?.previous_campus || {};
  const curr = diff?.current_campus || {};
  const parts = [];

  const addChange = (label, prevValue, currValue, short = false) => {
    if (currValue === undefined || currValue === null || currValue === '') return;
    if (prevValue === undefined || prevValue === null || prevValue === '') {
      parts.push(short && typeof currValue === 'string' ? `${label} ${currValue.slice(0, 8)}…` : `${label} ${currValue}`);
      return;
    }
    if (prevValue !== currValue) {
      parts.push(
        short
          ? `${label} ${String(prevValue).slice(0, 8)}… → ${String(currValue).slice(0, 8)}…`
          : `${label} ${prevValue} → ${currValue}`,
      );
    }
  };

  addChange('octoCacheRevision', prev.octoCacheRevision, curr.octoCacheRevision);
  addChange('masterVersion', prev.masterVersion, curr.masterVersion, true);
  addChange('appVersion', prev.appVersion, curr.appVersion);
  return parts.join(' / ');
}

function extOf(filePath) {
  const ext = path.posix.extname(String(filePath)).trim().toLowerCase();
  return ext ? ext.slice(1).toUpperCase() : 'NO EXT';
}

function normalizePaths(items, key = null) {
  return (items || [])
    .map((item) => (key ? item?.[key] : item))
    .filter(Boolean)
    .map((s) => String(s));
}

function groupChangesByType(diff) {
  const grouped = new Map();
  const addItem = (status, filePath) => {
    if (!filePath) return;
    const type = extOf(filePath);
    if (!grouped.has(type)) grouped.set(type, { added: [], modified: [], removed: [] });
    grouped.get(type)[status].push(filePath);
  };

  for (const filePath of normalizePaths(diff?.added)) addItem('added', filePath);
  for (const filePath of normalizePaths(diff?.removed)) addItem('removed', filePath);
  for (const filePath of normalizePaths(diff?.modified, 'path')) addItem('modified', filePath);

  return grouped;
}

function splitIntoChunks(items, overhead = 0, limit = DISCORD_SAFE_LIMIT) {
  const chunks = [];
  let current = [];
  let currentLen = overhead;

  for (const item of items) {
    const addLen = (current.length ? 2 : 0) + item.length;
    if (current.length && currentLen + addLen > limit) {
      chunks.push(current);
      current = [item];
      currentLen = overhead + item.length;
      continue;
    }
    current.push(item);
    currentLen += addLen;
  }

  if (current.length) chunks.push(current);
  return chunks;
}

function formatStatusBlocks(statusLabel, items) {
  if (!items.length) return [];
  const joinedPreview = items.join(', ');
  const baseOverhead = `    - ${statusLabel} (${items.length})\n      `.length;
  if (baseOverhead + joinedPreview.length <= DISCORD_SAFE_LIMIT) {
    return [`    - ${statusLabel} (${items.length})`, `      ${joinedPreview}`];
  }

  const chunks = splitIntoChunks(items, `    - ${statusLabel} (${items.length})\n      `.length);
  const lines = [`    - ${statusLabel} (${items.length})`];
  chunks.forEach((chunk, idx) => {
    lines.push(`      ${idx + 1}. ${chunk.join(', ')}`);
  });
  return lines;
}

function buildTargetBlocks(label, diff) {
  const summary = diff?.summary || {};
  const plus = Number(summary['+'] || 0);
  const minus = Number(summary['-'] || 0);
  const modified = Number(summary['~'] || 0);
  if (!plus && !minus && !modified) return [];

  const grouped = groupChangesByType(diff);
  const types = [...grouped.keys()].sort((a, b) => {
    if (a === 'NO EXT') return 1;
    if (b === 'NO EXT') return -1;
    return a.localeCompare(b, 'en');
  });

  const blocks = [`- ${label}: +${plus} ~${modified} -${minus}`];
  for (const type of types) {
    const g = grouped.get(type);
    blocks.push(`  • ${type}`);
    const statusOrder = [
      ['added', '추가'],
      ['modified', '수정'],
      ['removed', '삭제'],
    ];
    for (const [statusKey, statusLabel] of statusOrder) {
      const items = g[statusKey];
      if (!items.length) continue;
      blocks.push(...formatStatusBlocks(statusLabel, items));
    }
  }
  return blocks;
}

function buildMessages() {
  const adv = loadDiff('adv');
  const masterdb = loadDiff('masterdb');
  if (!adv && !masterdb) return [];

  const header = ['📦 캠퍼스 갱신 감지'];
  const cv = campusVersion(adv) || campusVersion(masterdb);
  if (cv) header.push(`캠퍼스 버전: ${cv}`);

  const messages = [];
  const pushBlocks = (blocks) => {
    if (!blocks?.length) return;
    const lines = [...header, ...blocks];
    const message = lines.join('\n');
    if (message.length <= DISCORD_SAFE_LIMIT) {
      messages.push(message);
      return;
    }

    // If the block is still too large, split by line while keeping the header.
    let current = [...header];
    for (const line of blocks) {
      const next = [...current, line].join('\n');
      if (next.length > DISCORD_SAFE_LIMIT && current.length > header.length) {
        messages.push(current.join('\n'));
        current = [...header, line];
      } else {
        current.push(line);
      }
    }
    if (current.length > header.length) messages.push(current.join('\n'));
  };

  if (adv) pushBlocks(buildTargetBlocks('ADV', adv));
  if (masterdb) pushBlocks(buildTargetBlocks('MasterDB2', masterdb));

  return messages;
}

async function postDiscordMessage(token, channelId, content) {
  const res = await fetch(`${DISCORD_API}/channels/${channelId}/messages`, {
    method: 'POST',
    headers: {
      Authorization: `Bot ${token}`,
      'Content-Type': 'application/json; charset=utf-8',
    },
    body: JSON.stringify({
      content,
      allowed_mentions: { parse: [] },
    }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Discord API returned HTTP ${res.status} ${res.statusText}${detail ? `\n${detail}` : ''}`);
  }
}

async function main() {
  const messages = buildMessages();
  if (!messages.length) {
    console.log('[notify] no campus diff to announce');
    return 0;
  }

  const channelId =
    getSetting('NANOCLAW_DISCORD_DM_CHANNEL_ID') ||
    getSetting('DISCORD_DM_CHANNEL_ID') ||
    DEFAULT_DM_CHANNEL_ID;
  const token = getSetting('DISCORD_BOT_TOKEN');
  if (!token) {
    console.error('[notify] DISCORD_BOT_TOKEN missing — skipping Discord notification');
    return 0;
  }

  if (process.env.DISCORD_DRY_RUN === '1') {
    console.log('[notify] dry-run messages follow:\n');
    for (const [idx, message] of messages.entries()) {
      console.log(`--- message ${idx + 1}/${messages.length} ---`);
      console.log(message);
    }
    return 0;
  }

  try {
    for (const message of messages) {
      await postDiscordMessage(token, channelId, message);
    }
    console.log(`[notify] Discord update sent to channel ${channelId} (${messages.length} message(s))`);
  } catch (e) {
    console.error(`[notify] Discord notify failed: ${e?.message || e}`);
  }

  return 0;
}

await main();
