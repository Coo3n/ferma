/* Аккаунты: список + постоянный редактор. Черновики живут в памяти до
   явного сохранения. Массовый выбор независим от открытого аккаунта. */

const ACC = window.ACC = {items: [], platform: '', query: '', status: '', sel: new Set(),
    active: '', drafts: new Map(), errors: new Map(), saving: new Set(), binding: new Set(),
    revision: 0, loadSeq: 0, bulkBusy: false};

function accPlatformOptions() {
    return Object.entries(PLATFORM_NAMES)
        .map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
}

const ACC_STATUS = {
    new: t('accounts.st_new'),
    active: t('accounts.st_active'),
    login: t('accounts.st_login'),
    banned: t('accounts.st_banned'),
};

/* Фильтр статуса: «свободные» и «на телефоне» — про привязку, а «бан» и
   «нужен вход» — про сам аккаунт; это то, что ищут на сотнях строк. */
const ACC_FILTERS = [
    {key: '', label: t('accounts.f_vse'), test: () => true},
    {key: 'free', label: t('accounts.f_svobodnye'), test: a => !a.serial},
    {key: 'bound', label: t('accounts.f_na_telefone'), test: a => !!a.serial},
    {key: 'banned', label: t('accounts.f_ban'), test: a => a.status === 'banned'},
    {key: 'login', label: t('accounts.f_nuzhen_vhod'), test: a => a.status === 'login'},
];

async function loadAccounts() {
    const seq = ++ACC.loadSeq, revision = ACC.revision;
    let items;
    try {
        items = await api('/api/accounts');
    } catch (e) {
        if (!ACC.loaded) {
            setHTML($('accList'), `<div class="acc-list-empty" role="alert"><p>${esc(e.message)}</p><button onclick="loadAccounts()">${t('accounts.retry')}</button></div>`);
            renderAccDetail();
        }
        return toast(e.message, 'bad');
    }
    if (seq !== ACC.loadSeq || revision !== ACC.revision) return;
    ACC.items = items;
    ACC.loaded = true;
    /* Выбор переживает перезагрузку списка, но не удалённые строки. */
    const ids = new Set(ACC.items.map(a => a.id));
    ACC.sel = new Set([...ACC.sel].filter(id => ids.has(id)));
    for (const id of ACC.drafts.keys()) if (!ids.has(id)) ACC.drafts.delete(id);
    renderAccounts();
}

function accDevice(serial) {
    return S.devices.find(x => x.serial === serial);
}

/* Имя телефона для человека. Серийник на экран не выводим: телефона нет
   в ферме — так и пишем, а серийник — только в подсказке. */
function accDeviceName(serial) {
    if (!serial) return '';
    const d = accDevice(serial);
    return d ? d.name : t('accounts.telefon_ne_v_ferme');
}

/* Платформа и поиск — общая часть: по ней же считаются числа на чипах. */
function accBaseRows() {
    const q = ACC.query;
    return ACC.items.filter(a =>
        (!ACC.platform || a.platform === ACC.platform)
        && (!q || [a.login, a.proxy, a.phone, a.note, accDeviceName(a.serial)]
            .some(v => (v || '').toLowerCase().includes(q))));
}

function accShownRows() {
    const f = ACC_FILTERS.find(x => x.key === ACC.status) || ACC_FILTERS[0];
    return accBaseRows().filter(f.test);
}

function renderAccFilters(base) {
    const rows = accShownRows();
    const n = rows.filter(a => ACC.sel.has(a.id)).length;
    setHTML($('accFilters'), ACC.items.length ? `<label class="acc-select-all">
        <input type="checkbox" id="accSelAll" onchange="accSelAll(this.checked)"
          aria-label="${t('accounts.vybrat_vse_pokazannye')}" ${rows.length && n === rows.length ? 'checked' : ''}>
        <span>${t('accounts.select_all')}</span></label>` : '');
    setHTML($('accStatusFilter'), ACC_FILTERS.map(f => `<option value="${f.key}"${f.key === ACC.status ? ' selected' : ''}>${f.label} (${base.filter(f.test).length})</option>`).join(''));
    $('accStatusFilter').value = ACC.status;
    $('accFilters').hidden = !ACC.items.length;
    if ($('accSelAll')) $('accSelAll').indeterminate = n > 0 && n < rows.length;
}

