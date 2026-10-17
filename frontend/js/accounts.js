/* Аккаунты: таблица с правкой на месте.

   Любое поле меняется прямо в строке и сохраняется при уходе с поля —
   без отдельной формы «редактировать». Сценарий берёт аккаунт своего
   телефона через ctx.account("vk"), поэтому главное здесь — колонка
   «Телефон». */

const ACC = window.ACC = {items: [], platform: '', query: ''};

function accPlatformOptions() {
    return Object.entries(PLATFORM_NAMES)
        .map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
}

const ACC_STATUS = {
    new: 'новый',
    active: 'работает',
    login: 'нужен вход',
    banned: 'бан',
};

async function loadAccounts() {
    try {
        ACC.items = await api('/api/accounts');
    } catch (e) {
        return toast(e.message, 'bad');
    }
    renderAccounts();
}

function accPlatforms() {
    return Object.keys(PLATFORM_NAMES).filter(p => ACC.items.some(a => a.platform === p));
}

function accDeviceName(serial) {
    const d = S.devices.find(x => x.serial === serial);
    return d ? d.name : serial;
}

function renderAccounts() {
    disableWithReason($('btnAccAutobind'), !ACC.platform, 'Сначала выберите платформу в фильтре');
    const sel = $('accPlatform');
    if (!sel.options.length) {
        sel.innerHTML = '<option value="">Все платформы</option>' + accPlatformOptions();
    }
    sel.value = ACC.platform;

    const q = ACC.query;
    const rows = ACC.items.filter(a =>
        (!ACC.platform || a.platform === ACC.platform)
        && (!q || [a.login, a.phone, a.note, accDeviceName(a.serial)]
            .some(v => (v || '').toLowerCase().includes(q))));

    const free = ACC.items.filter(a => !a.serial && a.status !== 'banned').length;
    setText($('accSummary'), ACC.items.length
        ? `${ACC.items.length} всего · ${free} свободно` : '');

    const box = $('accList');
    if (!ACC.items.length) {
        box.innerHTML = emptyBig({
            art: 'scenario',
            title: 'Аккаунтов пока нет',
            text: 'Вставьте «логин:пароль» по строке и раздайте телефонам.',
            action: {label: 'Вставить списком', icon: 'copy', onClick: 'accImport()'},
        });
        return;
    }

    /* Телефон — кнопка с одним общим выбором, а не select в каждой строке:
       на 500 аккаунтах × 100 телефонов это было 50 000 пунктов в DOM.
       Пароль не приходит с сервера целиком — только «задан / не задан»;
       показать — по явной кнопке. */
    box.innerHTML = `<table class="acc-table">
      <thead><tr><th>Платформа</th><th>Логин</th><th>Пароль</th><th>Прокси</th>
        <th>Телефон</th><th>Статус</th><th>Заметка</th><th></th></tr></thead>
      <tbody>${rows.map(a => `<tr data-id="${a.id}">
        <td><select data-f="platform" aria-label="Платформа">${accPlatformOptions()
            .replace(`value="${a.platform}"`, `value="${a.platform}" selected`)}</select></td>
        <td><input data-f="login" value="${esc(a.login)}" aria-label="Логин"></td>
        <td class="acc-pw"><input data-f="password" type="password" aria-label="Пароль"
                   placeholder="${a.has_password ? '••••••' : 'не задан'}" autocomplete="off">
            ${a.has_password ? `<button class="sm ghost" title="Показать пароль" aria-label="Показать пароль"
                onclick="accShowPw('${a.id}', this)"><svg class="ic"><use href="#i-eye-off"/></svg></button>` : ''}</td>
        <td><input data-f="proxy" value="${esc(a.proxy)}" placeholder="—" aria-label="Прокси"></td>
        <td><button class="sm acc-phone" onclick="accPickPhone('${a.id}')"
                    aria-label="Телефон: ${esc(a.serial ? accDeviceName(a.serial) : 'не привязан')}">
            ${a.serial ? esc(accDeviceName(a.serial)) + (S.devices.some(d => d.serial === a.serial) ? '' : ' <small>(нет в ферме)</small>')
                : '<span class="dim">не привязан</span>'}</button></td>
        <td><select data-f="status" aria-label="Статус" class="acc-st acc-st--${a.status}">${Object.entries(ACC_STATUS)
            .map(([k, v]) => `<option value="${k}"${k === a.status ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
        <td><input data-f="note" value="${esc(a.note)}" placeholder="—" aria-label="Заметка"></td>
        <td><button class="sm danger" title="Удалить аккаунт" aria-label="Удалить аккаунт"
                    onclick="accDelete('${a.id}', this)"><svg class="ic"><use href="#i-trash"/></svg></button></td>
      </tr>`).join('')}</tbody></table>`;
}

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

/* Привязка к телефону — общий выбор телефона (devices.js), плюс «отвязать». */
function accPickPhone(id) {
    const item = ACC.items.find(a => a.id === id);
    $('mTitle').textContent = `Телефон для ${item.login}`;
    $('mBody').innerHTML = `<div class="phone-pick">
      <button onclick="closeModal();accBind('${id}', '')"><span class="dot"></span><b>Не привязан</b><span>отвязать</span></button>
      ${S.devices.filter(d => !S.hidden.has(d.serial)).map(d => `
      <button onclick="closeModal();accBind('${id}', '${esc(d.serial)}')">
        <span class="dot ${d.online ? 'on' : ''}"></span><b>${esc(d.name)}</b>
        <span>${esc([d.group, (d.accounts || []).some(x => x.platform === item.platform) ? 'уже есть ' + PLATFORM_NAMES[item.platform] : '']
            .filter(Boolean).join(' · '))}</span></button>`).join('')}</div>`;
    $('mActs').innerHTML = '<button onclick="closeModal()">Отмена</button>';
    openModal();
}

async function accBind(id, serial) {
    try {
        const item = await api(`/api/accounts/${id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial}),
        });
        Object.assign(ACC.items.find(a => a.id === id), item);
        renderAccounts();
        toast(serial ? 'привязано' : 'отвязано', 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Одно сохранение на изменённое поле: change срабатывает при уходе с поля,
   а не на каждую букву. */
document.addEventListener('change', async ev => {
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
        toast('сохранено', 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
});

async function accDelete(id, btn) {
    btn.title = 'Нажмите ещё раз — аккаунт удалится';
    if (!armConfirm(btn, '')) return;
    try {
        await api(`/api/accounts/${id}`, {method: 'DELETE'});
        ACC.items = ACC.items.filter(a => a.id !== id);
        renderAccounts();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function accFilter() {
    ACC.platform = $('accPlatform').value;
    disableWithReason($('btnAccAutobind'), !ACC.platform, 'Сначала выберите платформу в фильтре');
    ACC.query = $('accSearch').value.trim().toLowerCase();
    renderAccounts();
}

function accImport() {
    $('mTitle').textContent = 'Добавить аккаунты списком';
    $('mBody').innerHTML = `
    <label class="bulk-row">Платформа
      <select id="accImpPlatform">${accPlatformOptions()}</select></label>
    <label class="bulk-row">По строке на аккаунт
      <div class="fmt-ex">
        <span class="fmt"><b>логин</b><i>:</i><b>пароль</b></span>
        <span>или</span>
        <span class="fmt"><b>логин</b><i>:</i><b>пароль</b><i>:</i><b class="opt">прокси</b></span>
      </div>
      <textarea id="accImpText" rows="8" placeholder="79001234567:secret&#10;user@mail.ru:pass:1.2.3.4:8080"></textarea></label>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">Отмена</button>
      <button class="primary" onclick="accImportGo()">Добавить</button>`;
    $('accImpPlatform').value = ACC.platform || 'vk';
    openModal();
}

async function accImportGo() {
    try {
        const res = await post('/api/accounts/import', {
            text: $('accImpText').value, platform: $('accImpPlatform').value,
        });
        toast(`добавлено аккаунтов: ${res.count}`, 'ok');
        closeModal();
        loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Сначала форма, потом запись на сервер: раньше «Добавить» сразу
   создавал аккаунт «новый», и отказ оставлял мусор. */
function accAdd() {
    $('mTitle').textContent = 'Новый аккаунт';
    $('mBody').innerHTML = `
      <label class="bulk-row">Платформа <select id="accNewPlatform">${accPlatformOptions()}</select></label>
      <label class="bulk-row">Логин <input id="accNewLogin" autocomplete="off"></label>
      <label class="bulk-row">Пароль <input id="accNewPassword" type="password" autocomplete="new-password"></label>
      <label class="bulk-row">Прокси <input id="accNewProxy" placeholder="необязательно, 1.2.3.4:8080"></label>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">Отмена</button>
      <button class="primary" onclick="accAddGo()">Добавить</button>`;
    $('accNewPlatform').value = ACC.platform || 'vk';
    openModal();
    $('accNewLogin').focus();
}

async function accAddGo() {
    const login = $('accNewLogin').value.trim();
    if (!login) return toast('впишите логин', 'bad');
    try {
        await post('/api/accounts', {
            platform: $('accNewPlatform').value, login,
            password: $('accNewPassword').value, proxy: $('accNewProxy').value,
        });
        closeModal();
        toast('аккаунт добавлен', 'ok');
        loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Раздать: каждому телефону без аккаунта этой платформы — свободный. */
async function accAutobind() {
    const platform = ACC.platform;
    if (!platform) return toast('сначала выберите платформу в фильтре', 'bad');
    /* Только видимые телефоны в сети: офлайн и скрытые — не в работе. */
    const serials = S.devices.filter(d => d.online && !S.hidden.has(d.serial)).map(d => d.serial);
    if (!serials.length) return toast('нет телефонов в сети', 'bad');
    try {
        const res = await post('/api/accounts/autobind', {platform, serials});
        toast(res.count ? `${PLATFORM_NAMES[platform]}: привязано ${res.count}`
            : `${PLATFORM_NAMES[platform]}: некому раздавать`,
            res.count ? 'ok' : undefined);
        loadAccounts();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

window.loadAccounts = loadAccounts;
