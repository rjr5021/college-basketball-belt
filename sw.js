/* Service worker (CBB-7 parity with the College Football Belt): pages come from the network
 * first and fall back to the last copy seen, or to /offline.html; styles, scripts and icons are
 * served from cache and refreshed in the background. Only same-origin GET requests are touched. */
var V = "belt-v1", OFF = "/offline.html", MAX_PAGES = 60;
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(V).then(function (c) { return c.addAll([OFF, "/favicon.png"]); }));
  self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== V; }).map(function (k) { return caches.delete(k); }));
  }));
  self.clients.claim();
});
function trim(c) {
  c.keys().then(function (ks) {
    var pages = ks.filter(function (r) { return !/\.(css|js|png|ico|svg|json|woff2?)(\?|$)/.test(r.url); });
    if (pages.length > MAX_PAGES) pages.slice(0, pages.length - MAX_PAGES).forEach(function (r) { c.delete(r); });
  });
}
self.addEventListener("fetch", function (e) {
  var r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).then(function (resp) {
      if (resp.ok) { var cp = resp.clone(); caches.open(V).then(function (c) { c.put(r, cp); trim(c); }); }
      return resp;
    }).catch(function () {
      return caches.match(r).then(function (x) { return x || caches.match(OFF); });
    }));
    return;
  }
  if (/\.(css|js|png|ico|svg|woff2?)$/.test(u.pathname)) {
    e.respondWith(caches.match(r).then(function (x) {
      var f = fetch(r).then(function (resp) {
        if (resp.ok) { var cp = resp.clone(); caches.open(V).then(function (c) { c.put(r, cp); }); }
        return resp;
      }).catch(function () { return x; });
      return x || f;
    }));
  }
});
