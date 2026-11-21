// Offline tests for the spa-rewrite CloudFront Function (forecast-view-hosting.md §2). The test
// runs the same file Terraform reads with file(), in a fresh node:vm context, because the
// CloudFront runtime takes a top-level handler and supports neither export nor module.exports.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'
import vm from 'node:vm'

const SOURCE = readFileSync(new URL('./spa-rewrite.js', import.meta.url), 'utf8')

function loadHandler() {
  const context = vm.createContext({})
  vm.runInContext(SOURCE, context, { filename: 'spa-rewrite.js' })
  assert.equal(typeof context.handler, 'function', 'spa-rewrite.js must declare a top-level handler')
  return context.handler
}

function viewerRequest(uri, querystring = {}) {
  return {
    version: '1.0',
    context: { eventType: 'viewer-request' },
    viewer: { ip: '192.0.2.1' },
    request: {
      method: 'GET',
      uri,
      querystring,
      headers: { host: { value: 'd111111abcdef8.cloudfront.net' } },
      cookies: {},
    },
  }
}

describe('spa-rewrite', () => {
  const handler = loadHandler()

  it('rewrites the root path to /index.html', () => {
    assert.equal(handler(viewerRequest('/')).uri, '/index.html')
  })

  for (const uri of ['/history', '/history/', '/console/foo']) {
    it(`rewrites the extensionless path ${uri} to /index.html`, () => {
      assert.equal(handler(viewerRequest(uri)).uri, '/index.html')
    })
  }

  it('keeps the querystring of a rewritten request as it was', () => {
    const querystring = { range: { value: '7d' }, tag: { value: 'a', multiValue: [{ value: 'a' }, { value: 'b' }] } }

    const request = handler(viewerRequest('/history', querystring))

    assert.equal(request.uri, '/index.html')
    assert.deepEqual(request.querystring, {
      range: { value: '7d' },
      tag: { value: 'a', multiValue: [{ value: 'a' }, { value: 'b' }] },
    })
  })

  for (const uri of ['/assets/x.js', '/favicon.ico']) {
    it(`passes ${uri} through unchanged, since its last segment has an extension`, () => {
      assert.equal(handler(viewerRequest(uri)).uri, uri)
    })
  }
})
