/* Файлы телефона: папки, скачать, загрузить, удалить. Окно открывается из
   пульта. Всё идёт через /api/devices/{serial}/fs — сервер пускает только в
   общую память телефона. */

const FILES = {serial: '', path: '', places: [], items: [], sel: new Set(), shown: 0, root: '/sdcard', busy: false};
const FILES_PAGE = 200;
const FILES_PLACE_ICON = {camera: 'camera', screenshots: 'image', downloads: 'download',
    pictures: 'image', movies: 'video'};
function filesPlaceName(id) {
    return {camera: t('files.m_camera'), screenshots: t('files.m_screenshots'), downloads: t('files.m_downloads'),
        pictures: t('files.m_pictures'), movies: t('files.m_movies')}[id] || id;
}
const FILES_IMG = /\.(jpe?g|png|webp|gif|bmp)$/i;

function filesUrl(tail, query) {
    return `/api/devices/${FILES.serial}/fs${tail}` + (query ? '?' + query : '');
}

function filesSize(n) {
    if (n < 1024) return n + ' Б';
    if (n < 1048576) return Math.round(n / 1024) + ' КБ';
    if (n < 1073741824) return (n / 1048576).toFixed(1).replace('.0', '') + ' МБ';
    return (n / 1073741824).toFixed(1) + ' ГБ';
}

function filesOpen() {
    const device = S.devices.find(d => d.serial === S.active);
    if (!device || !device.online) return toast(t('pult.ne_v_seti'), 'bad');
    const keep = FILES.serial === device.serial ? FILES.path : '';
    FILES.serial = device.serial;
    FILES.path = keep;
    FILES.sel.clear();
    $('mTitle').textContent = t('files.razdel');
    modalSheet('wide', 'files-sheet');
    $('mBody').innerHTML = '<div class="files" id="files"></div>';
    $('mActs').innerHTML = `
      <button class="sm" onclick="filesMkdir()"><svg class="ic"><use href="#i-plus"/></svg>${esc(t('files.novaya_papka'))}</button>
      <label class="sm btn-like"><svg class="ic"><use href="#i-upload"/></svg>${esc(t('files.zagruzit'))}
        <input type="file" multiple hidden onchange="filesUpload(this.files);this.value=''"></label>
      <span class="sp"></span>
      <button class="sm danger" id="filesDel" onclick="filesDelete(this)"><svg class="ic"><use href="#i-trash"/></svg><span></span></button>
      <button class="primary" id="filesGet" onclick="filesDownload()"><svg class="ic"><use href="#i-download"/></svg><span></span></button>`;
    openModal();
    filesDrop($('mBody'));
    filesGo(keep);
    api(filesUrl('/places')).then(r => {
        FILES.places = r.places;
        FILES.root = r.root;
        if (!FILES.path) filesGo(r.places.find(p => p.id === 'camera')?.path || r.root);
        else filesRender();
    }).catch(() => { FILES.places = []; filesRender(); });
}

async function filesGo(path) {
    if (!path) path = FILES.root;
    FILES.busy = true;
    FILES.sel.clear();
    try {
        const r = await api(filesUrl('', 'path=' + encodeURIComponent(path)));
        FILES.path = r.path;
        FILES.parent = r.parent;
        FILES.items = r.items;
        FILES.total = r.total;
        FILES.error = '';
        FILES.shown = FILES_PAGE;
    } catch (e) {
        FILES.path = path;
        FILES.parent = path === FILES.root ? null : path.replace(/\/[^/]*$/, '') || FILES.root;
        FILES.items = [];
        FILES.error = e.message;
    }
    FILES.busy = false;
    filesRender();
}

function filesCrumbs() {
    const rel = FILES.path.slice(FILES.root.length).split('/').filter(Boolean);
    let acc = FILES.root;
    const parts = [`<button class="sm ghost" onclick="filesGo()">${esc(t('files.m_root'))}</button>`];
    rel.forEach((name, i) => {
        acc += '/' + name;
        parts.push(`<span class="files-sep">/</span><button class="sm ghost" data-p="${esc(acc)}"
            onclick="filesGo(this.dataset.p)" ${i === rel.length - 1 ? 'aria-current="true"' : ''}>${esc(name)}</button>`);
    });
    return parts.join('');
}

