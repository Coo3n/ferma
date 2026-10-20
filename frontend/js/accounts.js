/* Аккаунты: таблица с правкой на месте.

   Любое поле меняется прямо в строке и сохраняется при уходе с поля —
   без отдельной формы «редактировать». Сценарий берёт аккаунт своего
   телефона через ctx.account("vk"), поэтому главное здесь — колонка
   «Телефон».

   Рассчитано на 500 аккаунтов: фильтр по статусу и поиск сужают список,
   выделение галочками — пачкой удалить, отвязать; каждая пачка — один
   запрос, а не 500. */

const ACC = window.ACC = {items: [], platform: '', query: '', status: '', sel: new Set()};

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
    try {
        ACC.items = await api('/api/accounts');
        ACC.loaded = true;
    } catch (e) {
        return toast(e.message, 'bad');
    }
    /* Выбор переживает перезагрузку списка, но не удалённые строки. */
    const ids = new Set(ACC.items.map(a => a.id));
    ACC.sel = new Set([...ACC.sel].filter(id => ids.has(id)));
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
    const chips = ACC_FILTERS.map(f => {
        const n = base.filter(f.test).length;
        return `<button class="chip${f.key === ACC.status ? ' on' : ''}" aria-pressed="${f.key === ACC.status}"
            onclick="accSetStatus('${f.key}')">${f.label} <span class="acc-n">${n}</span></button>`;
    }).join('');
    setHTML($('accFilters'), ACC.items.length ? `<div class="chips" role="group"
        aria-label="${t('accounts.filtr_statusa')}">${chips}</div><span class="sp"></span>
      <button class="sm ghost" onclick="accCsv()" title="${t('accounts.csv_title')}">
        <svg class="ic" aria-hidden="true"><use href="#i-download"/></svg>${t('accounts.skachat_csv')}</button>` : '');
    $('accFilters').hidden = !ACC.items.length;
}

function renderAccounts() {
    disableWithReason($('btnAccAutobind'), !ACC.platform, t('accounts.snachala_platforma'));
    const sel = $('accPlatform');
    if (!sel.options.length) {
        sel.innerHTML = `<option value="">${t('accounts.vse_platformy')}</option>` + accPlatformOptions();
    }
    sel.value = ACC.platform;

    const base = accBaseRows();
    const rows = accShownRows();
    renderAccFilters(base);
    setText($('accSummary'), rows.length !== ACC.items.length
        ? t('accounts.pokazano', {n: rows.length, all: ACC.items.length}) : '');

    const box = $('accList');
    if (!ACC.loaded) return;   // заготовки из разметки — до первого ответа
    if (!ACC.items.length) {
        setHTML(box, emptyBig({
            art: 'scenario',
            title: t('accounts.pusto_title'),
            text: t('accounts.pusto_text'),
            action: {label: t('accounts.vstavit_spiskom'), icon: 'copy', onClick: 'accImport()'},
        }));
        renderAccSelBar();
        return;
    }

    const shownSel = rows.filter(a => ACC.sel.has(a.id)).length;
    /* Телефон — кнопка с одним общим выбором, а не select в каждой строке:
       на 500 аккаунтах × 100 телефонов это было 50 000 пунктов в DOM.
       Пароль не приходит с сервера целиком — только «задан / не задан»;
       показать — по явной кнопке. */
    setHTML(box, `<table class="acc-table">
      <thead><tr><th class="acc-ck"><input type="checkbox" id="accSelAll" onchange="accSelAll(this.checked)"
            title="${t('accounts.vybrat_vse_pokazannye')}" aria-label="${t('accounts.vybrat_vse_pokazannye')}"
            ${rows.length && shownSel === rows.length ? 'checked' : ''}></th>
        <th>${t('accounts.platforma')}</th><th>${t('accounts.login')}</th><th>${t('accounts.parol')}</th>
        <th>${t('accounts.proksi')}</th><th>${t('accounts.telefon')}</th><th>${t('accounts.status')}</th>
        <th>${t('accounts.zametka')}</th><th></th></tr></thead>
      <tbody>${rows.length ? rows.map(accRowHtml).join('') : `<tr><td colspan="9" class="acc-none">
        ${t('accounts.nichego')} <button class="sm ghost" onclick="accResetFilters()">${t('accounts.sbrosit_filtry')}</button></td></tr>`}</tbody></table>`);
    const all = $('accSelAll');
    if (all) all.indeterminate = shownSel > 0 && shownSel < rows.length;
    renderAccSelBar();
}

