/* Node built-in tests for static/dataport.js. No npm dependencies. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {
  createDataPort,
  ConflictError,
  normalizeLegacy,
  toLegacySnapshot,
} = require(path.join(__dirname, '..', '..', 'static', 'dataport.js'));

function json(status, body) {
  return new Response(body == null ? '' : JSON.stringify(body), {
    status,
    headers: body == null ? {} : { 'Content-Type': 'application/json' },
  });
}

function mockFetch(handler) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const call = { url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null };
    calls.push(call);
    return handler(call);
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

function v2Status(mode, extra = {}) {
  return {
    data_mode: mode,
    contract_version: '2.0',
    schema_version: 1,
    fallback: mode !== 'v2_ready',
    reason: 'test',
    legacy: { available: true, initialized: true, note_count: 1, tag_count: 1, error: null },
    v2: { schema_ready: mode === 'v2_ready', migration_version: mode === 'v2_ready' ? 1 : null, note_count: 1, tag_count: 1 },
    ...extra,
  };
}

function notePayload(overrides = {}) {
  return {
    id: 'n1',
    title: '笔记一',
    content_html: '<p>正文</p>',
    tags: [{ id: 't1', name: '工作', color: '#7c83e6' }],
    is_favorite: false,
    is_trashed: false,
    created_at: '2026-11-20T00:00:00.000Z',
    updated_at: '2026-11-21T00:00:00.000Z',
    revision: 3,
    ...overrides,
  };
}

test('normalizes legacy snapshot and strips extension fields on write', () => {
  const data = normalizeLegacy({
    notes: [{ id: 'a', title: 'A', html: '', tags: null, fav: 1, trashed: 0, created: 1, updated: 2, revision: 9 }],
    tags: [{ id: 't', name: '标签' }],
    ui: { theme: 'dark' },
  });
  assert.equal(data.notes[0].fav, true);
  assert.deepEqual(data.notes[0].tags, []);
  assert.equal(data.ui.theme, 'dark');
  const snapshot = toLegacySnapshot(data);
  assert.equal(snapshot.notes[0].revision, undefined);
  assert.equal(snapshot.notes[0].fav, true);
});

test('legacy fallback when status endpoint is absent never calls v2 data', async () => {
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(404, { detail: 'Not Found' });
    if (call.url === '/api/state' && call.method === 'GET') {
      return json(200, { initialized: true, state: {
        notes: [{ id: 'a', title: '旧笔记', html: '', tags: [], fav: false, trashed: false, created: 1, updated: 2 }],
        tags: [],
        ui: { theme: 'dark' },
      } });
    }
    if (call.url === '/api/state' && call.method === 'PUT') return json(200, { saved: true });
    if (call.url.startsWith('/api/v2/')) throw new Error('v2 data endpoint must not be called');
    return json(404, {});
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  const opened = await port.open();
  assert.equal(opened.mode, 'legacy');
  assert.equal(opened.snapshot.notes[0].title, '旧笔记');
  await port.saveLegacy(opened.snapshot);
  assert.ok(fetchImpl.calls.some(call => call.url === '/api/state' && call.method === 'PUT'));
  assert.ok(!fetchImpl.calls.some(call => call.url.startsWith('/api/v2/notes')));
});

test('status failure does not fall back to legacy writes', async () => {
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(503, { detail: '无法读取数据状态' });
    throw new Error('must not write or read legacy when the mode is unknown: ' + call.url);
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  await assert.rejects(
    () => port.open(),
    error => error.code === 'status_unavailable' && error.status === 503,
  );
  assert.equal(fetchImpl.calls.some(call => call.url === '/api/state'), false);
});

test('migration_pending and migration_failed use legacy and never v2 writes', async () => {
  for (const mode of ['migration_pending', 'migration_failed']) {
    const fetchImpl = mockFetch(call => {
      if (call.url === '/api/v2/status') return json(200, v2Status(mode));
      if (call.url === '/api/state' && call.method === 'GET') return json(200, { initialized: false, state: null });
      if (call.url === '/api/state' && call.method === 'PUT') return json(200, { saved: true });
      throw new Error('unexpected call: ' + call.method + ' ' + call.url);
    });
    const port = createDataPort({ fetchImpl, logger: () => {} });
    const opened = await port.open();
    assert.equal(opened.mode, mode);
    assert.equal(port.adapter, 'legacy');
    assert.equal(opened.snapshot, null);
    await port.saveLegacy({ notes: [], tags: [], ui: {} });
    assert.throws(() => port.createNote({ title: 'x' }, []), /禁止调用 V2/);
  }
});

test('v2_ready reads tags/settings/live+trashed pages and writes only v2', async () => {
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(200, v2Status('v2_ready'));
    if (call.url === '/api/v2/tags') return json(200, [{ id: 't1', name: '工作', color: '#7c83e6' }]);
    if (call.url === '/api/v2/settings') return json(200, { theme: 'dark', layout: 'grid', sort: 'created', locale: 'zh-CN' });
    if (call.url.includes('trashed=false')) return json(200, { items: [notePayload()], total: 1, page: 1, page_size: 100 });
    if (call.url.includes('trashed=true')) return json(200, { items: [notePayload({ id: 'n2', title: '回收站', is_trashed: true })], total: 1, page: 1, page_size: 100 });
    if (call.url === '/api/v2/notes' && call.method === 'POST') {
      return json(201, notePayload({ id: 'n3', title: call.body.title, revision: 1 }));
    }
    if (call.url === '/api/v2/notes/n1' && call.method === 'PATCH') {
      throw new Error('conflict route should be tested separately');
    }
    throw new Error('unexpected call: ' + call.method + ' ' + call.url);
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  const opened = await port.open();
  assert.equal(opened.mode, 'v2_ready');
  assert.equal(opened.snapshot.notes.length, 2);
  assert.equal(opened.snapshot.notes[1].trashed, true);
  assert.equal(opened.snapshot.notes[0].revision, 3);
  assert.equal(opened.snapshot.ui.layout, 'grid');

  const created = await port.createNote({ id: 'local', title: '新笔记', html: '<p>x</p>', tags: ['t1'] }, [{ id: 't1', name: '工作', color: '#7c83e6' }]);
  assert.equal(created.id, 'n3');
  assert.equal(fetchImpl.calls.some(call => call.url === '/api/state'), false);
});

test('v2 revision conflict raises a typed error with server detail', async () => {
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(200, v2Status('v2_ready'));
    if (call.url === '/api/v2/tags') return json(200, [{ id: 't1', name: '工作', color: '#7c83e6' }]);
    if (call.url === '/api/v2/settings') return json(200, { theme: 'light', layout: 'list', sort: 'updated' });
    if (call.url.includes('/api/v2/notes?')) return json(200, { items: [notePayload()], total: 1 });
    if (call.url === '/api/v2/notes/n1' && call.method === 'PATCH') {
      return json(409, { detail: '笔记已被修改: 当前 revision=7' });
    }
    throw new Error('unexpected call: ' + call.method + ' ' + call.url);
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  await port.open();
  await assert.rejects(
    () => port.updateNote({ id: 'n1', title: '冲突', html: '', tags: [], revision: 3 }, []),
    error => error instanceof ConflictError && error.status === 409 && /revision=7/.test(error.message),
  );
});

test('v2 load failure does not fall back to legacy writes', async () => {
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(200, v2Status('v2_ready'));
    if (call.url.startsWith('/api/v2/')) return json(503, { detail: 'V2 数据库尚未迁移' });
    throw new Error('legacy endpoint must not be called after v2_ready detection');
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  const opened = await port.open();
  assert.equal(opened.mode, 'v2_ready');
  assert.equal(opened.snapshot, null);
  assert.equal(port.adapter, 'v2');
  await assert.rejects(() => port.saveLegacy({ notes: [], tags: [], ui: {} }), /双重写入/);
});

test('createNote maps local tag ids by name and creates a missing tag once', async () => {
  let tags = [{ id: 't1', name: '工作', color: '#7c83e6' }];
  const fetchImpl = mockFetch(call => {
    if (call.url === '/api/v2/status') return json(200, v2Status('v2_ready'));
    if (call.url === '/api/v2/tags' && call.method === 'GET') return json(200, tags);
    if (call.url === '/api/v2/tags' && call.method === 'POST') {
      const tag = { id: 't2', name: call.body.name, color: call.body.color };
      tags = tags.concat(tag);
      return json(201, tag);
    }
    if (call.url === '/api/v2/settings') return json(200, { theme: 'light', layout: 'list', sort: 'updated' });
    if (call.url.includes('/api/v2/notes?')) return json(200, { items: [], total: 0 });
    if (call.url === '/api/v2/notes' && call.method === 'POST') {
      assert.deepEqual(call.body.tags, ['t1', 't2']);
      return json(201, notePayload({ id: 'n9', tags: tags.map(t => ({ id: t.id, name: t.name, color: t.color })) }));
    }
    throw new Error('unexpected call: ' + call.method + ' ' + call.url);
  });
  const port = createDataPort({ fetchImpl, logger: () => {} });
  await port.open();
  const created = await port.createNote({
    title: '带本地标签', html: '', tags: ['t1', 'local-tag'],
  }, [
    { id: 't1', name: '工作', color: '#7c83e6' },
    { id: 'local-tag', name: '新标签', color: '#f5a524' },
  ]);
  assert.equal(created.id, 'n9');
  assert.equal(fetchImpl.calls.filter(call => call.url === '/api/v2/tags' && call.method === 'POST').length, 1);
});