function filesRender() {
    const box = $('files');
    if (!box) return;
    const places = FILES.places.map(p => `<button class="files-place${FILES.path === p.path ? ' on' : ''}"
        data-p="${esc(p.path)}" onclick="filesGo(this.dataset.p)">
        <svg class="ic"><use href="#i-${FILES_PLACE_ICON[p.id] || 'image'}"/></svg>${esc(filesPlaceName(p.id))}</button>`).join('');
    const root = `<button class="files-place${FILES.path === FILES.root ? ' on' : ''}" onclick="filesGo()">
        <svg class="ic"><use href="#i-phone"/></svg>${esc(t('files.m_root'))}</button>`;
    box.innerHTML = `
      <nav class="files-side" aria-label="${esc(t('files.razdel'))}">${places}${root}</nav>
      <div class="files-main">
        <div class="files-bar">
          <button class="sm" ${FILES.parent ? '' : 'disabled'} onclick="filesGo(FILES.parent)" title="${esc(t('files.naverh'))}"
              aria-label="${esc(t('files.naverh'))}"><svg class="ic"><use href="#i-up"/></svg></button>
          <div class="files-crumbs">${filesCrumbs()}</div>
          <button class="sm ghost" onclick="filesAll()">${esc(t('files.vybrat_vse'))}</button>
        </div>
        <div class="files-list scroll" id="filesList">${filesRows()}</div>
        <div class="files-drop" aria-hidden="true">${esc(t('files.peretaschite'))}</div>
      </div>`;
    filesSelSync();
}

function filesRows() {
    if (FILES.busy) return '';
    if (FILES.error) return emptyBig({art: 'device', title: esc(t('files.net_papki')), text: esc(FILES.error)});
    if (!FILES.items.length) return emptyBig({art: 'job', title: esc(t('files.pusto')), text: esc(t('files.pusto_text'))});
    const rows = FILES.items.slice(0, FILES.shown).map((it, i) => `
      <div class="files-row${FILES.sel.has(it.path) ? ' sel' : ''}" data-i="${i}">
        <input type="checkbox" ${FILES.sel.has(it.path) ? 'checked' : ''} onchange="filesToggle(${i})"
            aria-label="${esc(it.name)}">
        <button class="files-name" onclick="filesClick(${i})" title="${esc(it.name)}">
          <svg class="ic"><use href="#i-${it.dir ? 'layers' : FILES_IMG.test(it.name) ? 'image' : 'clipboard'}"/></svg>
          <span>${esc(it.name)}</span></button>
        <small>${it.dir ? esc(t('files.papka')) : filesSize(it.size)}</small>
        <small>${esc(it.mtime)}</small>
      </div>`).join('');
    const more = FILES.items.length - FILES.shown;
    return rows + (more > 0 ? `<button class="sm files-more" onclick="filesMore()">${esc(t('files.eshche', {n: Math.min(more, FILES_PAGE)}))}</button>` : '');
}

function filesMore() {
    FILES.shown += FILES_PAGE;
    $('filesList').innerHTML = filesRows();
}

function filesClick(i) {
    const it = FILES.items[i];
    if (it.dir) return filesGo(it.path);
    if (FILES_IMG.test(it.name)) return filesPreview(it);
    filesToggle(i);
}

function filesToggle(i) {
    const p = FILES.items[i].path;
    FILES.sel.has(p) ? FILES.sel.delete(p) : FILES.sel.add(p);
    filesSelSync();
}

function filesAll() {
    const all = FILES.items.length && FILES.sel.size === FILES.items.length;
    FILES.sel = new Set(all ? [] : FILES.items.map(i => i.path));
    filesSelSync();
}