function accRowHtml(a) {
    const known = !a.serial || accDevice(a.serial);
    const phone = a.serial ? accDeviceName(a.serial) : t('accounts.ne_privyazan');
    return `<tr data-id="${a.id}"${ACC.sel.has(a.id) ? ' class="sel"' : ''}>
        <td class="acc-ck"><input type="checkbox" data-sel="${a.id}" aria-label="${t('accounts.vybrat')} ${esc(a.login)}"
            ${ACC.sel.has(a.id) ? 'checked' : ''}></td>
        <td><select data-f="platform" aria-label="${t('accounts.platforma')}">${accPlatformOptions()
            .replace(`value="${a.platform}"`, `value="${a.platform}" selected`)}</select></td>
        <td><input data-f="login" value="${esc(a.login)}" aria-label="${t('accounts.login')}"></td>
        <td class="acc-pw"><input data-f="password" type="password" aria-label="${t('accounts.parol')}"
                   placeholder="${a.has_password ? '••••••' : t('accounts.ne_zadan')}" autocomplete="off">
            ${a.has_password ? `<button class="sm ghost" title="${t('accounts.pokazat_parol')}" aria-label="${t('accounts.pokazat_parol')}"
                onclick="accShowPw('${a.id}', this)"><svg class="ic"><use href="#i-eye-off"/></svg></button>` : ''}</td>
        <td class="acc-proxy"><input data-f="proxy" value="${esc(a.proxy)}" placeholder="—" aria-label="${t('accounts.proksi')}"
            ${a.proxy ? `title="${esc(a.proxy)}"` : ''}></td>
        <td><button class="sm acc-phone" onclick="accPickPhone('${a.id}')"
                    aria-label="${t('accounts.telefon')}: ${esc(phone)}"${known ? '' : ` title="${esc(a.serial)}"`}>
            ${a.serial ? (known ? esc(phone) : `<span class="dim">${esc(phone)}</span>`)
                : `<span class="dim">${esc(phone)}</span>`}</button></td>
        <td><select data-f="status" aria-label="${t('accounts.status')}" class="acc-st acc-st--${a.status}">${Object.entries(ACC_STATUS)
            .map(([k, v]) => `<option value="${k}"${k === a.status ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
        <td><input data-f="note" value="${esc(a.note)}" placeholder="—" aria-label="${t('accounts.zametka')}"></td>
        <td><button class="sm danger" title="${t('accounts.udalit_akkaunt')}" aria-label="${t('accounts.udalit_akkaunt')}"
                    onclick="accDelete('${a.id}', this)"><svg class="ic"><use href="#i-trash"/></svg></button></td>
      </tr>`;
}

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
    disableWithReason($('btnAccUnbindSel'), !bound, t('accounts.nikto_ne_privyazan'));
}

async function accDeleteSel(btn) {
    const ids = [...ACC.sel];
    if (!armConfirm(btn, t('accounts.udalit_tochno', {n: ids.length}))) return;
    btn.disabled = true;
    try {
        const res = await post('/api/accounts/delete', {ids});
        ACC.sel.clear();
        toast(t('accounts.udaleno_n', {n: res.deleted}), 'ok');
        await loadAccounts();
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
    }
}

async function accUnbindSel(btn) {
    btn.disabled = true;
    try {
        const res = await post('/api/accounts/unbind', {ids: [...ACC.sel]});
        toast(t('accounts.otvyazano_n', {n: res.unbound}), 'ok');
        await loadAccounts();
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
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
    try {
        const {password} = await api(`/api/accounts/${id}/password`);
        const input = btn.parentElement.querySelector('input');
        input.type = 'text';
        input.value = password;
        btn.remove();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Привязка к телефону — общий выбор телефона (devices.js), плюс «отвязать».
   Телефон, на котором уже есть аккаунт этой платформы, помечен: два VK на
   одном телефоне — путаница сценариев и риск бана, поэтому такой выбор
   подтверждается вторым нажатием. */
function accPickPhone(id) {
    const item = ACC.items.find(a => a.id === id);
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
    try {
        const item = await api(`/api/accounts/${id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial}),
        });
        Object.assign(ACC.items.find(a => a.id === id), item);
        renderAccounts();
        toast(serial ? t('accounts.privyazano') : t('accounts.otvyazano'), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Галочка выбора меняет только свою строку и панель — без перерисовки
   500 строк на каждый щелчок. */
function accToggleSel(box) {
    const id = box.dataset.sel;
    if (box.checked) ACC.sel.add(id); else ACC.sel.delete(id);
    box.closest('tr').classList.toggle('sel', box.checked);
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

/* Одно сохранение на изменённое поле: change срабатывает при уходе с поля,
   а не на каждую букву. */
document.addEventListener('change', async ev => {
    const box = ev.target.closest('#accList [data-sel]');
    if (box) return accToggleSel(box);
    const field = ev.target.closest('#accList [data-f]');
    if (!field) return;
    const id = field.closest('tr').dataset.id;
    try {
        const item = await api(`/api/accounts/${id}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({[field.dataset.f]: field.value}),
        });
        Object.assign(ACC.items.find(a => a.id === id), item);
        if (field.dataset.f === 'status') field.className = `acc-st acc-st--${item.status}`;
        if (field.dataset.f === 'proxy') field.title = item.proxy || '';
        /* Числа на чипах зависят от статуса — пересчитываем их, а таблицу
           не трогаем, пока человек в ней работает. */
        renderAccFilters(accBaseRows());
        $('accList')._html = '';
        toast(t('accounts.sohraneno'), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
});

async function accDelete(id, btn) {
    btn.title = t('accounts.nazhmite_eshche_title');
    if (!armConfirm(btn, '')) {
        toast(t('accounts.nazhmite_eshche'));
        return;
    }
    const acc = ACC.items.find(a => a.id === id);
    try {
        await api(`/api/accounts/${id}`, {method: 'DELETE'});
        ACC.items = ACC.items.filter(a => a.id !== id);
        ACC.sel.delete(id);
        renderAccounts();
        toast(t('accounts.udalen', {login: acc ? acc.login : ''}));
    } catch (e) {
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
    const parts = sep ? line.split(sep).map(p => p.trim()) : [line];
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
        const row = accParseLine(line);
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
      <label class="bulk-row">${t('accounts.login')} <input id="accNewLogin" autocomplete="off"></label>
      <label class="bulk-row">${t('accounts.parol')} <input id="accNewPassword" type="password" autocomplete="new-password"></label>
      <label class="bulk-row">${t('accounts.proksi')} <input id="accNewProxy" placeholder="${t('accounts.proksi_neob')}"></label>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">${t('accounts.otmena')}</button>
      <button class="primary" onclick="accAddGo(this)">${t('accounts.dobavit')}</button>`;
    $('accNewPlatform').value = ACC.platform || 'vk';
    openModal();
    $('accNewLogin').focus();
}

async function accAddGo(btn) {
    const login = $('accNewLogin').value.trim();
    if (!login) return toast(t('accounts.vpishite_login'), 'bad');
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
        toast(e.message, 'bad');
    }
}

/* Раздать: каждому телефону без аккаунта этой платформы — свободный. */
async function accAutobind() {
    const platform = ACC.platform;
    if (!platform) return toast(t('accounts.snachala_platforma'), 'bad');
    /* Только видимые телефоны в сети: офлайн и скрытые — не в работе. */
    const serials = S.devices.filter(d => d.online && !S.hidden.has(d.serial)).map(d => d.serial);
    if (!serials.length) return toast(t('accounts.net_telefonov'), 'bad');
    try {
        const res = await post('/api/accounts/autobind', {platform, serials});
        toast(res.count ? t('accounts.razdano', {p: PLATFORM_NAMES[platform], n: res.count})
            : t('accounts.nekomu', {p: PLATFORM_NAMES[platform]}),
            res.count ? 'ok' : undefined);
        loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
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
        && document.activeElement.closest('#accList [data-f]')) return;
    accDevSig = sig;
    renderAccounts();
}, 2000);

window.loadAccounts = loadAccounts;