function renderAccounts() {
    const focusedId = document.activeElement?.closest?.('#accList [data-open], #accList [data-sel]')?.closest('.acc-item')?.dataset.id;
    const focusedCheckbox = document.activeElement?.hasAttribute?.('data-sel');
    $('view-accounts').classList.toggle('acc-empty', !!ACC.loaded && !ACC.items.length);
    disableWithReason($('btnAccAutobind'), !ACC.platform || ACC.bulkBusy, ACC.bulkBusy ? t('accounts.saving') : t('accounts.snachala_platforma'));
    const sel = $('accPlatform');
    if (!sel.options.length) {
        sel.innerHTML = `<option value="">${t('accounts.vse_platformy')}</option>` + accPlatformOptions();
    }
    sel.value = ACC.platform;

    const base = accBaseRows();
    const rows = accShownRows();
    $('accBindingAction').hidden = !ACC.platform || !ACC.items.length;
    $('btnAccExport').hidden = !rows.length;
    renderAccFilters(base);
    setText($('accSummary'), t('accounts.pokazano', {n: rows.length, all: ACC.items.length}));

    const box = $('accList');
    if (!ACC.loaded) return;   // заготовки из разметки — до первого ответа
    if (!ACC.items.length) {
        setHTML(box, `<div class="acc-list-empty"><h2>${t('accounts.pusto_title')}</h2><p>${t('accounts.pusto_text')}</p></div>`);
        renderAccSelBar();
        ACC.active = '';
        renderAccDetail();
        return;
    }

    if (!rows.some(a => a.id === ACC.active)) ACC.active = rows[0]?.id || '';
    setHTML(box, rows.length ? `<ul class="acc-items">${rows.map(accRowHtml).join('')}</ul>`
        : `<div class="acc-list-empty"><p>${t('accounts.nichego')}</p><button class="sm" onclick="accResetFilters()">${t('accounts.sbrosit_filtry')}</button></div>`);
    renderAccSelBar();
    renderAccDetail();
    if (focusedId) {
        const row = [...box.querySelectorAll('.acc-item')].find(el => el.dataset.id === focusedId)
            || box.querySelector('.acc-item:has([aria-current="true"])');
        row?.querySelector(focusedCheckbox ? '[data-sel]' : '[data-open]')?.focus({preventScroll: true});
    }
}

function accSocialIcon(platform) {
    const known = ['vk', 'inst', 'tiktok', 'tg'].includes(platform) ? platform : 'vk';
    return `<span class="acc-social acc-social--${known}" aria-hidden="true"><span></span></span>`;
}

function accRowHtml(a, index) {
    const phone = a.serial ? accDeviceName(a.serial) : t('accounts.ne_privyazan');
    const reachable = a.id === ACC.active || (!ACC.active && index === 0);
    return `<li data-id="${a.id}" class="acc-item${ACC.sel.has(a.id) ? ' sel' : ''}">
      <label class="acc-check"><input type="checkbox" data-sel="${a.id}" tabindex="${reachable ? 0 : -1}" aria-label="${t('accounts.vybrat')} ${esc(a.login)}"
        ${ACC.sel.has(a.id) ? 'checked' : ''}></label>
      <button class="acc-item-open" data-open="${a.id}" tabindex="${reachable ? 0 : -1}" aria-current="${a.id === ACC.active}" onclick="accOpen('${a.id}')">
        ${accSocialIcon(a.platform)}
        <span class="acc-identity"><strong>${esc(a.login)}</strong><span>${esc(PLATFORM_NAMES[a.platform] || a.platform)} <span class="acc-draft-mark" data-draft="${a.id}">${accDraftLabel(a.id)}</span></span></span>
        <span class="acc-row-facts"><span class="acc-status acc-status--${a.status}">${esc(ACC_STATUS[a.status] || a.status)}</span>
        <span class="acc-row-phone" title="${esc(phone)}">${esc(phone)}</span></span>
      </button></li>`;
}

function accDraftLabel(id) {
    return ACC.errors.has(id) ? t('accounts.save_error') : ACC.drafts.has(id) ? '•' : '';
}

function accRefreshDraftMarks() {
    document.querySelectorAll('#accList [data-draft]').forEach(el => {
        setText(el, accDraftLabel(el.dataset.draft));
        el.setAttribute('aria-label', ACC.drafts.has(el.dataset.draft) ? t('accounts.unsaved') : '');
        el.title = ACC.drafts.has(el.dataset.draft) ? t('accounts.unsaved') : '';
    });
}

function accOpen(id) {
    ACC.active = id;
    document.querySelectorAll('#accList [data-open]').forEach((btn, i) => {
        const active = btn.dataset.open === id;
        btn.setAttribute('aria-current', String(active));
        btn.tabIndex = active || (!id && i === 0) ? 0 : -1;
        btn.closest('.acc-item').querySelector('input').tabIndex = btn.tabIndex;
    });
    $('accDetail').dataset.account = '';
    renderAccDetail();
}

function accCloseDetail() {
    const id = ACC.active;
    accOpen('');
    const button = [...document.querySelectorAll('#accList [data-open]')].find(btn => btn.dataset.open === id);
    if (button) button.focus();
}

function accDraftSet(field, value) {
    const item = ACC.items.find(a => a.id === ACC.active);
    if (!item || ACC.saving.has(item.id) || ACC.binding.has(item.id) || ACC.bulkBusy) return;
    const draft = {...ACC.drafts.get(item.id), [field]: value};
    if (field === 'password' && !value) delete draft.password;
    if (field !== 'password' && value === (item[field] || '')) delete draft[field];
    if (Object.keys(draft).length) ACC.drafts.set(item.id, draft);
    else ACC.drafts.delete(item.id);
    ACC.errors.delete(item.id);
    accEditorFeedback();
    accRefreshDraftMarks();
}

