'use strict';

/* Галерея готовых сюжетов: вкладка раздела «Сценарии». Карточка показывает,
   проверен ли сюжет на телефоне; «Добавить в мои» копирует файл в «Мои». */

const GALLERY = {list: null};

async function galleryShow() {
    galleryRender();
    try {
        GALLERY.list = await api('/api/gallery');
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    galleryRender();
}

function galleryCard(item) {
    const badge = item.verified ? '' :
        `<span class="gal-badge" title="${esc(t('gallery.ne_proveren_d'))}">${esc(t('gallery.ne_proveren'))}</span>`;
    const action = item.added
        ? `<span class="gal-done">${esc(t('gallery.uzhe_v_moih'))}</span>`
        : `<button class="sm accent" onclick="galleryAdd('${esc(item.key)}')">${esc(t('gallery.dobavit'))}</button>`;
    return `<article class="gal-card">
        <header><b>${esc(item.name)}</b><span class="gal-plat">${esc(item.platform)}</span></header>
        <p>${esc(item.description)}</p>
        <footer>${badge}<span class="sp"></span>${action}</footer>
      </article>`;
}

function galleryRender() {
    const box = $('galList');
    if (!box) return;
    const list = GALLERY.list;
    if (!list) return;
    if (!list.length) {
        box.innerHTML = `<div class="apk-empty"><h3>${esc(t('gallery.pusto'))}</h3><p>${esc(t('gallery.pusto_d'))}</p></div>`;
        return;
    }
    box.innerHTML = `<div class="gal-grid">${list.map(galleryCard).join('')}</div>`;
}

async function galleryAdd(key) {
    try {
        await api(`/api/gallery/${encodeURIComponent(key)}/add`, {method: 'POST'});
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    toast(t('gallery.dobavlen'), 'ok');
    await loadScenarios(true);
    GALLERY.list = await api('/api/gallery');
    galleryRender();
}
