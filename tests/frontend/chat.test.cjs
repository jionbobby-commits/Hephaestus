/* Node built-in tests for static/chat.js and the C3 DataPort AI bridge. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const chat = require(path.join(__dirname, '..', '..', 'static', 'chat.js'));
const {
  createDataPort, createSseParser, setCapabilityResolver, setClientPlatform,
} = require(path.join(__dirname, '..', '..', 'static', 'dataport.js'));

function json(status, body) {
  return new Response(body == null ? '' : JSON.stringify(body), {
    status,
    headers: body == null ? {} : { 'Content-Type': 'application/json' },
  });
}

function v2Status() {
  return {
    data_mode: 'v2_ready', contract_version: '2.0', schema_version: 1,
    fallback: false, reason: 'test',
    legacy: { available: true, initialized: true, note_count: 0, tag_count: 0, error: null },
    v2: { schema_ready: true, migration_version: 1, note_count: 0, tag_count: 0 },
  };
}

function mockEnv(handler) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const call = {
      url, method: options.method || 'GET', headers: options.headers || {},
      body: options.body ? JSON.parse(options.body) : null,
    };
    calls.push(call);
    return handler(call);
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

test('SSE parser handles chunk boundaries and malformed events', () => {
  const events = [];
  const parser = createSseParser(event => events.push(event));
  parser.push('data: {"type":"sta');
  parser.push('rt","conversation_id":"c1"}\n\ndata: {"type":"delta","text":"你');
  parser.push('好"}\n\n');
  parser.flush();
  assert.deepEqual(events.map(e => e.type), ['start', 'delta']);
  assert.equal(events[1].text, '你好');

  const broken = [];
  const bad = createSseParser(event => broken.push(event));
  bad.push('data: {not-json}\n\n');
  assert.equal(broken[0].type, 'parse_error');
});

test('markdown escapes raw HTML, blocks javascript: links and neutralizes fences', () => {
  const html = chat.renderMarkdown('**hi** <img src=x onerror=alert(1)> [x](javascript:alert(1))');
  assert.ok(html.includes('<strong>hi</strong>'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(html.includes('x'));

  const safe = chat.renderMarkdown('[官网](https://example.com/a?b=1)');
  assert.ok(safe.includes('href="https://example.com/a?b=1"'));
  assert.ok(safe.includes('rel="noopener noreferrer nofollow"'));

  const fenced = chat.renderMarkdown('\u0060\u0060\u0060html\n<script>alert(1)</script>\n\u0060\u0060\u0060');
  assert.ok(!fenced.includes('<script>'));
  assert.ok(fenced.includes('&lt;script&gt;'));
  assert.ok(fenced.includes('data-code='));
});

test('chat reducer replaces optimistic messages and preserves stopped content', () => {
  let messages = [
    { id: 'local-u', role: 'user', content: '你好', clientId: 'c-1', optimistic: true },
    { id: 'local-a', role: 'assistant', content: '', status: 'pending', optimistic: true },
  ];
  let result = chat.applyChatEvent(messages, {
    type: 'start',
    user_message: { id: 'u1', role: 'user', content: '你好', client_id: 'c-1', status: 'complete' },
    assistant_message: { id: 'a1', role: 'assistant', content: '', status: 'streaming' },
  });
  assert.equal(result.messages.length, 2);
  assert.equal(result.messages[0].id, 'u1');
  assert.equal(result.messages[0].optimistic, false);
  assert.equal(result.messages[1].id, 'a1');
  assert.equal(result.streaming, true);

  result = chat.applyChatEvent(result.messages, { type: 'delta', message_id: 'a1', text: '你好' });
  assert.equal(result.messages[1].content, '你好');
  result = chat.applyChatEvent(result.messages, {
    type: 'stopped', message: { id: 'a1', role: 'assistant', content: '你好', status: 'stopped' },
  });
  assert.equal(result.stopped, true);
  assert.equal(result.finished, true);
  assert.equal(result.messages[1].content, '你好');
  assert.equal(result.messages[1].status, 'stopped');

  const failed = chat.applyChatEvent(result.messages, { type: 'error', error: 'provider_error', message: '连接失败' });
  assert.equal(failed.messages[1].status, 'error');
  assert.equal(failed.messages[1].errorCode, 'provider_error');
  assert.equal(failed.error, '连接失败');
});

test('persona preview shows name, style, custom prompt and fixed safety notice', () => {
  const text = chat.personaPreview({
    assistant_name: '阿尔法', assistant_style: 'academic', response_length: 'long',
    assistant_custom_prompt: '先给结论，再给证据。',
  });
  assert.ok(text.includes('阿尔法'));
  assert.ok(text.includes('学术研究'));
  assert.ok(text.includes('详细'));
  assert.ok(text.includes('先给结论，再给证据。'));
  assert.ok(text.includes('安全约束始终优先'));
});

test('DataPort AI bridge adds capability/platform headers and returns a raw SSE stream', async () => {
  setCapabilityResolver(async () => 'cap-test-token');
  setClientPlatform('desktop');
  const fetchImpl = mockEnv(call => {
    if (call.url === '/api/v2/status') return json(200, v2Status());
    if (call.url === '/api/v2/tags') return json(200, []);
    if (call.url === '/api/v2/settings' && call.method === 'GET') return json(200, { theme: 'dark', layout: 'list', sort: 'updated', locale: 'zh-CN' });
    if (call.url === '/api/v2/settings' && call.method === 'PATCH') {
      return json(200, { ...call.body, theme: 'dark', layout: 'list', sort: 'updated' });
    }
    if (call.url.includes('/api/v2/notes?')) return json(200, { items: [], total: 0 });
    if (call.url === '/api/v2/ai/conversations/c1/messages' && call.method === 'POST') {
      return new Response('data: {"type":"delta","text":"hi"}\n\n', {
        status: 200, headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    throw new Error('unexpected call: ' + call.method + ' ' + call.url);
  });
  const port = createDataPort({ fetchImpl, logger: () => {}, platform: 'desktop' });
  await port.open();
  const response = await port.sendAIMessage('c1', { content: 'hello', client_message_id: 'c-1', stream: true });
  const call = fetchImpl.calls.find(item => item.url === '/api/v2/ai/conversations/c1/messages');
  assert.equal(call.headers['X-Hephaestus-Capability'], 'cap-test-token');
  assert.equal(call.headers['X-Hephaestus-Platform'], 'desktop');
  assert.ok(!call.url.includes('cap-test-token'));
  assert.deepEqual(call.body, { content: 'hello', client_message_id: 'c-1', stream: true });
  const text = await response.text();
  assert.ok(text.includes('"type":"delta"'));

  const saved = await port.updateSettings({ assistant_name: '阿尔法', assistant_style: 'academic' });
  assert.equal(saved.assistant_name, '阿尔法');
});