function accEditorFeedback() {
    const dirty = ACC.drafts.has(ACC.active), busy = ACC.saving.has(ACC.active) || ACC.binding.has(ACC.active) || ACC.bulkBusy;
    $('btnAccAdd').className = dirty ? 'sm' : 'sm primary';
    const error = ACC.errors.get(ACC.active) || '';
    setText($('accSaveState'), busy ? t('accounts.saving') : '');
    setText($('accEditError'), error);
    $('accEditError').hidden = !error;
    $('accSave').disabled = busy || !dirty;
    $('accReset').hidden = !dirty;
    $('accReset').disabled = busy;
    $('accEditFields').disabled = busy;
    $('accDetail').setAttribute('aria-busy', String(busy));
}

function renderAccDetail(force = false) {
    const box = $('accDetail');
    const item = ACC.items.find(a => a.id === ACC.active);
    if (!item) {
        $('btnAccAdd').className = 'sm primary';
        box.dataset.account = '';
        box.removeAttribute('aria-busy');
        box.innerHTML = `<div class="acc-detail-empty"><div class="acc-empty-platforms" aria-hidden="true">${['vk', 'inst', 'tiktok', 'tg'].map(accSocialIcon).join('')}</div>
          <h2>${t('accounts.empty_detail_title')}</h2><p>${t('accounts.empty_detail_text')}</p>
          <span class="acc-empty-key"><kbd>↑</kbd><kbd>↓</kbd><span>${t('accounts.list_hint')}</span></span></div>`;
        return;
    }
    const signature = JSON.stringify(item);
    if (!force && box.dataset.account === item.id && box.dataset.signature === signature) {
        setText($('accBoundName'), accDeviceName(item.serial) || t('accounts.ne_privyazan'));
        return;
    }
    const focused = box.dataset.account === item.id ? document.activeElement?.closest('#accDetail [data-edit]') : null;
    const focusName = focused?.dataset.edit;
    const caret = focused && typeof focused.selectionStart === 'number' ? focused.selectionStart : null;
    box.dataset.account = item.id;
    box.dataset.signature = signature;
    const a = {...item, ...ACC.drafts.get(item.id)};
    const input = (key, type = 'text') => `<input id="accEdit-${key}" name="${key}" data-edit="${key}" type="${type}"
        value="${esc(a[key] || '')}" autocomplete="${key === 'password' ? 'new-password' : 'off'}" spellcheck="false"
        ${key === 'login' ? 'required aria-describedby="accEditError"' : key === 'password' ? 'aria-describedby="accPasswordHint"' : ''}>`;
    box.innerHTML = `<form class="acc-editor" onsubmit="event.preventDefault();accSaveDetail()" novalidate>
      <header class="acc-detail-head">${accSocialIcon(item.platform)}<div class="acc-detail-identity"><h2>${esc(item.login)}</h2><span>${esc(PLATFORM_NAMES[item.platform] || item.platform)}</span></div>
      <button type="button" class="ghost acc-close" onclick="accCloseDetail()" aria-label="${t('accounts.close_detail')}"><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg></button></header>
      <fieldset id="accEditFields">
        <div class="acc-binding"><div><span class="acc-field-label">${t('accounts.telefon')}</span>
          <button type="button" class="acc-binding-button" onclick="accPickPhone('${item.id}')"><svg class="ic" aria-hidden="true"><use href="#i-phone"/></svg>
          <span id="accBoundName">${esc(accDeviceName(item.serial) || t('accounts.ne_privyazan'))}</span><span class="acc-binding-change">${t('accounts.change')}</span></button>
          <small>${t('accounts.binding_saved')}</small></div></div>
        <div class="acc-form-grid">
          <label>${t('accounts.platforma')}<select name="platform" data-edit="platform">${accPlatformOptions().replace(`value="${a.platform}"`, `value="${a.platform}" selected`)}</select></label>
          <label>${t('accounts.status')}<select name="status" data-edit="status">${Object.entries(ACC_STATUS).map(([k,v]) => `<option value="${k}"${k === a.status ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
          <label>${t('accounts.login')}${input('login')}</label>
          <div class="acc-password-field"><label for="accEdit-password">${t('accounts.parol')}</label><div class="acc-password-input">
            ${input('password', 'password')}<button type="button" class="ghost" aria-label="${t('accounts.pokazat_parol')}" onclick="accShowPw('${item.id}', this)"><svg class="ic" aria-hidden="true"><use href="#i-eye-off"/></svg></button></div>
            <small id="accPasswordHint">${item.has_password ? t('accounts.password_keep') : t('accounts.ne_zadan')}</small></div>
          <label>${t('accounts.proksi')}${input('proxy')}</label>
          <label>${t('accounts.zametka')}<textarea name="note" data-edit="note" rows="2">${esc(a.note || '')}</textarea></label>
        </div>
      </fieldset>
      <p id="accEditError" class="acc-edit-error" role="alert" hidden></p>
      <footer class="acc-editor-footer"><div class="acc-save-actions"><button class="primary" id="accSave" type="submit" aria-describedby="accSaveState">${t('accounts.save')}</button>
        <button id="accReset" type="button" onclick="accResetDetail()">${t('accounts.discard')}</button>
        <span id="accSaveState" role="status"></span></div>
        <button type="button" class="ghost danger" onclick="accDelete('${item.id}', this)" aria-label="${t('accounts.udalit_akkaunt')}"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg></button></footer>
    </form>`;
    $('accEdit-password').placeholder = item.has_password ? '••••••••' : '';
    accEditorFeedback();
    if (focusName) {
        const field = box.querySelector(`[data-edit="${focusName}"]`);
        field.focus({preventScroll: true});
        if (caret !== null && field.type !== 'password') field.setSelectionRange(caret, caret);
    }
}

function accResetDetail() {
    ACC.drafts.delete(ACC.active);
    ACC.errors.delete(ACC.active);
    accRefreshDraftMarks();
    renderAccDetail(true);
    $('accEdit-login').focus();
}

async function accSaveDetail() {
    const id = ACC.active, draft = ACC.drafts.get(id);
    if (!draft || ACC.saving.has(id) || ACC.binding.has(id) || ACC.bulkBusy) return;
    const item = ACC.items.find(a => a.id === id);
    if (!(draft.login ?? item.login).trim()) {
        ACC.errors.set(id, t('accounts.vpishite_login'));
        accEditorFeedback();
        $('accEdit-login').setAttribute('aria-invalid', 'true');
        $('accEdit-login').focus();
        return;
    }
    ACC.saving.add(id);
    ACC.revision++;
    accEditorFeedback();
    try {
        const saved = await api(`/api/accounts/${id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(draft)});
        const current = ACC.items.find(a => a.id === id);
        if (current) Object.assign(current, saved);
        ACC.drafts.delete(id);
        ACC.errors.delete(id);
        toast(t('accounts.sohraneno'), 'ok');
    } catch (e) {
        ACC.errors.set(id, e.message);
    } finally {
        ACC.saving.delete(id);
        ACC.revision++;
        renderAccounts();
        if (ACC.active === id) renderAccDetail(true);
    }
}

