(() => {
  const PER = 48;
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));

  const state = {
    items: [],
    offset: 0,
    total: 0,
    loading: false,
    nav: 'all', // all | trash | analytics | collection
    collectionId: null,
    kind: '',
    q: '',
    tags: [],
    excludeTags: [],
    orientation: '',
    platform: '',
    color: '',
    sort: 'newest',
    view: localStorage.getItem('mlib_view') || 'masonry',
    theme: localStorage.getItem('mlib_theme') || 'dark',
    selectMode: false,
    selected: new Set(),
    lastSelectedIdx: -1,
    curIdx: -1,
    collections: [],
    editingCol: null,
    popularTags: [],
    batchTagMode: 'add',
    zoom: 1,
    panX: 0,
    panY: 0,
    pipeLogType: 'x_scrape',
    defaultVisionPrompt: '',
    /** 加载中收到的重置请求：等当前请求结束后再补一次，避免筛选被吞 */
    pendingReset: false,
    /** 灯箱打开期间收到的库更新：关闭灯箱后补刷新 */
    pendingLibRefresh: false,
  };

  function isMobileViewport() {
    return window.innerWidth <= 860;
  }

  function syncSidebarBackdrop() {
    const bd = $('#sidebarBackdrop');
    if (!bd) return;
    const openOnMobile = isMobileViewport() && !$('#sidebar').classList.contains('collapsed');
    bd.hidden = !openOnMobile;
  }

  function closeMobileSidebar() {
    if (isMobileViewport()) {
      $('#sidebar').classList.add('collapsed');
      syncSidebarBackdrop();
    }
  }

  // 移动端默认收起侧边栏，避免首屏挤压主画廊
  if (isMobileViewport()) {
    $('#sidebar').classList.add('collapsed');
  }

  // 初始化主题与视图
  document.documentElement.setAttribute('data-theme', state.theme);
  $$('#viewTabs .seg-btn').forEach(b => b.classList.toggle('on', b.dataset.v === state.view));
  $('#gallery').className = `gallery ${state.view}`;

  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), 2200);
  }

  function fmtBytes(b) {
    if (!b) return '0B';
    if (b < 1024) return b + 'B';
    if (b < 1048576) return (b / 1024).toFixed(0) + 'KB';
    if (b < 1073741824) return (b / 1048576).toFixed(1) + 'MB';
    return (b / 1073741824).toFixed(2) + 'GB';
  }

  function fmtDur(sec) {
    if (!sec) return '';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function esc(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------- 统计、标签云与画板 ----------

  async function loadStats() {
    try {
      const r = await fetch('/api/stats');
      const d = await r.json();
      $('#stat').textContent = `${d.total} 项 · ${d.images} 图 · ${d.videos} 视频 · ${fmtBytes(d.bytes)}`;
      $('#cntAll').textContent = d.total;
      $('#cntTrash').textContent = d.trash_count || 0;

      // 渲染热门标签云
      const cloud = $('#tagCloud');
      cloud.innerHTML = '';
      state.popularTags = (d.tags_list || []).slice(0, 40);
      state.popularTags.forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        if (state.tags.includes(t.name)) chip.classList.add('on');
        if (state.excludeTags.includes(t.name)) chip.classList.add('ex');
        chip.textContent = `${t.name} (${t.count})`;
        chip.title = '左键交集筛选 / Alt+点击排除';
        chip.onclick = (e) => {
          if (e.altKey) {
            toggleArr(state.excludeTags, t.name);
            state.tags = state.tags.filter(x => x !== t.name);
          } else {
            toggleArr(state.tags, t.name);
            state.excludeTags = state.excludeTags.filter(x => x !== t.name);
          }
          loadStats();
          loadItems(true);
        };
        cloud.appendChild(chip);
      });

      // 来源平台下拉
      const pf = $('#platformFilter');
      const curPf = pf.value;
      pf.innerHTML = '<option value="">全部来源平台</option>';
      (d.platforms || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = `${p.name} (${p.count})`;
        pf.appendChild(opt);
      });
      pf.value = curPf;
    } catch (e) { console.error(e); }
  }

  async function loadCollections() {
    try {
      const r = await fetch('/api/collections');
      const d = await r.json();
      state.collections = d.collections || [];
      const list = $('#colList');
      list.innerHTML = '';
      state.collections.forEach(c => {
        const div = document.createElement('div');
        div.className = 'col-item' + (state.nav === 'collection' && state.collectionId === c.id ? ' on' : '');
        div.innerHTML = `<span class="col-item__name">📁 ${esc(c.name)}</span>
          <span class="col-item__meta"><b>${c.item_count}</b>
            <span class="col-item__acts">
              <button class="mini-icon" data-act="rename" title="重命名" aria-label="重命名">✎</button>
              <button class="mini-icon" data-act="del" title="删除" aria-label="删除">🗑</button>
            </span>
          </span>`;
        div.onclick = () => {
          state.nav = 'collection';
          state.collectionId = c.id;
          closeMobileSidebar();
          syncNavUI();
          loadItems(true);
        };
        div.querySelectorAll('[data-act]').forEach(btn => {
          btn.onclick = e => {
            e.stopPropagation();
            if (btn.dataset.act === 'rename') openColModal(c);
            else deleteCollection(c);
          };
        });
        list.appendChild(div);
      });
    } catch (e) { console.error(e); }
  }

  // 打开画板弹窗：传 c 为编辑，缺省为新建
  function openColModal(c = null) {
    state.editingCol = c ? c.id : null;
    $('#colModalTitle').textContent = c ? '重命名画板' : '新建画板';
    $('#btnSubmitCol').textContent = c ? '保存' : '创建';
    $('#inColName').value = c ? c.name : '';
    $('#inColDesc').value = c ? (c.description || '') : '';
    $('#colModal').hidden = false;
    $('#inColName').focus();
    $('#inColName').select();
  }

  async function deleteCollection(c) {
    if (!confirm(`删除画板「${c.name}」？画板内的素材不会被删除。`)) return;
    const r = await fetch(`/api/collections/${c.id}`, { method: 'DELETE' });
    if (!r.ok) return toast('删除失败');
    // 正在浏览被删画板时回到全部资产，避免停留在空筛选
    if (state.nav === 'collection' && state.collectionId === c.id) {
      state.nav = 'all';
      state.collectionId = null;
      syncNavUI();
      loadItems(true);
    }
    await loadCollections();
    toast('画板已删除');
  }

  function toggleArr(arr, val) {
    const i = arr.indexOf(val);
    if (i >= 0) arr.splice(i, 1);
    else arr.push(val);
  }

  // ---------- 瀑布流无抖动排版 ----------

  function layoutMasonry() {
    const gal = $('#gallery');
    if (state.view !== 'masonry') {
      gal.style.height = '';
      gal.querySelectorAll('.card').forEach(c => {
        c.style.width = '';
        c.style.left = '';
        c.style.top = '';
        const box = c.querySelector('.thumb-box');
        if (box) box.style.height = '';
      });
      return;
    }
    const w = gal.clientWidth;
    if (!w) return;
    const gap = w < 600 ? 8 : 12;
    const cols = w >= 1480 ? 5 : w >= 1120 ? 4 : w >= 780 ? 3 : 2;
    const colW = (w - gap * (cols - 1)) / cols;
    const heights = new Array(cols).fill(0);

    const cards = gal.querySelectorAll('.card');
    cards.forEach(card => {
      const idx = +card.dataset.idx;
      const it = state.items[idx];
      const ratio = it && it.width > 0 && it.height > 0 ? (it.height / it.width) : 1.0;
      const imgH = Math.max(90, Math.round(colW * Math.min(ratio, 2.4)));
      const box = card.querySelector('.thumb-box');
      if (box) box.style.height = imgH + 'px';

      let minCol = 0;
      for (let i = 1; i < cols; i++) {
        if (heights[i] < heights[minCol]) minCol = i;
      }
      card.style.width = colW + 'px';
      card.style.left = (minCol * (colW + gap)) + 'px';
      card.style.top = heights[minCol] + 'px';
      heights[minCol] += imgH + 50 + gap;
    });
    gal.style.height = Math.max(...heights, 200) + 'px';
  }

  new ResizeObserver(() => {
    if (state.view === 'masonry') requestAnimationFrame(layoutMasonry);
  }).observe($('#gallery'));

  // ---------- 列表加载与卡片渲染 ----------

  function renderActiveBar() {
    const bar = $('#activeBar');
    const chips = [];
    if (state.nav === 'trash') chips.push('🗑 回收站');
    if (state.nav === 'collection') {
      const col = state.collections.find(c => c.id === state.collectionId);
      if (col) chips.push(`📁 画板: ${col.name}`);
    }
    if (state.q) chips.push(`搜索: "${state.q}"`);
    if (state.kind) chips.push(`类型: ${state.kind === 'image' ? '图片' : '视频'}`);
    state.tags.forEach(t => chips.push(`#${t}`));
    state.excludeTags.forEach(t => chips.push(`排除 #${t}`));
    if (state.orientation) chips.push(`方向: ${state.orientation}`);
    if (state.platform) chips.push(`平台: ${state.platform}`);
    if (state.color) chips.push(`色调: ${state.color}`);

    if (!chips.length) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    bar.innerHTML = `<span>当前筛选：</span>` +
      chips.map(c => `<span class="tag-chip on">${esc(c)}</span>`).join('') +
      `<button class="mini-btn" id="btnClearBar" style="margin-left:auto">清除筛选</button>`;
    $('#btnClearBar').onclick = resetFilters;
  }

  function buildCard(it, idx) {
    const el = document.createElement('div');
    el.className = 'card' + (state.selected.has(it.id) ? ' selected' : '');
    el.dataset.idx = idx;
    el.dataset.id = it.id;

    const thumbUrl = it.thumb ? `/t/${it.id}_md.webp` : `/f/${it.file}`;
    const bg = it.dominant_color || '#1a1d24';
    const badge = it.kind === 'video'
      ? `<div class="badge">▶ ${it.duration ? fmtDur(it.duration) : '视频'}</div>`
      : '';
    const dim = it.width > 0 ? `${it.width}×${it.height}` : fmtBytes(it.size);
    const extTxt = (it.ext || '').replace(/^\./, '').toUpperCase();
    const specParts = [dim, extTxt, it.size ? fmtBytes(it.size) : '', it.source_platform && it.source_platform !== 'local' ? it.source_platform : ''].filter(Boolean);
    const tagsHtml = (it.tags || []).slice(0, 3).map(t => `<span class="card-tag">#${esc(t)}</span>`).join('');

    el.innerHTML = `
      <div class="thumb-box" style="background:${esc(bg)}">
        <div class="sel-check">${state.selected.has(it.id) ? '✓' : ''}</div>
        ${badge}
        <img loading="lazy" src="${thumbUrl}" alt="${esc(it.title)}">
      </div>
      <div class="meta">
        <div class="meta-main">
          <div class="meta-title" title="${esc(it.title || it.name)}">${esc(it.title || it.name)}</div>
          ${tagsHtml ? `<div class="card-tags">${tagsHtml}</div>` : ''}
        </div>
        <div class="meta-sub"><span>${esc(dim)}</span><span>${esc(it.source_platform === 'local' ? extTxt : (it.source_platform || extTxt))}</span></div>
      </div>`;

    const img = el.querySelector('img');
    img.onload = () => img.classList.add('loaded');
    img.onerror = () => {
      if (!img.dataset.fb) {
        img.dataset.fb = '1';
        img.src = it.thumb ? `/t/${it.id}.jpg` : `/f/${it.file}`;
      }
    };

    // 视频悬停动态预览
    if (it.kind === 'video' && it.preview_file) {
      el.addEventListener('mouseenter', () => { img.src = `/p/${it.preview_file}`; });
      el.addEventListener('mouseleave', () => { img.src = thumbUrl; });
    }

    el.onclick = (e) => {
      if (state.selectMode) {
        toggleSelect(it.id, el, e.shiftKey, idx);
      } else {
        openLightbox(idx);
      }
    };
    return el;
  }

  async function loadItems(reset = false) {
    if (state.nav === 'analytics' || state.nav === 'pipeline') return;
    // 加载中直接 return 会让快速切换筛选的请求被吞，最终列表与 UI 不一致；
    // 记录待执行的重置，当前请求结束后立即补一次。
    if (state.loading) {
      if (reset) state.pendingReset = true;
      return;
    }
    state.loading = true;
    const gal = $('#gallery');
    if (reset) {
      state.items = [];
      state.offset = 0;
      gal.innerHTML = '';
      gal.style.height = '';
    }
    renderActiveBar();
    try {
      const p = new URLSearchParams({
        limit: PER,
        offset: state.offset,
        sort: state.sort,
      });
      if (state.q) p.set('q', state.q);
      if (state.kind) p.set('kind', state.kind);
      if (state.tags.length) p.set('tag', state.tags.join(','));
      if (state.excludeTags.length) p.set('exclude_tag', state.excludeTags.join(','));
      if (state.orientation) p.set('orientation', state.orientation);
      if (state.platform) p.set('platform', state.platform);
      if (state.color) p.set('color', state.color);
      if (state.nav === 'trash') p.set('deleted', 'true');
      if (state.nav === 'collection' && state.collectionId) p.set('collection_id', state.collectionId);

      const r = await fetch('/api/items?' + p);
      const d = await r.json();
      state.total = d.total;

      const frag = document.createDocumentFragment();
      d.items.forEach(it => {
        const idx = state.items.length;
        state.items.push(it);
        frag.appendChild(buildCard(it, idx));
      });
      gal.appendChild(frag);
      state.offset += d.items.length;

      if (state.total === 0) {
        gal.innerHTML = '<div class="empty">没有找到匹配的素材</div>';
        $('#done').textContent = '';
      } else {
        $('#done').textContent = state.offset >= state.total ? `共 ${state.total} 项` : '滚动加载更多…';
      }
      requestAnimationFrame(layoutMasonry);
    } catch (e) {
      console.error(e);
      toast('加载列表失败');
    }
    state.loading = false;
    if (state.pendingReset) {
      state.pendingReset = false;
      loadItems(true);
    }
  }

  // 无限滚动
  new IntersectionObserver(es => {
    if (es[0].isIntersecting && state.offset < state.total && state.nav !== 'analytics' && state.nav !== 'pipeline') {
      loadItems(false);
    }
  }, { rootMargin: '600px' }).observe($('#done'));

  // ---------- 专业媒体灯箱 ----------

  function applyTransform() {
    const img = $('#lbMediaWrap img');
    if (img) img.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  }

  async function openLightbox(idx) {
    state.curIdx = idx;
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    const it = state.items[idx];
    if (!it) return;

    // 异步记录浏览量
    fetch(`/api/item/${it.id}?view=true`).catch(() => {});

    const wrap = $('#lbMediaWrap');
    const ctrls = $('#lbControls');
    if (it.kind === 'video') {
      const src = it.play_file ? `/f/${it.file}?play=1` : `/f/${it.file}`;
      wrap.innerHTML = `<video id="lbVideo" src="${src}" controls autoplay playsinline></video>`;
      ctrls.innerHTML = `
        <button class="btn" id="vSpeed">倍速 1x</button>
        <button class="btn" id="vLoop">循环: 关</button>
        <button class="btn" id="vPip">画中画</button>
        <a class="btn primary" href="/f/${it.file}?dl=1" download>⬇ 下载原视频</a>`;
      const vid = $('#lbVideo');
      const speeds = [1, 1.25, 1.5, 2, 0.5];
      let si = 0;
      $('#vSpeed').onclick = () => { si = (si + 1) % speeds.length; vid.playbackRate = speeds[si]; $('#vSpeed').textContent = `倍速 ${speeds[si]}x`; };
      $('#vLoop').onclick = () => { vid.loop = !vid.loop; $('#vLoop').textContent = `循环: ${vid.loop ? '开' : '关'}`; };
      $('#vPip').onclick = () => { if (vid.requestPictureInPicture) vid.requestPictureInPicture(); };
    } else {
      const previewSrc = it.thumb ? `/t/${it.id}_lg.webp` : `/f/${it.file}`;
      wrap.innerHTML = `<img src="${previewSrc}" alt="${esc(it.title)}">`;
      const img = wrap.querySelector('img');
      img.onerror = () => { img.src = `/f/${it.file}`; };
      // 鼠标滚轮缩放 & 拖拽平移
      img.onwheel = (e) => {
        e.preventDefault();
        state.zoom = Math.min(6, Math.max(0.5, state.zoom + (e.deltaY < 0 ? 0.2 : -0.2)));
        applyTransform();
      };
      img.ondblclick = () => {
        state.zoom = state.zoom > 1 ? 1 : 2;
        state.panX = 0;
        state.panY = 0;
        applyTransform();
      };
      let dragging = false, sx = 0, sy = 0;
      img.onmousedown = (e) => { dragging = true; sx = e.clientX - state.panX; sy = e.clientY - state.panY; };
      window.onmousemove = (e) => { if (!dragging) return; state.panX = e.clientX - sx; state.panY = e.clientY - sy; applyTransform(); };
      window.onmouseup = () => { dragging = false; };

      ctrls.innerHTML = `
        <button class="btn" id="zIn">放大 +</button>
        <button class="btn" id="zOut">缩小 -</button>
        <button class="btn" id="zOrig">查看原图</button>
        <a class="btn primary" href="/f/${it.file}?dl=1" download>⬇ 下载原图</a>`;
      $('#zIn').onclick = () => { state.zoom = Math.min(6, state.zoom + 0.4); applyTransform(); };
      $('#zOut').onclick = () => { state.zoom = Math.max(0.5, state.zoom - 0.4); applyTransform(); };
      $('#zOrig').onclick = () => { img.src = `/f/${it.file}`; state.zoom = 1; state.panX = 0; state.panY = 0; applyTransform(); toast('已切换原图'); };
    }

    renderDrawer(it);
    $('#lb').hidden = false;
    document.body.style.overflow = 'hidden';
  }

  async function renderDrawer(it) {
    const shareUrl = `${location.origin}/s/${it.id}`;
    const body = $('#lbDrawerBody');
    body.innerHTML = `
      <div>
        <label class="muted">标题</label>
        <input id="edTitle" class="inp" style="margin-top:4px" value="${esc(it.title)}">
      </div>
      <div>
        <label class="muted">标签（逗号分隔）</label>
        <input id="edTags" class="inp" style="margin-top:4px" value="${esc((it.tags || []).join(', '))}">
      </div>
      <div>
        <label class="muted">备注</label>
        <input id="edNotes" class="inp" style="margin-top:4px" value="${esc(it.notes || '')}" placeholder="添加备注…">
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn primary" id="btnSaveItem" style="flex:1">保存修改</button>
        <button class="btn danger" id="btnDelItem">删除</button>
      </div>
      <div class="kv">
        <span>尺寸/大小</span><b>${it.width ? `${it.width}×${it.height}` : '-'} · ${fmtBytes(it.size)}</b>
        <span>格式/编码</span><b>${esc(it.ext)} ${it.codec ? `/ ${esc(it.codec)}` : ''}</b>
        <span>来源平台</span><b>${esc(it.source_platform || 'local')}</b>
        <span>主色调</span><b><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:${esc(it.dominant_color)};vertical-align:middle"></span> ${esc(it.dominant_color)}</b>
        <span>浏览/下载</span><b>${it.views || 0} / ${it.downloads || 0}</b>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="mini-btn" id="cpShare">复制分享页</button>
        <button class="mini-btn" id="cpMd">复制 Markdown</button>
        ${it.source ? `<a class="mini-btn" href="${esc(it.source)}" target="_blank" rel="noopener">打开原来源</a>` : ''}
      </div>
      <div>
        <div class="muted">视觉相似推荐</div>
        <div class="sim-grid" id="simGrid"><span class="muted">检索中…</span></div>
      </div>`;

    $('#btnSaveItem').onclick = async () => {
      const tags = $('#edTags').value.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean);
      const r = await fetch(`/api/item/${it.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: $('#edTitle').value, tags, notes: $('#edNotes').value }),
      });
      if (r.ok) {
        const d = await r.json();
        state.items[state.curIdx] = d.item;
        toast('已保存');
        loadStats();
      }
    };

    $('#btnDelItem').onclick = async () => {
      await fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: it.id }),
      });
      closeLightbox();
      toast('已移入回收站');
      loadStats();
      loadItems(true);
    };

    $('#cpShare').onclick = () => { navigator.clipboard.writeText(shareUrl); toast('已复制分享页链接'); };
    $('#cpMd').onclick = () => { navigator.clipboard.writeText(`![${it.title}](${location.origin}/f/${it.file})`); toast('已复制 Markdown'); };

    try {
      const sr = await fetch(`/api/item/${it.id}/similar?limit=6`);
      const sd = await sr.json();
      const sg = $('#simGrid');
      if (!sd.items || !sd.items.length) {
        sg.innerHTML = '<span class="muted">暂无相似资产</span>';
      } else {
        sg.innerHTML = '';
        sd.items.forEach(sim => {
          const im = document.createElement('img');
          im.src = sim.thumb ? `/t/${sim.id}_sm.webp` : `/f/${sim.file}`;
          im.title = sim.title;
          im.onclick = () => {
            const found = state.items.findIndex(x => x.id === sim.id);
            if (found >= 0) openLightbox(found);
            else window.open(`/s/${sim.id}`, '_blank');
          };
          sg.appendChild(im);
        });
      }
    } catch (e) {}
  }

  function closeLightbox() {
    $('#lb').hidden = true;
    $('#lbMediaWrap').innerHTML = '';
    document.body.style.overflow = '';
    // 灯箱打开期间刻意不刷新列表（否则 curIdx 会指向新列表的错位项），
    // 关闭后补上积压的库更新。
    if (state.pendingLibRefresh) {
      state.pendingLibRefresh = false;
      loadStats();
      if (state.nav !== 'analytics' && state.nav !== 'pipeline') loadItems(true);
    }
  }

  function jumpLb(d) {
    const n = state.curIdx + d;
    if (n >= 0 && n < state.items.length) openLightbox(n);
  }

  $('#lbClose').onclick = closeLightbox;
  $('#lbPrev').onclick = () => jumpLb(-1);
  $('#lbNext').onclick = () => jumpLb(1);
  const syncDrawerUi = () => {
    $('#lbShowDrawer').hidden = !$('#lbDrawer').classList.contains('collapsed');
  };
  $('#lbToggleDrawer').onclick = () => { $('#lbDrawer').classList.toggle('collapsed'); syncDrawerUi(); };
  $('#lbShowDrawer').onclick = () => { $('#lbDrawer').classList.remove('collapsed'); syncDrawerUi(); };

  document.addEventListener('keydown', e => {
    if ($('#lb').hidden) return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;
    // 视频获得焦点时方向键交给原生播放器做快进/快退，否则会一边 seek 一边切换素材
    if (tag === 'VIDEO' && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') jumpLb(-1);
    if (e.key === 'ArrowRight') jumpLb(1);
  });

  // ---------- 上传、粘贴、拖拽、抓链接 ----------

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const fd = new FormData();
    for (const f of fileList) fd.append('file', f);
    toast(`正在上传 ${fileList.length} 个文件…`);
    try {
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      const d = await r.json();
      if (r.ok) {
        toast(`成功入库 ${d.count} 项`);
        loadStats();
        loadItems(true);
      } else {
        toast(d.detail || '上传失败');
      }
    } catch (e) { toast('上传请求失败'); }
  }

  $('#btnUpload').onclick = () => $('#filePicker').click();
  $('#filePicker').onchange = (e) => { uploadFiles(e.target.files); e.target.value = ''; };

  // 全屏拖拽上传
  let dragCnt = 0;
  window.addEventListener('dragenter', e => { e.preventDefault(); dragCnt++; $('#dropOverlay').hidden = false; });
  window.addEventListener('dragleave', e => { dragCnt--; if (dragCnt <= 0) { dragCnt = 0; $('#dropOverlay').hidden = true; } });
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => {
    e.preventDefault();
    dragCnt = 0;
    $('#dropOverlay').hidden = true;
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });

  // 剪贴板粘贴图片上传
  window.addEventListener('paste', e => {
    if (e.target.tagName === 'INPUT') return;
    const files = Array.from(e.clipboardData.items || [])
      .filter(i => i.kind === 'file')
      .map(i => i.getAsFile())
      .filter(Boolean);
    if (files.length) uploadFiles(files);
  });

  // URL 投递
  window.closeModal = (id) => { $('#' + id).hidden = true; };
  $('#btnIngestUrl').onclick = () => { $('#urlModal').hidden = false; $('#inUrl').focus(); };
  $('#btnSubmitUrl').onclick = async () => {
    const url = $('#inUrl').value.trim();
    if (!url) return toast('请输入链接');
    const r = await fetch('/api/ingest-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, tags: $('#inUrlTags').value, title: $('#inUrlTitle').value }),
    });
    if (r.ok) {
      closeModal('urlModal');
      $('#inUrl').value = '';
      toast('已加入后台抓取队列');
      $('#jobDot').hidden = false;
      loadJobs();
    } else {
      const d = await r.json();
      toast(d.detail || '提交失败');
    }
  };

  // ---------- 批量多选 ----------

  function syncBatchBarVisibility(show) {
    $('#batchBar').hidden = !show;
    document.body.classList.toggle('has-batch-bar', Boolean(show));
  }

  function syncCardSelectionDOM() {
    $$('#gallery .card').forEach(c => {
      const on = state.selected.has(c.dataset.id);
      c.classList.toggle('selected', on);
      const ck = c.querySelector('.sel-check');
      if (ck) ck.textContent = on ? '✓' : '';
    });
    $('#batchCount').textContent = state.selected.size;
    const allSel = state.items.length > 0 && state.selected.size >= state.items.length;
    if ($('#bSelectAll')) {
      $('#bSelectAll').textContent = allSel ? '取消全选' : `全选 (${state.items.length})`;
    }
    syncBatchBarVisibility(state.selected.size > 0);
  }

  function toggleSelect(id, cardEl, shiftKey = false, idx = -1) {
    if (shiftKey && state.lastSelectedIdx >= 0 && idx >= 0 && state.lastSelectedIdx !== idx) {
      const lo = Math.min(state.lastSelectedIdx, idx);
      const hi = Math.max(state.lastSelectedIdx, idx);
      const targetOn = !state.selected.has(id);
      for (let k = lo; k <= hi; k++) {
        const item = state.items[k];
        if (!item) continue;
        if (targetOn) state.selected.add(item.id);
        else state.selected.delete(item.id);
      }
      state.lastSelectedIdx = idx;
      syncCardSelectionDOM();
      return;
    }
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    state.lastSelectedIdx = idx;
    syncCardSelectionDOM();
  }

  function exitSelectMode() {
    state.selectMode = false;
    state.selected.clear();
    state.lastSelectedIdx = -1;
    document.body.classList.remove('select-mode');
    $('#btnSelectMode').classList.remove('primary');
    syncBatchBarVisibility(false);
    $$('.card.selected').forEach(c => {
      c.classList.remove('selected');
      const ck = c.querySelector('.sel-check');
      if (ck) ck.textContent = '';
    });
  }

  $('#btnSelectMode').onclick = () => {
    if (state.selectMode) exitSelectMode();
    else {
      state.selectMode = true;
      document.body.classList.add('select-mode');
      $('#btnSelectMode').classList.add('primary');
      $('#bRestore').hidden = state.nav !== 'trash';
      $('#bPurge').hidden = state.nav !== 'trash';
      $('#bDelete').hidden = state.nav === 'trash';
      closeMobileSidebar();
      toast('多选已开启：点击勾选，按住 Shift 可区间连选');
    }
  };
  if ($('#bSelectAll')) {
    $('#bSelectAll').onclick = () => {
      const allSel = state.items.length > 0 && state.selected.size >= state.items.length;
      if (allSel) state.selected.clear();
      else state.items.forEach(it => state.selected.add(it.id));
      syncCardSelectionDOM();
    };
  }
  $('#bCancel').onclick = exitSelectMode;

  async function runBatch(action, extra = {}) {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    const r = await fetch('/api/items/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, action, ...extra }),
    });
    if (r.ok) {
      toast('批量操作完成');
      exitSelectMode();
      loadStats();
      loadCollections();
      loadItems(true);
    }
  }

  function openBatchTagModal(mode) {
    state.batchTagMode = mode;
    $('#batchTagTitle').textContent = mode === 'remove' ? '批量移除标签' : '批量打标签';
    $('#batchTagHint').textContent = mode === 'remove'
      ? `将从已选的 ${state.selected.size} 项中移除匹配的标签`
      : `将追加到已选的 ${state.selected.size} 项，不会覆盖原有标签`;
    const btn = $('#btnSubmitBatchTag');
    btn.textContent = mode === 'remove' ? '确认移除' : '确定';
    btn.className = mode === 'remove' ? 'btn danger' : 'btn primary';
    const inp = $('#inBatchTags');
    inp.value = '';
    const picks = $('#batchTagPicks');
    picks.innerHTML = '';
    let tagCandidates = state.popularTags.slice(0, 12).map(x => x.name);
    if (mode === 'remove') {
      const selTags = new Set();
      state.items.forEach(it => {
        if (state.selected.has(it.id)) (it.tags || []).forEach(t => selTags.add(t));
      });
      if (selTags.size) tagCandidates = Array.from(selTags).slice(0, 16);
    }
    tagCandidates.forEach(name => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip';
      chip.textContent = name;
      chip.onclick = () => {
        const cur = inp.value.split(/[,，\s]+/).filter(Boolean);
        const i = cur.indexOf(name);
        if (i >= 0) cur.splice(i, 1);
        else cur.push(name);
        inp.value = cur.join(' ');
        chip.classList.toggle('on', i < 0 && mode !== 'remove');
        chip.classList.toggle('ex', i < 0 && mode === 'remove');
      };
      picks.appendChild(chip);
    });
    $('#batchTagModal').hidden = false;
    inp.focus();
  }

  $('#bAddTag').onclick = () => openBatchTagModal('add');
  $('#bRemTag').onclick = () => openBatchTagModal('remove');
  $('#btnSubmitBatchTag').onclick = () => {
    const tags = $('#inBatchTags').value.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
    if (!tags.length) return toast('请输入或点选标签');
    closeModal('batchTagModal');
    runBatch(state.batchTagMode === 'remove' ? 'remove_tags' : 'add_tags', { tags });
  };
  $('#inBatchTags').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); $('#btnSubmitBatchTag').click(); }
  });

  $('#bAddCol').onclick = () => {
    if (!state.collections.length) return toast('请先在左侧新建画板');
    const sel = $('#inBatchCol');
    sel.innerHTML = state.collections.map(c => `<option value="${c.id}">${esc(c.name)} (${c.item_count})</option>`).join('');
    $('#batchColModal').hidden = false;
    sel.focus();
  };
  $('#btnSubmitBatchCol').onclick = () => {
    const cid = +$('#inBatchCol').value;
    if (!cid) return;
    closeModal('batchColModal');
    runBatch('add_collection', { collection_id: cid });
  };
  $('#bDelete').onclick = () => runBatch('delete');
  $('#bRestore').onclick = () => runBatch('restore');
  $('#bPurge').onclick = () => { if (confirm('彻底删除后不可恢复，确定？')) runBatch('permanent_delete'); };
  $('#bZip').onclick = async () => {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    const r = await fetch('/api/items/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (r.status === 202) {
      // 大批量导出返回 JSON（job_id），不能当 ZIP 下载
      let d = {};
      try { d = await r.json(); } catch (err) { /* 保留默认提示 */ }
      toast(`导出任务 #${d.job_id || '-'} 已提交（${d.count || ids.length} 项），完成后在任务中心下载`);
      $('#jobsDrawer').hidden = false;
      loadJobs();
      return;
    }
    if (!r.ok) {
      let msg = '导出失败';
      try { const d = await r.json(); msg = d.detail || msg; } catch (err) { /* 保留默认提示 */ }
      toast(msg);
      return;
    }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'medialib-pack.zip';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  };

  // ---------- 画板、统计看板、任务 SSE ----------

  $('#btnNewCol').onclick = () => openColModal();
  $('#btnSubmitCol').onclick = async () => {
    const name = $('#inColName').value.trim();
    if (!name) return;
    const editing = state.editingCol;
    const r = await fetch(editing ? `/api/collections/${editing}` : '/api/collections', {
      method: editing ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: $('#inColDesc').value }),
    });
    if (!r.ok) return toast(editing ? '保存失败' : '创建失败');
    closeModal('colModal');
    state.editingCol = null;
    $('#inColName').value = '';
    $('#inColDesc').value = '';
    await loadCollections();
    // 重命名的是当前筛选的画板时，同步刷新顶部筛选条
    if (editing && state.nav === 'collection' && state.collectionId === editing) renderActiveBar();
    toast(editing ? '画板已更新' : '画板已创建');
  };

  async function loadAnalytics() {
    const [sr, ar] = await Promise.all([fetch('/api/storage/summary'), fetch('/api/analytics')]);
    const st = await sr.json();
    const an = await ar.json();
    const rows = [
      { label: '原文件', files: st.files.files, bytes: st.files.bytes },
      { label: '多规格缩略图', files: st.thumbs.files, bytes: st.thumbs.bytes },
      { label: '视频动态预览', files: st.previews.files, bytes: st.previews.bytes },
      { label: '兼容播放副本', files: st.play.files, bytes: st.play.bytes },
    ];
    if (st.imgcache && st.imgcache.files > 0) {
      rows.push({ label: '按需变换缓存', files: st.imgcache.files, bytes: st.imgcache.bytes });
    }
    const mediaTotal = Math.max(rows.reduce((s, r) => s + (r.bytes || 0), 0), 1);
    const diskUsed = Math.max(0, (st.disk_total || 0) - (st.disk_free || 0));
    const diskPct = st.disk_total > 0 ? Math.min(100, Math.round(diskUsed * 100 / st.disk_total)) : 0;

    $('#storageBox').innerHTML = `
      <div class="storage-list">
        ${rows.map(r => {
          const pct = r.bytes > 0 ? Math.max(2, Math.round(r.bytes * 100 / mediaTotal)) : 0;
          return `<div class="storage-row">
            <div class="storage-head"><span>${esc(r.label)} (${r.files})</span><b>${fmtBytes(r.bytes)}</b></div>
            <div class="storage-track"><div class="storage-fill" style="width:${pct}%"></div></div>
          </div>`;
        }).join('')}
        <div class="storage-row storage-disk">
          <div class="storage-head"><span>磁盘空间（可用 ${fmtBytes(st.disk_free)}）</span><b>${diskPct}% · ${fmtBytes(diskUsed)} / ${fmtBytes(st.disk_total)}</b></div>
          <div class="storage-track"><div class="storage-fill ok" style="width:${diskPct}%"></div></div>
        </div>
      </div>`;

    const daily = an.daily_ingest || [];
    const maxC = Math.max(...daily.map(d => d.cnt), 1);
    const sumC = daily.reduce((s, d) => s + (d.cnt || 0), 0);
    const dailyHead = $('#dailyChart').previousElementSibling;
    if (dailyHead && dailyHead.tagName === 'H3') {
      dailyHead.innerHTML = `<span>近 30 天入库趋势</span><small>合计 ${sumC} 项 · 峰值 ${daily.length ? maxC : 0}/天</small>`;
    }
    const axis = daily.length > 1
      ? `<div class="chart-axis"><span>${esc(daily[0].day)}</span><span>${esc(daily[daily.length - 1].day)}</span></div>`
      : '';
    $('#dailyChart').innerHTML = daily.length
      ? daily.map(d => `<div class="bar-col" style="height:${Math.max(6, Math.round(d.cnt * 100 / maxC))}%" title="${esc(d.day)}: ${d.cnt} 项"></div>`).join('')
      : '<span class="muted">暂无近 30 天入库数据</span>';
    const oldAxis = $('#dailyChart').parentElement.querySelector('.chart-axis');
    if (oldAxis) oldAxis.remove();
    if (axis) $('#dailyChart').insertAdjacentHTML('afterend', axis);

    $('#topViewed').innerHTML = (an.top_viewed || []).map(it => `
      <div class="top-item" onclick="window.open('/s/${it.id}','_blank')">
        <img src="${it.thumb ? `/t/${it.id}_sm.webp` : `/f/${it.file}`}">
        <div style="min-width:0">
          <div class="meta-title">${esc(it.title)}</div>
          <div class="muted">👁 ${it.views} · ⬇ ${it.downloads}</div>
        </div>
      </div>`).join('') || '<span class="muted">暂无浏览记录</span>';
  }

  $('#btnBackfill').onclick = async () => {
    await fetch('/api/jobs/backfill', { method: 'POST' });
    toast('已启动元数据回填任务');
    $('#jobsDrawer').hidden = false;
    loadJobs();
  };
  $('#btnRepair').onclick = async () => {
    const r = await fetch('/api/storage/repair', { method: 'POST' });
    const d = await r.json();
    toast(`修复完成：清理孤儿 ${d.orphans_removed}，补缩略图 ${d.fixed_thumbs}`);
    loadAnalytics();
  };

  async function loadJobs() {
    const r = await fetch('/api/jobs?limit=25');
    const d = await r.json();
    $('#jobsList').innerHTML = (d.jobs || []).map(j => {
      const file = j.result && j.result.file;
      const dl = j.status === 'done' && file
        ? `<a class="mini-btn" href="/api/exports/${encodeURIComponent(file)}" style="margin-top:6px;display:inline-block">⬇ 下载导出包</a>`
        : '';
      return `
      <div class="job-item">
        <div style="display:flex;justify-content:space-between">
          <b>#${j.id} ${esc(j.job_type)}</b>
          <span>${esc(j.status)} (${j.progress}%)</span>
        </div>
        <div class="muted" style="margin-top:4px">${esc(j.message)}</div>
        <div class="job-bar"><i style="width:${j.progress}%"></i></div>
        ${dl}
      </div>`;
    }).join('') || '<div class="muted">暂无后台任务</div>';
  }

  $('#btnJobs').onclick = () => { $('#jobsDrawer').hidden = !$('#jobsDrawer').hidden; $('#jobDot').hidden = true; loadJobs(); };
  $('#btnCloseJobs').onclick = () => { $('#jobsDrawer').hidden = true; };

  // SSE 实时任务通知
  try {
    const es = new EventSource('/api/jobs/stream');
    es.addEventListener('job', () => {
      $('#jobDot').hidden = false;
      if (!$('#jobsDrawer').hidden) loadJobs();
    });
    es.addEventListener('library_updated', () => {
      loadStats();
      if (state.nav !== 'analytics' && state.nav !== 'pipeline') {
        if (!$('#lb').hidden) {
          // 灯箱内素材可能已被移动/删除，立即重排会让 curIdx 错位；
          // 先记下待刷新，关闭灯箱后再执行。
          state.pendingLibRefresh = true;
          return;
        }
        loadItems(true);
      }
    });
  } catch (e) {}

  // ---------- 采集与后处理运维中心 ----------

  function applyPipelineConfigToForm(d) {
    const s = d.scrape || {};
    const p = d.postprocess || {};
    const v = d.vision || {};
    state.defaultVisionPrompt = (d.defaults && d.defaults.vision_prompt) || v.prompt || '';

    $('#cfgScrapeBatch').value = s.batch ?? 14;
    $('#cfgScrapeLimit').value = s.limit ?? 4;
    $('#cfgScrapeMaxMb').value = s.max_mb ?? 30;
    $('#cfgScrapeTags').value = (s.tags || ['X抓取', '人物']).join(', ');
    $('#cfgScrapeMinPx').value = s.min_px ?? 320;
    $('#cfgScrapeMinKb').value = s.min_img_kb ?? 20;
    $('#cfgScrapeTimeout').value = s.timeout ?? 30;
    $('#cfgScrapeProxy').value = s.proxy ?? '';

    $('#cfgPpBatch').value = p.batch ?? 50;
    $('#cfgPpPhashLimit').value = p.phash_limit ?? 50;
    $('#cfgPpMaxDist').value = p.max_dist ?? 4;
    $('#cfgPpAiTag').value = p.ai_tag || 'AI已标注';
    $('#cfgPpEnableDedup').checked = !p.skip_dedup;
    $('#cfgPpEnableVision').checked = !p.skip_vision;

    $('#cfgVisionEnabled').checked = v.enabled !== false;
    $('#cfgVisionBaseUrl').value = v.base_url || '';
    $('#cfgVisionModel').value = v.model || '';
    $('#cfgVisionTimeout').value = v.timeout ?? 45;
    $('#cfgVisionApiKey').value = '';
    $('#cfgVisionClearKey').checked = false;
    $('#cfgVisionApiKey').placeholder = v.has_api_key
      ? `已配置 (${v.api_key_masked})，留空保持不变`
      : '未配置密钥，请输入 sk-...';
    $('#cfgVisionKeyStatus').textContent = v.has_api_key
      ? `（当前已保存：${v.api_key_masked}）`
      : '（当前未配置 API Key）';
    $('#cfgVisionPrompt').value = v.prompt || '';

    $('#cfgAccountsText').value = d.accounts_text || '';
    $('#cfgAccountsCount').textContent = `${d.accounts_count || 0} 个有效账号`;
    if (d.updated_at > 0) {
      const dt = new Date(d.updated_at * 1000);
      $('#pipeUpdatedAt').textContent = `上次保存：${dt.toLocaleString()}`;
    } else {
      $('#pipeUpdatedAt').textContent = '当前使用默认配置';
    }
  }

  async function loadPipelineConfig() {
    try {
      const r = await fetch('/api/pipeline/config');
      if (!r.ok) return toast('加载配置失败');
      const d = await r.json();
      applyPipelineConfigToForm(d);
    } catch (e) {
      console.error(e);
      toast('加载配置失败');
    }
  }

  async function savePipelineConfig() {
    const tags = $('#cfgScrapeTags').value
      .split(/[,，\s]+/)
      .map(s => s.trim())
      .filter(Boolean);
    const payload = {
      scrape: {
        batch: +$('#cfgScrapeBatch').value,
        limit: +$('#cfgScrapeLimit').value,
        max_mb: +$('#cfgScrapeMaxMb').value,
        tags,
        min_px: +$('#cfgScrapeMinPx').value,
        min_img_kb: +$('#cfgScrapeMinKb').value,
        timeout: +$('#cfgScrapeTimeout').value,
        proxy: $('#cfgScrapeProxy').value.trim(),
      },
      postprocess: {
        batch: +$('#cfgPpBatch').value,
        phash_limit: +$('#cfgPpPhashLimit').value,
        max_dist: +$('#cfgPpMaxDist').value,
        ai_tag: $('#cfgPpAiTag').value.trim(),
        skip_dedup: !$('#cfgPpEnableDedup').checked,
        skip_vision: !$('#cfgPpEnableVision').checked,
      },
      vision: {
        enabled: $('#cfgVisionEnabled').checked,
        base_url: $('#cfgVisionBaseUrl').value.trim(),
        model: $('#cfgVisionModel').value.trim(),
        timeout: +$('#cfgVisionTimeout').value,
        api_key: $('#cfgVisionApiKey').value.trim(),
        clear_api_key: $('#cfgVisionClearKey').checked,
        prompt: $('#cfgVisionPrompt').value.trim(),
      },
      accounts_text: $('#cfgAccountsText').value,
    };

    try {
      const r = await fetch('/api/pipeline/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) {
        toast(d.detail || '保存配置失败');
        return;
      }
      applyPipelineConfigToForm(d);
      toast('配置已保存并生效');
      loadPipelineStatus();
    } catch (e) {
      toast('保存请求异常');
    }
  }

  async function loadPipelineStatus(preserveCustomLog = false) {
    try {
      const r = await fetch(`/api/pipeline/status?log_type=${encodeURIComponent(state.pipeLogType)}&lines=160`);
      if (!r.ok) return;
      const d = await r.json();
      const s = d.scrape || {};
      const p = d.postprocess || {};

      const sb = $('#stScrapeBadge');
      sb.textContent = s.running ? '运行中' : '空闲';
      sb.classList.toggle('running', Boolean(s.running));
      const lastStr = s.last_run_ts
        ? ` · 最近运行 ${new Date(s.last_run_ts * 1000).toLocaleTimeString()}`
        : '';
      $('#stScrapeMetrics').textContent =
        `轮转游标：${s.cursor || 0} / ${s.accounts_count || 0} · 下一顺位：${s.next_account ? '@' + s.next_account : '-'}${lastStr}`;

      const pb = $('#stPpBadge');
      pb.textContent = p.running ? '运行中' : '空闲';
      pb.classList.toggle('running', Boolean(p.running));
      $('#stPpMetrics').textContent =
        `待回填指纹：${p.missing_phash_count || 0} 项 · 待视觉标注：${p.untagged_vision_count || 0} 项`;

      const anyRunning = Boolean(s.running || p.running);
      if ($('#badgePipeline')) $('#badgePipeline').hidden = !anyRunning;

      if (!preserveCustomLog && d.log) {
        const box = $('#pipeLogBox');
        box.textContent = d.log.content || `（${d.log.path} 暂无日志内容）`;
        box.scrollTop = box.scrollHeight;
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function runPipelineAction(action, extra = {}) {
    try {
      const r = await fetch('/api/pipeline/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...extra }),
      });
      const d = await r.json();
      if (!r.ok) {
        toast(d.detail || '操作失败');
        return null;
      }
      return d;
    } catch (e) {
      toast('请求执行失败');
      return null;
    }
  }

  if ($('#btnPipeSave')) $('#btnPipeSave').onclick = savePipelineConfig;
  if ($('#btnPipeReload')) {
    $('#btnPipeReload').onclick = () => {
      loadPipelineConfig();
      loadPipelineStatus();
      toast('已重新加载配置');
    };
  }
  if ($('#btnResetPrompt')) {
    $('#btnResetPrompt').onclick = () => {
      if (state.defaultVisionPrompt) {
        $('#cfgVisionPrompt').value = state.defaultVisionPrompt;
        toast('已恢复默认视觉 Prompt（请点击保存生效）');
      }
    };
  }
  if ($('#cfgAccountsText')) {
    $('#cfgAccountsText').addEventListener('input', () => {
      const seen = new Set();
      $('#cfgAccountsText').value.split('\n').forEach(line => {
        const s = line.trim();
        if (!s || s.startsWith('#')) return;
        const a = s.replace(/^@+/, '').toLowerCase();
        if (a) seen.add(a);
      });
      $('#cfgAccountsCount').textContent = `${seen.size} 个有效账号`;
    });
  }
  if ($('#btnTestProxy')) {
    $('#btnTestProxy').onclick = async () => {
      const btn = $('#btnTestProxy');
      const resEl = $('#proxyTestResult');
      btn.disabled = true;
      resEl.textContent = '正在测试连接 https://x.com/robots.txt …';
      const d = await runPipelineAction('test_proxy', { proxy: $('#cfgScrapeProxy').value.trim() });
      btn.disabled = false;
      if (!d) {
        resEl.textContent = '测试请求失败';
        return;
      }
      if (d.ok) {
        resEl.textContent = `✓ 连通正常（HTTP ${d.status}，耗时 ${d.elapsed_ms} ms）`;
        toast(`代理可用 (${d.elapsed_ms}ms)`);
      } else {
        resEl.textContent = `✗ 连接失败：${d.error || ('HTTP ' + d.status)} (${d.elapsed_ms} ms)`;
        toast('代理连接失败');
      }
    };
  }
  if ($('#btnResetCursor')) {
    $('#btnResetCursor').onclick = async () => {
      const d = await runPipelineAction('reset_cursor');
      if (d) {
        toast(d.message || '游标已重置为 0');
        loadPipelineStatus();
      }
    };
  }
  if ($('#btnRunScrape')) {
    $('#btnRunScrape').onclick = async () => {
      const d = await runPipelineAction('run_scrape');
      if (d) {
        toast(d.message || '已投递后台抓取');
        setTimeout(() => loadPipelineStatus(), 400);
      }
    };
  }
  if ($('#btnRunPp')) {
    $('#btnRunPp').onclick = async () => {
      const d = await runPipelineAction('run_postprocess');
      if (d) {
        toast(d.message || '已投递后台后处理');
        setTimeout(() => loadPipelineStatus(), 400);
      }
    };
  }
  if ($('#btnDryScrape')) {
    $('#btnDryScrape').onclick = async () => {
      const btn = $('#btnDryScrape');
      btn.disabled = true;
      btn.textContent = '试运行中…';
      $('#pipeLogBox').textContent = '正在执行抓取试运行 (--dry-run --batch 2 --limit 2)…';
      const d = await runPipelineAction('dry_run_scrape');
      btn.disabled = false;
      btn.textContent = '🔍 试运行';
      if (d) {
        $('#pipeLogBox').textContent = `[抓取试运行输出 rc=${d.returncode}]\n` + (d.output || '');
        toast(d.message || '试运行完成');
      }
    };
  }
  if ($('#btnDryPp')) {
    $('#btnDryPp').onclick = async () => {
      const btn = $('#btnDryPp');
      btn.disabled = true;
      btn.textContent = '试运行中…';
      $('#pipeLogBox').textContent = '正在执行存量后处理试运行 (--dry-run)…';
      const d = await runPipelineAction('dry_run_postprocess');
      btn.disabled = false;
      btn.textContent = '🔍 试运行';
      if (d) {
        $('#pipeLogBox').textContent = `[后处理试运行输出 rc=${d.returncode}]\n` + (d.output || '');
        toast(d.message || '试运行完成');
      }
    };
  }
  $$('#pipeLogTabs .seg-btn').forEach(b => {
    b.onclick = () => {
      $$('#pipeLogTabs .seg-btn').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      state.pipeLogType = b.dataset.log;
      loadPipelineStatus();
    };
  });
  if ($('#btnRefreshLog')) {
    $('#btnRefreshLog').onclick = () => loadPipelineStatus();
  }
  setInterval(() => {
    if (state.nav === 'pipeline') loadPipelineStatus(true);
  }, 6000);

  // ---------- 导航与筛选事件绑定 ----------

  function syncNavUI() {
    $$('.nav-item').forEach(n => n.classList.toggle('on', n.dataset.nav === state.nav));
    $$('.col-item').forEach((c, idx) => {
      const col = state.collections[idx];
      c.classList.toggle('on', state.nav === 'collection' && col && col.id === state.collectionId);
    });
    const isAna = state.nav === 'analytics';
    const isPipe = state.nav === 'pipeline';
    const hideGal = isAna || isPipe;
    $$('[data-gallery-only]').forEach(el => { el.hidden = hideGal; });
    $('#gallery').hidden = hideGal;
    $('#done').hidden = hideGal;
    if (hideGal) $('#activeBar').hidden = true;
    $('#analyticsView').hidden = !isAna;
    if ($('#pipelineView')) $('#pipelineView').hidden = !isPipe;
    if (isAna) loadAnalytics();
    if (isPipe) {
      loadPipelineConfig();
      loadPipelineStatus();
    }
  }

  $$('.nav-item').forEach(n => {
    n.onclick = () => {
      state.nav = n.dataset.nav;
      state.collectionId = null;
      exitSelectMode();
      closeMobileSidebar();
      syncNavUI();
      if (state.nav !== 'analytics' && state.nav !== 'pipeline') loadItems(true);
    };
  });

  function resetFilters() {
    state.q = '';
    state.kind = '';
    state.tags = [];
    state.excludeTags = [];
    state.orientation = '';
    state.platform = '';
    state.color = '';
    if (state.nav === 'collection' || state.nav === 'trash') {
      state.nav = 'all';
      state.collectionId = null;
      syncNavUI();
    }
    $('#q').value = '';
    $('#btnClearQ').hidden = true;
    $('#orientFilter').value = '';
    $('#platformFilter').value = '';
    $$('#kindTabs .seg-btn').forEach(b => b.classList.toggle('on', b.dataset.k === ''));
    $$('.swatch').forEach(s => s.classList.remove('on'));
    loadStats();
    loadItems(true);
  }
  $('#btnResetFilters').onclick = resetFilters;

  let qTimer = null;
  $('#q').addEventListener('input', e => {
    state.q = e.target.value.trim();
    $('#btnClearQ').hidden = !state.q;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => loadItems(true), 280);
  });
  $('#btnClearQ').onclick = () => { $('#q').value = ''; state.q = ''; $('#btnClearQ').hidden = true; loadItems(true); };

  $$('#kindTabs .seg-btn').forEach(b => {
    b.onclick = () => {
      $$('#kindTabs .seg-btn').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      state.kind = b.dataset.k;
      loadItems(true);
    };
  });

  $('#sortSelect').onchange = e => { state.sort = e.target.value; loadItems(true); };

  $$('#viewTabs .seg-btn').forEach(b => {
    b.onclick = () => {
      $$('#viewTabs .seg-btn').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      state.view = b.dataset.v;
      localStorage.setItem('mlib_view', state.view);
      $('#gallery').className = `gallery ${state.view}`;
      requestAnimationFrame(layoutMasonry);
    };
  });

  $('#orientFilter').onchange = e => { state.orientation = e.target.value; loadItems(true); };
  $('#platformFilter').onchange = e => { state.platform = e.target.value; loadItems(true); };
  $$('.swatch').forEach(s => {
    s.onclick = () => {
      const c = s.dataset.c;
      const same = state.color === c;
      $$('.swatch').forEach(x => x.classList.remove('on'));
      state.color = same ? '' : c;
      if (!same) s.classList.add('on');
      loadItems(true);
    };
  });

  $('#btnSidebar').onclick = () => {
    $('#sidebar').classList.toggle('collapsed');
    syncSidebarBackdrop();
    requestAnimationFrame(layoutMasonry);
  };
  if ($('#sidebarBackdrop')) {
    $('#sidebarBackdrop').onclick = () => {
      $('#sidebar').classList.add('collapsed');
      syncSidebarBackdrop();
    };
  }
  window.addEventListener('resize', syncSidebarBackdrop, { passive: true });

  // 所有弹窗与任务抽屉统一支持点击遮罩或按 Esc 关闭
  $$('.modal').forEach(m => {
    m.addEventListener('click', e => {
      if (e.target === m) m.hidden = true;
    });
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const openModal = $$('.modal').find(m => !m.hidden);
    if (openModal) {
      openModal.hidden = true;
      return;
    }
    if (!$('#jobsDrawer').hidden) {
      $('#jobsDrawer').hidden = true;
      return;
    }
    if (state.selectMode && $('#lb').hidden) {
      exitSelectMode();
    }
  });

  $('#btnTheme').onclick = () => {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('mlib_theme', state.theme);
    document.documentElement.setAttribute('data-theme', state.theme);
  };

  // 初始化加载
  loadStats();
  loadCollections();
  loadItems(true);
})();
