// Real local HTTP checks, no Flask models or external network. Do not load .env.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { resolve } from 'node:path'

test('Vite rejects dataset labels and private backend files over HTTP', async () => {
  const server = await createServer({ configFile: resolve('vite.config.js'), envFile: false,
    server: { host: '127.0.0.1', port: 0, open: false, watch: null }, logLevel: 'silent' })
  await server.listen()
  try {
    const address = server.httpServer.address()
    const base = `http://127.0.0.1:${address.port}`
    for (const path of ['/answer.jsonl', '/answer.jsonl?raw', '/answer.jsonl?import', '/%61nswer.jsonl',
      '/backend/app.py', '/backend/output/final_result.json', '/backend/research_data/research.sqlite3',
      '/@fs/' + resolve('answer.jsonl').replaceAll('\\', '/')]) {
      const response = await fetch(base + path)
      assert.equal(response.status, 403, path)
    }
    assert.equal((await fetch(base + '/')).status, 200)
    assert.equal((await fetch(base + '/src/App.vue')).status, 200)
  } finally { await server.close() }
})