function filesSelSync() {
    document.querySelectorAll('.files-row').forEach(row => {
        const it = FILES.items[+row.dataset.i];
        const on = FILES.sel.has(it.path);
        row.classList.toggle('sel', on);
        row.querySelector('input').checked = on;
    });
    const n = FILES.sel.size;
    const get = $('filesGet'), del = $('filesDel');
    if (!get) return;
    setText(get.querySelector('span'), n ? t('files.skachat_n', {n}) : t('files.skachat'));
    setText(del.querySelector('span'), n ? t('files.udalit_n', {n}) : t('files.udalit'));
    disableWithReason(get, !n, t('files.vyberite'));
    disableWithReason(del, !n, t('files.vyberite'));
}

function filesPreview(it) {
    const list = $('filesList');
    const url = filesUrl('/preview', 'path=' + encodeURIComponent(it.path));
    list.insertAdjacentHTML('afterbegin', `<div class="files-prev" id="filesPrev">
      <button class="sm" onclick="$('filesPrev').remove()" aria-label="${esc(t('files.zakryt'))}"><svg class="ic"><use href="#i-x"/></svg></button>
      <img src="${esc(url)}" alt="${esc(it.name)}" onerror="this.replaceWith(Object.assign(document.createElement('p'),{textContent:t('files.prevyu_net')}))">
      <b>${esc(it.name)}</b></div>`);
    list.scrollTop = 0;
}

function filesDownload() {
    if (!FILES.sel.size) return;
    const q = [...FILES.sel].map(p => 'path=' + encodeURIComponent(p)).join('&');
    const one = FILES.items.find(i => FILES.sel.has(i.path));
    if (FILES.sel.size > 1 || one.dir) toast(t('files.gotovlyu'));
    pultDownload(filesUrl('/download', q));
}

async function filesUpload(files) {
    if (FILES.busy) return;
    FILES.busy = true;
    let ok = 0;
    for (const file of files) {
        toast(t('files.zagruzhayu', {file: file.name}));
        try {
            await api(filesUrl('/upload', `path=${encodeURIComponent(FILES.path)}&name=${encodeURIComponent(file.name)}`),
                {method: 'POST', body: file});
            ok++;
        } catch (e) {
            toast(t('files.ne_udalos', {error: e.message}), 'bad');
        }
    }
    FILES.busy = false;
    if (ok) toast(t('files.zagruzheno', {n: ok}), 'ok');
    filesGo(FILES.path);
}

function filesMkdir() {
    promptModal(t('files.novaya_papka'), t('files.imya_papki'), '', t('files.sozdat'), async value => {
        const name = String(value || '').trim().replace(/[\\/]/g, '');
        if (!name) return;
        try {
            await post(filesUrl('/mkdir'), {path: FILES.path + '/' + name});
            toast(t('files.sozdana'), 'ok');
        } catch (e) {
            toast(e.message, 'bad');
        }
        filesOpenAgain();
    });
}

/* promptModal занимает то же окно — возвращаем файлы на то же место. */
function filesOpenAgain() {
    filesOpen();
}

async function filesDelete(btn) {
    if (!FILES.sel.size || !armConfirm(btn, t('files.tochno'))) return;
    try {
        const r = await post(filesUrl('/delete'), {paths: [...FILES.sel]});
        toast(r.failed.length ? t('files.ne_udalos', {error: r.failed[0].error}) : t('files.udaleno', {n: r.deleted}),
            r.failed.length ? 'bad' : 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
    filesGo(FILES.path);
}

/* Файлы можно бросить прямо на окно: они уйдут в открытую папку. */
function filesDrop(el) {
    const has = ev => ev.dataTransfer && [...ev.dataTransfer.types].includes('Files');
    el.ondragover = ev => { if (has(ev)) { ev.preventDefault(); el.classList.add('drag'); } };
    el.ondragleave = ev => { if (!el.contains(ev.relatedTarget)) el.classList.remove('drag'); };
    el.ondrop = ev => {
        el.classList.remove('drag');
        if (!has(ev)) return;
        ev.preventDefault();
        filesUpload(ev.dataTransfer.files);
    };
}
