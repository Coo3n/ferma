'use strict';

/* Панель «Помощник-нейросеть» (раздел проблем). Ключ с сервера приходит
   только маской: поле показывает её, а менять ключ — значит вписать новый. */

const VLM = {loaded: false, data: null};

async function vlmLoad() {
    const box = $('vlmBody');
    if (!box || !$('vlmPanel').open) return;
    try {
        VLM.data = await api('/api/vlm');
    } catch (e) {
        toast(t('vlm.ne_zagruzilos'), 'bad');
        return;
    }
    vlmRender();
}

function vlmRender() {
    const d = VLM.data;
    const locked = (d.locked || []).length
        ? `<p>${esc(t('vlm.ot_servera', {list: d.locked.join(', ')}))}</p>` : '';
    setHTML($('vlmBody'), `
      <p>${esc(t('vlm.opisanie'))}</p>
      <p class="vlm-priv">${esc(t('vlm.privatnost'))}</p>
      <label class="vlm-check"><input type="checkbox" id="vlmOn" ${d.enabled ? 'checked' : ''}>${esc(t('vlm.vkl'))}</label>
      <label>${esc(t('vlm.adres'))}<input id="vlmUrl" value="${esc(d.url)}" placeholder="http://192.168.1.50:8000/v1"></label>
      <label>${esc(t('vlm.model'))}<input id="vlmModel" value="${esc(d.model)}" placeholder="AutoGLM-Phone-9B"></label>
      <label>${esc(t('vlm.klyuch'))}<input id="vlmKey" type="password" value="${esc(d.key)}" autocomplete="off"></label>
      <label>${esc(t('vlm.na_zadachu'))}<input id="vlmJob" type="number" min="0" max="50" value="${esc(d.max_per_job)}"></label>
      <label>${esc(t('vlm.v_sutki'))}<input id="vlmDay" type="number" min="0" value="${esc(d.max_per_day)}"></label>
      ${locked}
      <div class="vlm-row">
        <button class="sm primary" onclick="vlmSave()">${esc(t('vlm.sohranit'))}</button>
        <button class="sm" onclick="vlmTest()">${esc(t('vlm.proverit'))}</button>
        <span class="vlm-count">${esc(t('vlm.segodnya', {n: d.used_today, m: d.max_per_day}))}</span>
      </div>`);
}

function vlmForm() {
    return {
        enabled: $('vlmOn').checked,
        url: $('vlmUrl').value,
        model: $('vlmModel').value,
        key: $('vlmKey').value,
        max_per_job: Number($('vlmJob').value),
        max_per_day: Number($('vlmDay').value),
    };
}

async function vlmSave() {
    try {
        VLM.data = await api('/api/vlm', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(vlmForm())});
        toast(t('vlm.sohraneno'));
        vlmRender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

async function vlmTest() {
    try {
        const r = await api('/api/vlm/test', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(vlmForm())});
        toast(r.ok ? t('vlm.svyaz_ok', {text: r.reply}) : t('vlm.svyaz_ploho', {text: r.error}), r.ok ? undefined : 'bad');
    } catch (e) {
        toast(e.message, 'bad');
    }
}