document.addEventListener('input', ev => {
    const field = ev.target.closest('#accDetail [data-edit]');
    if (field) {
        field.removeAttribute('aria-invalid');
        accDraftSet(field.dataset.edit, field.value);
    }
});

document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && !$('accAddMenu').hidden) {
        accAddMenuToggle(false);
        $('btnAccAdd').focus();
        ev.preventDefault();
        return;
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's' && S.view === 'accounts') {
        ev.preventDefault();
        accSaveDetail();
    }
    if (S.view !== 'accounts' || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    const row = ev.target.closest('#accList .acc-item');
    const btn = row?.querySelector('[data-open]');
    if (btn && ev.target === btn && ev.key === ' ') {
        ev.preventDefault();
        const box = btn.closest('.acc-item').querySelector('input');
        box.checked = !box.checked;
        accToggleSel(box);
        return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(ev.key)) return;
    const fromSearch = ev.target === $('accSearch') && ['ArrowDown', 'ArrowUp'].includes(ev.key);
    const fromPage = ev.target === document.body || ev.target === $('view-accounts') || ev.target === $('accList')
        || ev.target.closest('[data-view="accounts"]');
    if (!btn && !fromSearch && !fromPage) return;
    if (document.querySelector('.modal.on, dialog[open]')) return;
    ev.preventDefault();
    const buttons = [...document.querySelectorAll('#accList [data-open]')];
    if (!buttons.length) return;
    const current = btn ? buttons.indexOf(btn) : buttons.findIndex(el => el.dataset.open === ACC.active);
    const index = ev.key === 'Home' || (fromSearch && ev.key === 'ArrowDown') ? 0
        : ev.key === 'End' || (fromSearch && ev.key === 'ArrowUp') ? buttons.length - 1
        : Math.max(0, Math.min(buttons.length - 1, current + (ev.key === 'ArrowDown' ? 1 : -1)));
    buttons[index].focus();
    buttons[index].scrollIntoView({block: 'nearest'});
    accOpen(buttons[index].dataset.open);
});

function accAddMenuToggle(open = $('accAddMenu').hidden) {
    $('accAddMenu').hidden = !open;
    $('btnAccAdd').setAttribute('aria-expanded', String(open));
    if (open) $('accAddMenu').querySelector('button').focus();
}

document.addEventListener('click', ev => {
    if (!ev.target.closest('.acc-add-control')) accAddMenuToggle(false);
});

/* Drafts stay in memory only, including passwords; never localStorage. */
if (window.addEventListener) window.addEventListener('beforeunload', ev => {
    if (!ACC.drafts.size) return;
    ev.preventDefault();
    ev.returnValue = '';
});

/* ------------------------------------------------------------ фильтры */

function accSetStatus(key) {
    ACC.status = key;
    renderAccounts();
}

function accResetFilters() {
    ACC.status = '';
    ACC.query = '';
    ACC.platform = '';
    $('accSearch').value = '';
    renderAccounts();
}

function accFilter() {
    ACC.platform = $('accPlatform').value;
    ACC.query = $('accSearch').value.trim().toLowerCase();
    renderAccounts();
}

/* ------------------------------------------------------------ выбор */

