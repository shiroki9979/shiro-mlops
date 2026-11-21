// spa-rewrite: CloudFront Function (cloudfront-js-2.0), viewer-request on the default behavior only
// (forecast-view-hosting.md §2). A request whose last path segment has no "." is a client-side
// route ("/", "/history", "/history/"), so it is served /index.html; anything else, such as
// /assets/x.js or /favicon.ico, passes through and a missing object stays a 403 from S3.
// Only the uri changes: querystring, headers and method go to the origin as received.
// The runtime takes a top-level handler and supports neither export nor module.exports;
// Terraform reads this file with file() and spa-rewrite.test.mjs runs the same file.
function handler(event) {
  const request = event.request
  const lastSegment = request.uri.slice(request.uri.lastIndexOf('/') + 1)
  if (!lastSegment.includes('.')) {
    request.uri = '/index.html'
  }
  return request
}
