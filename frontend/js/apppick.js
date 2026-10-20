'use strict';

/* Выбор приложения по названию. Людям незачем знать, что у VK пакет
   com.vkontakte.android: показываем «VK», а пакет оставляем в подсказке.
   Для редкого случая есть «Другое приложение…» — там можно вписать вручную. */

const APP_PICK = {byDevice: {}, cb: {}};
const APP_OTHER = '__other__';

/* [{package, label}] по телефону + приложения из библиотеки APK: шагу
   «Приложение готово» нужно выбрать и то, чего на телефоне ещё нет.
   Кэш на телефон: форма открывается часто. */
/* Подписи приложений без повторов — везде одним способом: выбор приложения
   в шаге, массовые действия, пульт. Настоящие имена бывают одинаковыми (у
   Яндекса несколько «Яндекс»): тогда дописываем слово из пакета. */
function appTail(pkg) {
    const parts = String(pkg).split('.').filter(p => p.length > 1 && !REC_PKG_NOISE.has(p.toLowerCase()));
    const w = parts[parts.length - 1] || String(pkg);
    return w[0].toUpperCase() + w.slice(1);
}

function appDistinct(list) {
    const count = {};
    list.forEach(a => { const k = a.label.toLowerCase(); count[k] = (count[k] || 0) + 1; });
    return list.map(a => count[a.label.toLowerCase()] > 1
        ? Object.assign({}, a, {label: `${a.label} · ${appTail(a.package)}`}) : a);
}

/* Настоящее имя, если его уже где-то узнали (пульт, выбор приложения). */
function appKnownLabel(pkg) {
    for (const map of Object.values((window.PULT && PULT.labels) || {})) if (map[pkg]) return map[pkg];
    for (const entry of Object.values(APP_PICK.byDevice)) {
        const hit = (entry.rows || []).find(a => a.package === pkg && a.real);
        if (hit) return hit.label;
    }
    return '';
}

function appLabel(pkg) {
    return appKnownLabel(pkg) || recApp(pkg).replace(/[«»]/g, '');
}

async function appChoices(serial) {
    let lib = [];
    try {
        lib = (await apkList()).map(a => ({package: a.package, label: a.name}));
    } catch (e) {
        lib = [];
    }
    if (!serial) return appDistinct(lib);
    const cached = APP_PICK.byDevice[serial];
    /* Сервер отдаёт названия, какие успел; остальные доберёт — неполный
       список через 5 с спрашиваем снова, а не держим «Yandex» навсегда. */
    if (!cached || (cached.partial && Date.now() - cached.at > 5000)) {
        let rows = [];
        try {
            rows = await api(`/api/devices/${serial}/apps`);
        } catch (e) {
            try {
                rows = (await api(`/api/devices/${serial}/packages`)).map(pkg => ({package: pkg}));
            } catch (e2) {
                rows = [];
            }
        }
        const mapped = rows.map(r => ({
            package: r.package,
            label: r.label || appLabel(r.package),
            real: !!r.label,
        }));
        if (!rows.length) return appDistinct(mergeApps(mapped, lib));   // сбой не запоминаем
        APP_PICK.byDevice[serial] = {rows: mapped, at: Date.now(), partial: mapped.some(a => !a.real)};
    }
    return appDistinct(mergeApps(APP_PICK.byDevice[serial].rows, lib));
}

function mergeApps(base, lib) {
    const list = base.slice();
    for (const a of lib) if (!list.some(x => x.package === a.package)) list.push(a);
    return list.sort((a, b) => (REC_APPS[a.package] ? 0 : 1) - (REC_APPS[b.package] ? 0 : 1)
        || a.label.localeCompare(b.label, 'ru'));
}

function appLabelOf(serial, pkg) {
    const hit = (((APP_PICK.byDevice[serial] || {}).rows) || []).find(a => a.package === pkg);
    return hit ? hit.label : appLabel(pkg);
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
        if (current && !known) rows.unshift({package: current, label: appLabel(current)});
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
    if (handler && (select.value !== APP_OTHER || typing)) handler(appPickValue(id), !!typing);
}
