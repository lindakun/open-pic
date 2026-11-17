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
    curIdx: -1,
    collections: [],
    zoom: 1,
    panX: 0,
    panY: 0,
  };

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
      (d.tags_list || []).slice(0, 40).forEach(t => {
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
        div.innerHTML = `<span>📁 ${esc(c.name)}</span><b>${c.item_count}</b>`;
        div.onclick = () => {
          state.nav = 'collection';
          state.collectionId = c.id;
          syncNavUI();
          loadItems(true);
        };
        list.appendChild(div);
      });
    } catch (e) { console.error(e); }
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

    el.innerHTML = `
      <div class="thumb-box" style="background:${esc(bg)}">
        <div class="sel-check">${state.selected.has(it.id) ? '✓' : ''}</div>
        ${badge}
        <img loading="lazy" src="${thumbUrl}" alt="${esc(it.title)}">
      </div>
      <div class="meta">
        <div class="meta-title">${esc(it.title || it.name)}</div>
        <div class="meta-sub"><span>${esc(dim)}</span><span>${esc(it.source_platform || '')}</span></div>
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

    el.onclick = () => {
      if (state.selectMode) {
        toggleSelect(it.id, el);
      } else {
        openLightbox(idx);
      }
    };
    return el;
  }

  async function loadItems(reset = false) {
    if (state.nav === 'analytics') return;
    if (state.loading) return;
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
  }

  // 无限滚动
  new IntersectionObserver(es => {
    if (es[0].isIntersecting && state.offset < state.total && state.nav !== 'analytics') {
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
  }

  function jumpLb(d) {
    const n = state.curIdx + d;
    if (n >= 0 && n < state.items.length) openLightbox(n);
  }

  $('#lbClose').onclick = closeLightbox;
  $('#lbPrev').onclick = () => jumpLb(-1);
  $('#lbNext').onclick = () => jumpLb(1);
  $('#lbToggleDrawer').onclick = () => $('#lbDrawer').classList.toggle('collapsed');

  document.addEventListener('keydown', e => {
    if ($('#lb').hidden) return;
    if (e.target.tagName === 'INPUT') return;
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

  function toggleSelect(id, cardEl) {
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    if (cardEl) {
      cardEl.classList.toggle('selected', state.selected.has(id));
      const ck = cardEl.querySelector('.sel-check');
      if (ck) ck.textContent = state.selected.has(id) ? '✓' : '';
    }
    $('#batchCount').textContent = state.selected.size;
    $('#batchBar').hidden = state.selected.size === 0;
  }

  function exitSelectMode() {
    state.selectMode = false;
    state.selected.clear();
    document.body.classList.remove('select-mode');
    $('#batchBar').hidden = true;
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
      $('#bRestore').hidden = state.nav !== 'trash';
      $('#bPurge').hidden = state.nav !== 'trash';
      $('#bDelete').hidden = state.nav === 'trash';
      toast('已进入多选模式，点击卡片勾选');
    }
  };
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

  $('#bAddTag').onclick = () => {
    const raw = prompt('输入要批量添加的标签（逗号分隔）');
    if (raw) runBatch('add_tags', { tags: raw.split(/[,，\s]+/).filter(Boolean) });
  };
  $('#bAddCol').onclick = () => {
    if (!state.collections.length) return toast('请先在左侧新建画板');
    const list = state.collections.map(c => `${c.id}: ${c.name}`).join('\n');
    const cid = prompt(`输入目标画板 ID:\n${list}`);
    if (cid && !isNaN(+cid)) runBatch('add_collection', { collection_id: +cid });
  };
  $('#bDelete').onclick = () => runBatch('delete');
  $('#bRestore').onclick = () => runBatch('restore');
  $('#bPurge').onclick = () => { if (confirm('彻底删除后不可恢复，确定？')) runBatch('permanent_delete'); };
  $('#bZip').onclick = async () => {
    const ids = Array.from(state.selected);
    const r = await fetch('/api/items/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (r.ok) {
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'medialib-pack.zip';
      a.click();
    }
  };

  // ---------- 画板、统计看板、任务 SSE ----------

  $('#btnNewCol').onclick = () => { $('#colModal').hidden = false; $('#inColName').focus(); };
  $('#btnSubmitCol').onclick = async () => {
    const name = $('#inColName').value.trim();
    if (!name) return;
    const r = await fetch('/api/collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: $('#inColDesc').value }),
    });
    if (r.ok) {
      closeModal('colModal');
      $('#inColName').value = '';
      $('#inColDesc').value = '';
      loadCollections();
      toast('画板已创建');
    }
  };

  async function loadAnalytics() {
    const [sr, ar] = await Promise.all([fetch('/api/storage/summary'), fetch('/api/analytics')]);
    const st = await sr.json();
    const an = await ar.json();
    $('#storageBox').innerHTML = `
      <div class="kv">
        <span>原文件 (${st.files.files})</span><b>${fmtBytes(st.files.bytes)}</b>
        <span>多规格缩略图 (${st.thumbs.files})</span><b>${fmtBytes(st.thumbs.bytes)}</b>
        <span>视频动态预览 (${st.previews.files})</span><b>${fmtBytes(st.previews.bytes)}</b>
        <span>兼容播放副本 (${st.play.files})</span><b>${fmtBytes(st.play.bytes)}</b>
        <span>磁盘可用空间</span><b>${fmtBytes(st.disk_free)} / ${fmtBytes(st.disk_total)}</b>
      </div>`;

    const daily = an.daily_ingest || [];
    const maxC = Math.max(...daily.map(d => d.cnt), 1);
    $('#dailyChart').innerHTML = daily.length
      ? daily.map(d => `<div class="bar-col" style="height:${Math.max(6, Math.round(d.cnt * 100 / maxC))}%" title="${d.day}: ${d.cnt} 项"></div>`).join('')
      : '<span class="muted">暂无近 30 天入库数据</span>';

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
    $('#jobsList').innerHTML = (d.jobs || []).map(j => `
      <div class="job-item">
        <div style="display:flex;justify-content:space-between">
          <b>#${j.id} ${esc(j.job_type)}</b>
          <span>${esc(j.status)} (${j.progress}%)</span>
        </div>
        <div class="muted" style="margin-top:4px">${esc(j.message)}</div>
        <div class="job-bar"><i style="width:${j.progress}%"></i></div>
      </div>`).join('') || '<div class="muted">暂无后台任务</div>';
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
      if (state.nav !== 'analytics') loadItems(true);
    });
  } catch (e) {}

  // ---------- 导航与筛选事件绑定 ----------

  function syncNavUI() {
    $$('.nav-item').forEach(n => n.classList.toggle('on', n.dataset.nav === state.nav));
    $$('.col-item').forEach(c => c.classList.remove('on'));
    const isAna = state.nav === 'analytics';
    $('#gallery').hidden = isAna;
    $('#done').hidden = isAna;
    $('#activeBar').hidden = isAna;
    $('#analyticsView').hidden = !isAna;
    if (isAna) loadAnalytics();
  }

  $$('.nav-item').forEach(n => {
    n.onclick = () => {
      state.nav = n.dataset.nav;
      state.collectionId = null;
      exitSelectMode();
      syncNavUI();
      if (state.nav !== 'analytics') loadItems(true);
    };
  });

  function resetFilters() {
    state.q = '';
    state.tags = [];
    state.excludeTags = [];
    state.orientation = '';
    state.platform = '';
    state.color = '';
    $('#q').value = '';
    $('#btnClearQ').hidden = true;
    $('#orientFilter').value = '';
    $('#platformFilter').value = '';
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

  $('#btnSidebar').onclick = () => { $('#sidebar').classList.toggle('collapsed'); requestAnimationFrame(layoutMasonry); };
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