function accSelAll(on) {
    accShownRows().forEach(a => (on ? ACC.sel.add(a.id) : ACC.sel.delete(a.id)));
    renderAccounts();
}

function accSelClear() {
    ACC.sel.clear();
    renderAccounts();
}

/* Панель выбора — только когда что-то выбрано: на пустом выборе ей нечего
   предложить. Считает и выбранные вне фильтра — удалятся и они, поэтому
   об этом говорим прямо. */
function renderAccSelBar() {
    const bar = $('accSelBar');
    const n = ACC.sel.size;
    bar.hidden = !n;
    if (!n) return setHTML(bar, '');
    const shown = new Set(accShownRows().map(a => a.id));
    const hidden = [...ACC.sel].filter(id => !shown.has(id)).length;
    setHTML(bar, `<span class="selbar-n">${t('accounts.vybrano', {n})}</span>
      ${hidden ? `<span class="dim">${t('accounts.iz_nih_skryto', {n: hidden})}</span>` : ''}
      <button class="sm" id="btnAccUnbindSel" onclick="accUnbindSel(this)">
        <svg class="ic" aria-hidden="true"><use href="#i-phone"/></svg>${t('accounts.otvyazat_ot_telefonov')}</button>
      <button class="sm danger" id="btnAccDelSel" onclick="accDeleteSel(this)">
        <svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg><span>${t('accounts.udalit_vybrannye', {n})}</span></button>
      <span class="sp"></span>
      <button class="sm ghost" onclick="accSelClear()">${t('accounts.snyat_vybor')}</button>`);
    const bound = ACC.items.filter(a => ACC.sel.has(a.id) && a.serial).length;
    const busy = ACC.bulkBusy || ACC.saving.size > 0 || ACC.binding.size > 0;
    disableWithReason($('btnAccUnbindSel'), !bound || busy, busy ? t('accounts.saving') : t('accounts.nikto_ne_privyazan'));
    disableWithReason($('btnAccDelSel'), busy, t('accounts.saving'));
}

async function accDeleteSel(btn) {
    if (ACC.bulkBusy || ACC.saving.size || ACC.binding.size) return;
    const ids = [...ACC.sel];
    if (!armConfirm(btn, t('accounts.udalit_tochno', {n: ids.length}))) return;
    btn.disabled = true;
    ACC.bulkBusy = true;
    ACC.revision++;
    if (ACC.active) accEditorFeedback();
    try {
        const res = await post('/api/accounts/delete', {ids});
        ACC.revision++;
        ACC.sel.clear();
        toast(t('accounts.udaleno_n', {n: res.deleted}), 'ok');
        await loadAccounts();
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
    } finally {
        ACC.bulkBusy = false;
        renderAccounts();
        if (ACC.active) accEditorFeedback();
    }
}

async function accUnbindSel(btn) {
    if (ACC.bulkBusy || ACC.saving.size || ACC.binding.size) return;
    btn.disabled = true;
    ACC.bulkBusy = true;
    ACC.revision++;
    if (ACC.active) accEditorFeedback();
    try {
        const res = await post('/api/accounts/unbind', {ids: [...ACC.sel]});
        ACC.revision++;
        toast(t('accounts.otvyazano_n', {n: res.unbound}), 'ok');
        await loadAccounts();
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
    } finally {
        ACC.bulkBusy = false;
        renderAccounts();
        if (ACC.active) accEditorFeedback();
    }
}

/* CSV — то, что сейчас на экране (с фильтрами), без паролей: файл уходит
   из фермы, а пароль отдаётся только по явному «показать». */
