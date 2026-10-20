'use strict';

/* Библиотека APK: приложения, которые сценарий ставит сам (шаг «Приложение
   готово»). Одно приложение — один файл: новый APK того же приложения
   заменяет старый, и сценарии сразу ставят новую версию. */

const APK_LIB = {list: null, busy: false};

async function apkList(force) {
    if (APK_LIB.list && !force) return APK_LIB.list;
    APK_LIB.list = await api('/api/apks');
    return APK_LIB.list;
}

function apkShow() {
    apkRender();
    apkList(true).then(apkRender).catch(e => toast(e.message, 'bad'));
}

function apkSize(bytes) {
    return t('apk.mb', {n: Math.max(1, Math.round((bytes || 0) / 1048576))});
}

/* Что делает раздел — тремя шагами: «Добавьте APK» в пустом экране не
   объясняло, зачем он нужен. Зона перетаскивания — сразу здесь. */
function apkHowHtml() {
    const step = (n, icon, title, text) => `<li><span class="apk-how-n">${n}</span>
        <svg class="ic" aria-hidden="true"><use href="#i-${icon}"/></svg><b>${esc(title)}</b><span>${esc(text)}</span></li>`;
    return `<ol class="apk-how">
        ${step(1, 'upload', t('apk.how1_t'), t('apk.how1'))}
        ${step(2, 'check-square', t('apk.how2_t'), t('apk.how2'))}
        ${step(3, 'refresh', t('apk.how3_t'), t('apk.how3'))}
      </ol>`;
}

function apkDropHtml(big) {
    return `<button type="button" class="apk-drop ${big ? 'big' : ''}" onclick="apkPick()">
        <svg class="ic" aria-hidden="true"><use href="#i-upload"/></svg>
        <span><b>${esc(t('apk.drop_t'))}</b> ${esc(t('apk.drop'))}</span></button>`;
}

function apkRender() {
    const box = $('apkList');
    if (!box) return;
    const list = APK_LIB.list;
    document.querySelectorAll('[data-count="apps"]').forEach(el => setText(el, list && list.length ? String(list.length) : ''));
    if (!list) return;
    if (!list.length) {
        box.innerHTML = `<div class="apk-empty"><h3>${esc(t('apk.pusto'))}</h3>
            <p>${esc(t('apk.pusto_d'))}</p>${apkHowHtml()}${apkDropHtml(true)}</div>`;
        return;
    }
    const avatar = a => window.pultAvatar ? pultAvatar(a.name, a.package) : '';
    box.innerHTML = `<div class="apk-wrap"><div class="apk-list">${list.map(a => `
      <div class="apk-row">
        <span class="apk-av">${avatar(a)}</span>
        <div class="apk-main">
          <b>${esc(a.name)}</b>
          <span title="${esc(a.package)}">${esc(t('apk.versiya', {v: a.version_name || a.version_code}))}
            · ${esc(apkSize(a.size))}${a.used ? ' · ' + esc(t('apk.v_stsenariyah', {n: a.used})) : ''}</span>
        </div>
        <span class="apk-acts">
          <button class="sm ghost" onclick="apkRename('${esc(a.package)}')">${esc(t('apk.pereimenovat'))}</button>
          <button class="sm ghost" onclick="apkPick()">${esc(t('apk.zamenit'))}</button>
          <button class="sm ghost danger" onclick="apkRemove(this, '${esc(a.package)}')"><span>${esc(t('apk.udalit'))}</span></button>
        </span>
      </div>`).join('')}</div>${apkDropHtml(false)}</div>`;
}

function apkPick() {
    if (APK_LIB.busy) return toast(t('apk.uzhe_gruzim'), 'bad');
    $('apkFile').click();
}

function apkDrop(ev) {
    ev.preventDefault();
    const file = [...((ev.dataTransfer && ev.dataTransfer.files) || [])].find(f => /\.apk$/i.test(f.name));
    if (!file) return toast(t('apk.tolko_apk'), 'bad');
    apkUpload(file);
}

async function apkUpload(file) {
    if (!file) return;
    if (APK_LIB.busy) return toast(t('apk.uzhe_gruzim'), 'bad');
    APK_LIB.busy = true;
    const btn = $('btnApkAdd');
    disableWithReason(btn, true, t('apk.gruzim'));
    try {
        const res = await api('/api/apks?name=' + encodeURIComponent(file.name), {method: 'POST', body: file});
        const words = {name: res.name, v: res.version_name};
        toast(res.replaced ? t('apk.zamenen', words) : t('apk.dobavlen', words), 'ok');
        await apkList(true);
        apkRender();
    } catch (e) {
        toast(e.message, 'bad');
    } finally {
        APK_LIB.busy = false;
        disableWithReason(btn, false);
    }
}

function apkRename(pkg) {
    const a = (APK_LIB.list || []).find(x => x.package === pkg);
    promptModal(t('apk.nazvanie_title'), t('apk.nazvanie'), a ? a.name : '', t('apk.sohranit'), async name => {
        if (!name) return;
        try {
            await api('/api/apks/' + encodeURIComponent(pkg), {
                method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name}),
            });
            apkShow();
        } catch (e) {
            toast(e.message, 'bad');
        }
    });
}

async function apkRemove(btn, pkg) {
    const a = (APK_LIB.list || []).find(x => x.package === pkg);
    if (!armConfirm(btn, a && a.used ? t('apk.udalit_used', {n: a.used}) : t('apk.udalit_tochno'))) return;
    try {
        await api('/api/apks/' + encodeURIComponent(pkg), {method: 'DELETE'});
        toast(t('apk.udaleno', {name: a ? a.name : pkg}), 'ok');
        apkShow();
    } catch (e) {
        toast(e.message, 'bad');
    }
}
