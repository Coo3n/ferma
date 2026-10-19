'use strict';

/* Выбор приложения по названию. Людям незачем знать, что у VK пакет
   com.vkontakte.android: показываем «VK», а пакет оставляем в подсказке.
   Для редкого случая есть «Другое приложение…» — там можно вписать вручную. */

const APP_PICK = {byDevice: {}, cb: {}};
const APP_OTHER = '__other__';

/* [{package, label}] по телефону: названия с телефона, а где их нет — по
   имени пакета. Кэш на телефон: форма открывается часто. */
async function appChoices(serial) {
    if (!serial) return [];
    if (APP_PICK.byDevice[serial]) return APP_PICK.byDevice[serial];
    let rows = [];
    try {
        rows = await api(`/api/devices/${serial}/apps`);
    } catch (e) {
        try {
            rows = (await api(`/api/devices/${serial}/packages`)).map(pkg => ({package: pkg}));
        } catch (e2) {
            return [];
        }
    }
    const list = rows.map(r => ({
        package: r.package,
        label: r.label || recApp(r.package).replace(/[«»]/g, ''),
    })).sort((a, b) => (REC_APPS[a.package] ? 0 : 1) - (REC_APPS[b.package] ? 0 : 1)
        || a.label.localeCompare(b.label, 'ru'));
    APP_PICK.byDevice[serial] = list;
    return list;
}

function appLabelOf(serial, pkg) {
    const hit = ((APP_PICK.byDevice[serial] || []).find(a => a.package === pkg));
    return hit ? hit.label : recApp(pkg).replace(/[«»]/g, '');
}

/* Разметка: список приложений + поле «другое», пока скрытое. Заполняется
   appPickFill(id) — список приходит с телефона не сразу. */
function appPickHtml(id, value, onchange) {
    APP_PICK.cb[id] = onchange || null;
    return `<span class="apppick grow" id="${esc(id)}" data-value="${esc(value || '')}">
      <select class="grow" aria-label="${esc(t('app.prilozhenie'))}" onchange="appPickChanged('${esc(id)}')"></select>
      <input type="text" class="grow" hidden placeholder="${esc(t('app.kod_prilozheniya'))}"
             aria-label="${esc(t('app.kod_prilozheniya'))}" oninput="appPickChanged('${esc(id)}', true)">
    </span>`;
}

async function appPickFill(id) {
    const box = $(id);
    if (!box) return;
    const select = box.querySelector('select');
    const current = box.dataset.value || '';
    const draw = list => {
        const known = list.some(a => a.package === current);
        const rows = list.slice();
        if (current && !known) rows.unshift({package: current, label: recApp(current).replace(/[«»]/g, '')});
        select.innerHTML = (current ? '' : `<option value="" disabled selected>${esc(t('app.vyberite'))}</option>`)
            + rows.map(a => `<option value="${esc(a.package)}" title="${esc(a.package)}"
                ${a.package === current ? 'selected' : ''}>${esc(a.label)}</option>`).join('')
            + `<option value="${APP_OTHER}">${esc(t('app.drugoe'))}</option>`;
    };
    draw([]);
    draw(await appChoices(S.active));
}

function appPickValue(id) {
    const box = $(id);
    if (!box) return '';
    const select = box.querySelector('select');
    const input = box.querySelector('input');
    return select.value === APP_OTHER ? input.value.trim() : select.value;
}

function appPickChanged(id, typing) {
    const box = $(id);
    const select = box.querySelector('select');
    const input = box.querySelector('input');
    input.hidden = select.value !== APP_OTHER;
    if (!typing && !input.hidden) input.focus();
    const handler = APP_PICK.cb[id];
    if (handler && (select.value !== APP_OTHER || typing)) handler(appPickValue(id));
}