function accCsv() {
    const rows = accShownRows();
    /* Ячейка с = + - @ в начале Excel считает формулой — гасим апострофом. */
    const cell = v => {
        let s = String(v ?? '');
        if (/^[=+\-@]/.test(s)) s = "'" + s;
        return /[",;\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [t('accounts.csv_head')].concat(rows.map(a => [
        PLATFORM_NAMES[a.platform] || a.platform, a.login, a.proxy,
        ACC_STATUS[a.status] || a.status, accDeviceName(a.serial),
    ].map(cell).join(',')));
    /* BOM — чтобы Excel узнал UTF-8 и не показал кракозябры. */
    const blob = new Blob(['﻿' + lines.join('\r\n') + '\r\n'], {type: 'text/csv;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'accounts.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    toast(t('accounts.csv_gotovo', {n: rows.length}), 'ok');
}

/* ------------------------------------------------------------ строка */

async function accShowPw(id, btn) {
    const input = $('accEdit-password');
    if (input.type === 'text') {
        input.type = 'password';
        btn.setAttribute('aria-label', t('accounts.pokazat_parol'));
        return;
    }
    if (ACC.drafts.get(id)?.password !== undefined || input.value) {
        input.type = 'text';
        btn.setAttribute('aria-label', t('accounts.hide_password'));
        return;
    }
    btn.disabled = true;
    try {
        const {password} = await api(`/api/accounts/${id}/password`);
        if (!btn.isConnected || ACC.active !== id || ACC.drafts.get(id)?.password !== undefined) return;
        input.type = 'text';
        input.value = password;
        btn.setAttribute('aria-label', t('accounts.hide_password'));
    } catch (e) {
        ACC.errors.set(id, e.message);
        if (ACC.active === id) accEditorFeedback();
    } finally {
        btn.disabled = false;
    }
}

/* Привязка к телефону — общий выбор телефона (devices.js), плюс «отвязать».
   Телефон, на котором уже есть аккаунт этой платформы, помечен: два VK на
   одном телефоне — путаница сценариев и риск бана, поэтому такой выбор
   подтверждается вторым нажатием. */
function accPickPhone(id) {
    const item = ACC.items.find(a => a.id === id);
    if (ACC.drafts.get(id)?.platform && ACC.drafts.get(id).platform !== item.platform) {
        ACC.errors.set(id, t('accounts.save_platform_first'));
        accEditorFeedback();
        return;
    }
    const pname = PLATFORM_NAMES[item.platform] || item.platform;
    const taken = new Set(ACC.items
        .filter(a => a.id !== id && a.platform === item.platform && a.serial).map(a => a.serial));
    $('mTitle').textContent = t('accounts.telefon_dlya', {login: item.login});
    $('mBody').innerHTML = `<div class="phone-pick">
      <button onclick="closeModal();accBind('${id}', '')"><span class="dot"></span><b>${t('accounts.ne_privyazan')}</b><span>${t('accounts.otvyazat')}</span></button>
      ${S.devices.filter(d => !S.hidden.has(d.serial)).map(d => {
        const dup = taken.has(d.serial);
        const hint = [d.group, dup ? t('accounts.uzhe_est', {p: pname}) : ''].filter(Boolean).join(' · ');
        return `<button class="${d.serial === item.serial ? 'on' : ''}${dup ? ' acc-dup' : ''}"
            onclick="accPickGo(this, '${id}', '${esc(d.serial)}', ${dup})">
        <span class="dot ${d.online ? 'on' : ''}"></span><b>${esc(d.name)}</b>
        <span class="acc-hint">${esc(hint)}</span></button>`;
    }).join('')}</div>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">${t('accounts.otmena')}</button>`;
    openModal();
}

function accPickGo(btn, id, serial, dup) {
    if (dup && !armConfirm(btn, '')) {
        const item = ACC.items.find(a => a.id === id);
        const hint = btn.querySelector('.acc-hint');
        const was = hint.textContent;
        hint.textContent = t('accounts.eshche_raz_dva', {p: PLATFORM_NAMES[item.platform] || item.platform});
        setTimeout(() => { hint.textContent = was; }, 4000);
        return;
    }
    closeModal();
    accBind(id, serial);
}

async function accBind(id, serial) {
    if (ACC.binding.has(id) || ACC.saving.has(id) || ACC.bulkBusy) return;
    ACC.binding.add(id);
    ACC.revision++;
    if (ACC.active === id) accEditorFeedback();
    try {
        const item = await api(`/api/accounts/${id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial}),
        });
        const current = ACC.items.find(a => a.id === id);
        if (current) Object.assign(current, item);
        renderAccounts();
        toast(serial ? t('accounts.privyazano') : t('accounts.otvyazano'), 'ok');
    } catch (e) {
        ACC.errors.set(id, e.message);
        toast(e.message, 'bad');
    } finally {
        ACC.binding.delete(id);
        ACC.revision++;
        renderAccounts();
        if (ACC.active === id) accEditorFeedback();
    }
}

/* Галочка выбора меняет только свою строку и панель — без перерисовки
   500 строк на каждый щелчок. */
function accToggleSel(box) {
    const id = box.dataset.sel;
    if (box.checked) ACC.sel.add(id); else ACC.sel.delete(id);
    box.closest('.acc-item').classList.toggle('sel', box.checked);
    const rows = accShownRows();
    const n = rows.filter(a => ACC.sel.has(a.id)).length;
    const all = $('accSelAll');
    all.checked = rows.length > 0 && n === rows.length;
    all.indeterminate = n > 0 && n < rows.length;
    /* таблица изменилась мимо setHTML — следующая перерисовка не должна
       счесть её прежней */
    $('accList')._html = '';
    renderAccSelBar();
}

document.addEventListener('change', ev => {
    const box = ev.target.closest('#accList [data-sel]');
    if (box) return accToggleSel(box);
});

async function accDelete(id, btn) {
    if (ACC.saving.has(id) || ACC.binding.has(id) || ACC.bulkBusy) return;
    btn.title = t('accounts.nazhmite_eshche_title');
    if (!armConfirm(btn, '')) {
        toast(t('accounts.nazhmite_eshche'));
        return;
    }
    const acc = ACC.items.find(a => a.id === id);
    ACC.revision++;
    btn.disabled = true;
    try {
        await api(`/api/accounts/${id}`, {method: 'DELETE'});
        ACC.items = ACC.items.filter(a => a.id !== id);
        ACC.sel.delete(id);
        ACC.drafts.delete(id);
        ACC.errors.delete(id);
        ACC.revision++;
        renderAccounts();
        toast(t('accounts.udalen', {login: acc ? acc.login : ''}));
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
    }
}

/* ------------------------------------------------------------ импорт */

/* Тот же разбор, что parse_lines в backend/farm/accounts.py: первый
   встретившийся разделитель по старшинству, остаток после пароля — прокси.
   Предпросмотр должен обещать ровно то, что сделает сервер. */
const ACC_SEPARATORS = ['\t', ';', ':', ','];

function accParseLine(line) {
    const sep = ACC_SEPARATORS.find(s => line.includes(s));
    const parts = sep ? line.split(sep).map((p, i) => i === 1 ? p : p.trim()) : [line.trim()];
    return {
        login: parts[0],
        password: parts.length > 1 ? parts[1] : '',
        proxy: parts.length > 2 ? parts.slice(2).join(sep) : '',
    };
}

/* Строки вставки с итогом: ok / dup (тот же логин этой платформы уже есть
   или повторился выше) / bad (нет пароля) — как в import_report. */
function accImportPlan(text, platform) {
    const known = new Set(ACC.items.filter(a => a.platform === platform)
        .map(a => (a.login || '').toLowerCase()));
    const rows = [];
    (text || '').split(/\r?\n/).forEach((raw, i) => {
        const line = raw.trim();
        if (!line || line.startsWith('#')) return;
        const row = accParseLine(raw);
        row.n = i + 1;
        const key = row.login.toLowerCase();
        if (!row.password) row.kind = 'bad';
        else if (known.has(key)) row.kind = 'dup';
        else {
            row.kind = 'ok';
            known.add(key);
        }
        rows.push(row);
    });
    return rows;
}

const ACC_IMPORT_SHOW = 100;

function accImportPreview() {
    const rows = accImportPlan($('accImpText').value, $('accImpPlatform').value);
    const count = k => rows.filter(r => r.kind === k).length;
    const ok = count('ok');
    const word = {ok: t('accounts.imp_ok'), dup: t('accounts.imp_dup'), bad: t('accounts.imp_bad')};
    /* Сначала то, что не войдёт: ради этих строк предпросмотр и нужен. */
    const order = {bad: 0, dup: 1, ok: 2};
    const shown = rows.slice().sort((a, b) => order[a.kind] - order[b.kind] || a.n - b.n)
        .slice(0, ACC_IMPORT_SHOW);
    setHTML($('accImpPreview'), rows.length ? `<div class="acc-imp-sum">
        <span class="acc-imp--ok">${t('accounts.imp_dobavitsya', {n: ok})}</span>
        ${count('dup') ? `<span class="acc-imp--dup">${t('accounts.imp_uzhe_est_n', {n: count('dup')})}</span>` : ''}
        ${count('bad') ? `<span class="acc-imp--bad">${t('accounts.imp_bez_parolya_n', {n: count('bad')})}</span>` : ''}</div>
      <div class="acc-imp-wrap"><table class="acc-imp">
        <thead><tr><th>${t('accounts.imp_stroka')}</th><th>${t('accounts.login')}</th>
          <th>${t('accounts.proksi')}</th><th></th></tr></thead>
        <tbody>${shown.map(r => `<tr><td class="dim">${r.n}</td><td>${esc(r.login)}</td>
          <td class="acc-imp-proxy" title="${esc(r.proxy)}">${esc(r.proxy) || '—'}</td>
          <td class="acc-imp--${r.kind}">${word[r.kind]}</td></tr>`).join('')}</tbody></table>
        ${rows.length > shown.length ? `<p class="dim">${t('accounts.imp_eshche', {n: rows.length - shown.length})}</p>` : ''}</div>` : '');
    const btn = $('accImpGo');
    if (btn.dataset.busy) return;
    btn.textContent = ok ? t('accounts.dobavit_n', {n: ok}) : t('accounts.dobavit');
    disableWithReason(btn, !ok, rows.length ? t('accounts.imp_net_novyh') : t('accounts.imp_vstavte'));
}

function accImport() {
    $('mTitle').textContent = t('accounts.imp_title');
    $('mBody').innerHTML = `
    <label class="bulk-row">${t('accounts.platforma')}
      <select id="accImpPlatform" onchange="accImportPreview()">${accPlatformOptions()}</select></label>
    <label class="bulk-row">${t('accounts.imp_po_stroke')}
      <div class="fmt-ex">
        <span class="fmt"><b>${t('accounts.fmt_login')}</b><i>:</i><b>${t('accounts.fmt_parol')}</b></span>
        <span>${t('accounts.fmt_ili')}</span>
        <span class="fmt"><b>${t('accounts.fmt_login')}</b><i>:</i><b>${t('accounts.fmt_parol')}</b><i>:</i><b class="opt">${t('accounts.fmt_proksi')}</b></span>
      </div>
      <textarea id="accImpText" rows="8" oninput="accImportPreview()"
        placeholder="79001234567:secret&#10;user@mail.ru:pass:1.2.3.4:8080"></textarea></label>
    <div id="accImpPreview" aria-live="polite"></div>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">${t('accounts.otmena')}</button>
      <button class="primary" id="accImpGo" onclick="accImportGo(this)">${t('accounts.dobavit')}</button>`;
    $('accImpPlatform').value = ACC.platform || 'vk';
    openModal();
    accImportPreview();
}

async function accImportGo(btn) {
    /* Двойной клик раньше отправлял список дважды. */
    btn.disabled = true;
    btn.dataset.busy = '1';
    try {
        const res = await post('/api/accounts/import', {
            text: $('accImpText').value, platform: $('accImpPlatform').value,
        });
        const bad = res.bad_lines || [];
        const parts = [t('accounts.imp_dobavleno', {n: res.count})];
        if (res.duplicates) parts.push(t('accounts.imp_propushcheny', {n: res.duplicates}));
        if (bad.length) parts.push(t('accounts.imp_bez_parolya_stroki', {list: bad.slice(0, 5).join(', ') + (bad.length > 5 ? '…' : '')}));
        toast(parts.join(', '), bad.length ? 'bad' : 'ok');
        closeModal();
        loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
        delete btn.dataset.busy;
        btn.disabled = false;
    }
}

/* Сначала форма, потом запись на сервер: раньше «Добавить» сразу
   создавал аккаунт «новый», и отказ оставлял мусор. */
function accAdd() {
    $('mTitle').textContent = t('accounts.novyy');
    $('mBody').innerHTML = `
      <label class="bulk-row">${t('accounts.platforma')} <select id="accNewPlatform">${accPlatformOptions()}</select></label>
      <label class="bulk-row">${t('accounts.login')} <input id="accNewLogin" name="login" autocomplete="off" spellcheck="false" required aria-describedby="accNewError" oninput="this.removeAttribute('aria-invalid');$('accNewError').hidden=true"></label>
      <label class="bulk-row">${t('accounts.parol')} <input id="accNewPassword" type="password" autocomplete="new-password"></label>
      <label class="bulk-row">${t('accounts.proksi')} <input id="accNewProxy" placeholder="${t('accounts.proksi_neob')}"></label>
      <p id="accNewError" class="acc-edit-error" role="alert" hidden></p>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">${t('accounts.otmena')}</button>
      <button class="primary" onclick="accAddGo(this)">${t('accounts.dobavit')}</button>`;
    $('accNewPlatform').value = ACC.platform || 'vk';
    openModal();
    $('accNewLogin').focus();
}

async function accAddGo(btn) {
    const login = $('accNewLogin').value.trim();
    if (!login) {
        setText($('accNewError'), t('accounts.vpishite_login'));
        $('accNewError').hidden = false;
        $('accNewLogin').setAttribute('aria-invalid', 'true');
        $('accNewLogin').focus();
        return;
    }
    btn.disabled = true;
    try {
        await post('/api/accounts', {
            platform: $('accNewPlatform').value, login,
            password: $('accNewPassword').value, proxy: $('accNewProxy').value,
        });
        closeModal();
        toast(t('accounts.dobavlen'), 'ok');
        loadAccounts();
    } catch (e) {
        btn.disabled = false;
        setText($('accNewError'), e.message);
        $('accNewError').hidden = false;
    }
}

/* Раздать: каждому телефону без аккаунта этой платформы — свободный. */
async function accAutobind() {
    if (ACC.bulkBusy || ACC.saving.size || ACC.binding.size) return;
    const platform = ACC.platform;
    if (!platform) return toast(t('accounts.snachala_platforma'), 'bad');
    /* Только видимые телефоны в сети: офлайн и скрытые — не в работе. */
    const serials = S.devices.filter(d => d.online && !S.hidden.has(d.serial)).map(d => d.serial);
    if (!serials.length) return toast(t('accounts.net_telefonov'), 'bad');
    const btn = $('btnAccAutobind');
    btn.disabled = true;
    ACC.bulkBusy = true;
    ACC.revision++;
    if (ACC.active) accEditorFeedback();
    try {
        const res = await post('/api/accounts/autobind', {platform, serials});
        ACC.revision++;
        toast(res.count ? t('accounts.razdano', {p: PLATFORM_NAMES[platform], n: res.count})
            : t('accounts.nekomu', {p: PLATFORM_NAMES[platform]}),
            res.count ? 'ok' : undefined);
        await loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
    } finally {
        ACC.bulkBusy = false;
        disableWithReason(btn, !ACC.platform, t('accounts.snachala_platforma'));
        if (ACC.active) accEditorFeedback();
    }
}

/* Имена телефонов приходят опросом фермы (devices.js) — и позже, чем список
   аккаунтов, если страницу открыли сразу на «Аккаунтах». Перерисовываем,
   когда они сменились; фильтры и выбор живут в ACC и не сбрасываются.
   Пока человек правит поле в таблице — не трогаем её. */
let accDevSig = '';
setInterval(() => {
    if (S.view !== 'accounts' || !ACC.items.length) return;
    const sig = S.devices.map(d => d.serial + '\u0001' + d.name).join('\u0002');
    if (sig === accDevSig) return;
    if (document.activeElement && document.activeElement.closest
        && document.activeElement.closest('#view-accounts input, #view-accounts select, #view-accounts textarea')) return;
    accDevSig = sig;
    renderAccounts();
}, 2000);

window.loadAccounts = loadAccounts;
