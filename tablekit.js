/* tablekit: search, filters, sorting and pages for long belt tables.
   Each table ships its first 100 rows as HTML (and has real /page/N/ pages
   for search engines); the full list loads as JSON the moment someone
   filters, sorts or pages, and everything after that happens here. */
(function(){
  document.querySelectorAll('[data-tablekit]').forEach(function(root){
    var cfg = JSON.parse(root.getAttribute('data-tablekit'));
    var tbody = root.querySelector('tbody'), info = root.querySelector('.tk-info');
    var pagers = root.querySelectorAll('.tk-pager'), q = root.querySelector('.tk-q');
    var sels = root.querySelectorAll('select[data-f]'), ord = root.querySelectorAll('[data-order]');
    var ths = root.querySelectorAll('th[data-k]'), empty = root.querySelector('.tk-empty');
    var D = null, loading = null;
    var st = {q:'', f:{}, order:'default', k:null, dir:1, page:cfg.page||1};
    var P = new URLSearchParams(location.search);
    if (P.get('q')) { st.q = P.get('q'); q && (q.value = st.q); }
    sels.forEach(function(s){ var v = P.get(s.dataset.f); if (v) { s.value = v; st.f[s.dataset.f] = v; } });
    if (P.get('order')) st.order = P.get('order');
    if (P.get('sort')) { st.k = +P.get('sort'); st.dir = P.get('dir') === '-1' ? -1 : 1; }
    if (P.get('p')) st.page = +P.get('p');
    function isDefault(){ return !st.q && !Object.keys(st.f).some(function(k){return st.f[k];}) && st.order === 'default' && st.k === null; }
    function load(){ if (D) return Promise.resolve(D); if (!loading) loading = fetch(cfg.data).then(function(r){return r.json();}).then(function(j){ D = j; return j; }); return loading; }
    function fmt(n){ return n.toLocaleString('en-US'); }
    function rowsNow(){
      var s = st.q.trim().toLowerCase();
      var r = D.rows.filter(function(x){
        if (s && x.t.indexOf(s) === -1) return false;
        for (var k in st.f) { if (st.f[k] && String(x.f[k]) !== st.f[k]) return false; }
        return true;
      });
      if (st.k !== null) { var k = st.k, d = st.dir; r = r.slice().sort(function(a,b){ var x = a.k[k], y = b.k[k]; return (x < y ? -1 : x > y ? 1 : 0) * d; }); }
      else if (st.order === 'reverse') r = r.slice().reverse();
      return r;
    }
    function pagerHtml(page, total, link){
      if (total <= 1) return '';
      var nums = [1, total], out = [], last = 0;
      for (var n = page - 2; n <= page + 2; n++) if (n >= 1 && n <= total) nums.push(n);
      nums = nums.filter(function(v,i,a){return a.indexOf(v) === i;}).sort(function(a,b){return a-b;});
      if (page > 1) out.push(link(page - 1, '← Prev'));
      nums.forEach(function(n){ if (n - last > 1) out.push('<span class="tk-gap">…</span>'); out.push(n === page ? '<span class="tk-on">' + n + '</span>' : link(n, n)); last = n; });
      if (page < total) out.push(link(page + 1, 'Next →'));
      return out.join('');
    }
    function url(p){ return p === 1 ? cfg.base : cfg.base + 'page/' + p + '/'; }
    function render(){
      var r = rowsNow(), total = Math.max(1, Math.ceil(r.length / cfg.size));
      st.page = Math.min(Math.max(1, st.page), total);
      var start = (st.page - 1) * cfg.size, chunk = r.slice(start, start + cfg.size);
      tbody.innerHTML = chunk.map(function(x){ return '<tr' + (x.cur ? ' class="cur"' : '') + '>' + x.c.map(function(c, i){ return '<td' + (cfg.cls[i] ? ' class="' + cfg.cls[i] + '"' : '') + '>' + c + '</td>'; }).join('') + '</tr>'; }).join('');
      if (empty) empty.style.display = r.length ? 'none' : 'block';
      var def = isDefault();
      var link = function(p, label){ return def ? '<a href="' + url(p) + '">' + label + '</a>' : '<a href="#" data-p="' + p + '">' + label + '</a>'; };
      pagers.forEach(function(pg){ pg.innerHTML = pagerHtml(st.page, total, link); });
      if (info) info.textContent = (r.length ? fmt(start + 1) + '–' + fmt(start + chunk.length) : '0') + ' of ' + fmt(r.length) + (def ? '' : ' matching') + ' · page ' + st.page + ' of ' + total;
      ths.forEach(function(th){ th.classList.toggle('tk-up', st.k === +th.dataset.k && st.dir === 1); th.classList.toggle('tk-down', st.k === +th.dataset.k && st.dir === -1); });
      ord.forEach(function(b){ b.classList.toggle('on', b.dataset.order === st.order && st.k === null); });
      var P2 = new URLSearchParams();
      if (st.q) P2.set('q', st.q); for (var k in st.f) if (st.f[k]) P2.set(k, st.f[k]);
      if (st.order !== 'default') P2.set('order', st.order); if (st.k !== null) { P2.set('sort', st.k); P2.set('dir', st.dir); }
      if (!def && st.page > 1) P2.set('p', st.page);
      var qs = P2.toString(); history.replaceState(null, '', (def ? url(st.page) : cfg.base) + (qs ? '?' + qs : ''));
    }
    function go(){ load().then(render); }
    var timer; q && q.addEventListener('input', function(){ clearTimeout(timer); timer = setTimeout(function(){ st.q = q.value; st.page = 1; go(); }, 150); });
    sels.forEach(function(s){ s.addEventListener('change', function(){ st.f[s.dataset.f] = s.value; st.page = 1; go(); }); });
    ord.forEach(function(b){ b.addEventListener('click', function(){ st.order = b.dataset.order; st.k = null; st.page = 1; go(); }); });
    ths.forEach(function(th){ th.addEventListener('click', function(){ var k = +th.dataset.k; if (st.k === k) st.dir = -st.dir; else { st.k = k; st.dir = +(th.dataset.dir || -1); } st.page = 1; go(); }); });
    root.addEventListener('click', function(ev){ var a = ev.target.closest('a[data-p]'); if (!a) return; ev.preventDefault(); st.page = +a.dataset.p; go(); root.scrollIntoView({behavior:'smooth'}); });
    if (!isDefault() || P.get('p')) go();
  });
})();
