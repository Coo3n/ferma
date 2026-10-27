'use strict';

/* «Помощник-нейросеть»: в шапке «Проблем» — одна кнопка-статус, настройки —
   в диалоге (меняют их раз в жизни, держать форму на экране незачем).
   Ключ с сервера приходит только маской: поле показывает её, а менять ключ —
   значит вписать новый. */

const VLM = {data: null};

/* Готовые модели: выбор подставляет имя в поле «Модель». Обе отдаёт LM Studio
   на одном адресе; AutoGLM ферма узнаёт по «autoglm» в имени и говорит с ней на её
   языке (do(action="Tap", …)). «Другая» — поле правится руками. */
function vlmPresets() {
    return [
        {id: 'qwen', model: 'qwen/qwen3-vl-30b',
            name: t('vlm.preset_qwen'), hint: t('vlm.preset_qwen_hint')},
        {id: 'autoglm', model: 'autoglm-phone-9b',
            name: t('vlm.preset_autoglm'), hint: t('vlm.preset_autoglm_hint')},
        {id: 'autoglm_ml', model: 'autoglm-phone-9b-multilingual',
            name: t('vlm.preset_autoglm_ml'), hint: t('vlm.preset_autoglm_ml_hint')},
        {id: 'other', model: null,
            name: t('vlm.preset_other'), hint: t('vlm.preset_other_hint')},
    ];
}

function vlmPresetOf(model) {
    const found = vlmPresets().find(p => p.model === model);
    return found || vlmPresets().find(p => p.id === 'other');
}

function vlmPick(id) {
    const p = vlmPresets().find(x => x.id === id);
    if (!p) return;
    if (p.model) $('vlmModel').value = p.model;
    setText($('vlmPresetHint'), p.hint);
}

async function vlmChipRefresh() {
    try {
        VLM.data = await api('/api/vlm');
    } catch (e) {
        return;   // кнопка просто остаётся как была: без сервера настройки ни к чему
    }
    vlmChipPaint();
}

function vlmChipPaint() {
    const d = VLM.data;
    const chip = $('vlmChip');
    if (!d || !chip) return;
    const on = d.enabled && d.configured;
    chip.dataset.on = on ? '1' : '0';
    setText($('vlmChipText'), on
        ? t('vlm.chip_vkl', {n: d.used_today, m: d.max_per_day}) : t('vlm.chip_vykl'));
}

async function vlmOpen() {
    try {
        VLM.data = await api('/api/vlm');
    } catch (e) {
        toast(t('vlm.ne_zagruzilos'), 'bad');
        return;
    }
    const d = VLM.data;
    const locked = (d.locked || []).length
        ? `<p class="vlm-note">${esc(t('vlm.ot_servera', {list: d.locked.join(', ')}))}</p>` : '';
    $('mTitle').textContent = t('vlm.zagolovok');
    $('mBody').innerHTML = `
      <div class="vlm-form">
        <p class="vlm-lead">${esc(t('vlm.opisanie'))}</p>
        <label class="vlm-switch">
          <input type="checkbox" id="vlmOn" ${d.enabled ? 'checked' : ''}>
          <span><b>${esc(t('vlm.vkl'))}</b><small>${esc(t('vlm.vkl_podpis'))}</small></span>
        </label>
        <div class="vlm-group">
          <h4>${esc(t('vlm.gruppa_kuda'))}</h4>
          <label>${esc(t('vlm.adres'))}<input id="vlmUrl" value="${esc(d.url)}" placeholder="http://127.0.0.1:1234/v1"></label>
          <label>${esc(t('vlm.preset'))}
            <select id="vlmPreset" onchange="vlmPick(this.value)">
              ${vlmPresets().map(p =>
                `<option value="${p.id}" ${p.id === vlmPresetOf(d.model).id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}
            </select>
          </label>
          <p class="vlm-calm" id="vlmPresetHint">${esc(vlmPresetOf(d.model).hint)}</p>
          <div class="vlm-two">
            <label>${esc(t('vlm.model'))}<input id="vlmModel" value="${esc(d.model)}" placeholder="qwen/qwen3-vl-30b"></label>
            <label>${esc(t('vlm.klyuch'))}<input id="vlmKey" type="password" value="${esc(d.key)}" autocomplete="off"></label>
          </div>
          <div class="vlm-status" id="vlmStatus" role="status" aria-live="polite"></div>
          <p class="vlm-warn">${esc(t('vlm.privatnost'))}</p>
          <p class="vlm-calm">${esc(t('vlm.bezopasno'))}</p>
        </div>
        <div class="vlm-group">
          <h4>${esc(t('vlm.gruppa_limity'))}</h4>
          <div class="vlm-two">
            <label>${esc(t('vlm.na_zadachu'))}<input id="vlmJob" type="number" min="0" max="50" value="${esc(d.max_per_job)}"></label>
            <label>${esc(t('vlm.v_sutki'))}<input id="vlmDay" type="number" min="0" value="${esc(d.max_per_day)}"></label>
          </div>
          <p class="vlm-calm">${esc(t('vlm.segodnya', {n: d.used_today, m: d.max_per_day}))}</p>
        </div>
        ${locked}
      </div>`;
    $('mActs').innerHTML = `
      <button onclick="closeModal()">${esc(t('vlm.zakryt'))}</button>
      <button id="vlmTestBtn" onclick="vlmTest()">${esc(t('vlm.proverit'))}</button>
      <button class="primary" id="vlmSaveBtn" onclick="vlmSave()">${esc(t('vlm.sohranit'))}</button>`;
    openModal();
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

function vlmStatus(text, ok) {
    const box = $('vlmStatus');
    if (!box) return;
    box.textContent = text;
    box.dataset.ok = ok === undefined ? '' : (ok ? '1' : '0');
    box.scrollIntoView({block: 'nearest'});
}

async function vlmSave() {
    const btn = $('vlmSaveBtn');
    btn.disabled = true;   // пока запрос не вернулся — второй раз не жмём
    try {
        VLM.data = await api('/api/vlm', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(vlmForm())});
        vlmChipPaint();
        closeModal();
        toast(t('vlm.sohraneno'));
    } catch (e) {
        vlmStatus(e.message, false);
        btn.disabled = false;
    }
}

async function vlmTest() {
    const btn = $('vlmTestBtn');
    btn.disabled = true;
    vlmStatus(t('vlm.proveryayu'));
    try {
        const r = await api('/api/vlm/test', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(vlmForm())});
        vlmStatus(r.ok ? t('vlm.svyaz_ok', {text: r.reply}) : t('vlm.svyaz_ploho', {text: r.error}), r.ok);
    } catch (e) {
        vlmStatus(e.message, false);
    }
    btn.disabled = false;
}
