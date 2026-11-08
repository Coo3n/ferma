/* Окно «Подключить нейросеть»: плитки провайдеров вместо двух карточек.
   Грузится ПОСЛЕ ai-wizard.js и подменяет aiSetPaint / aiServerCard (присваиванием в window,
   поэтому вызовы внутри ai-wizard.js попадают сюда) и оборачивает aiSetClick.
   Локальная Ollama остаётся прежней: aiLocalCard и её действия не менялись.
   Ключ в браузер не приходит (только маска) и уходит лишь вместе с формой подключения. */

const AP = {list: null, loading: false, err: '', sel: null, changing: false, key: '', model: '', url: '',
    region: '', models: null, mErr: '', mseq: 0, busy: false, status: null};

const AP_NAMES = {
    openai: ['OpenAI', 'ChatGPT'], claude: ['Claude', 'Anthropic'], gemini: ['Gemini', 'Google'],
    qwen: ['Qwen', 'Alibaba'], glm: ['GLM', 'Zhipu'], kimi: ['Kimi', 'Moonshot'], deepseek: ['DeepSeek', 'DeepSeek'],
    local: ['Этот компьютер', 'Ollama'], custom: ['Свой сервер', 'LM Studio, vLLM'],
};
const AP_ICON = {
    local: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    custom: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="6" rx="1.5"/><rect x="4" y="14" width="16" height="6" rx="1.5"/><path d="M8 7h.01M8 17h.01"/></svg>',
};
const AP_MONO = {openai: 'Ai', claude: 'Cl', gemini: 'Ge', qwen: 'Qw', glm: 'GL', kimi: 'Ki', deepseek: 'DS'};
const AP_OLLAMA = /^https?:\/\/(127\.0\.0\.1|localhost):11434\b/;
const apNorm = u => String(u || '').trim().replace(/\/+$/, '');

function apPreset(id) { return (AP.list || []).find(p => p.id === id) || null; }

/* Какой плитке соответствует сохранённый адрес. */
function apProvOf(d) {
    if (!d || !d.url) return null;
    const u = apNorm(d.url);
    if (AP_OLLAMA.test(u)) return {id: 'local'};
    for (const p of AP.list || []) {
        if (apNorm(p.base_url) === u) return {id: p.id};
        const r = (p.regions || []).find(x => apNorm(x.base_url) === u);
        if (r) return {id: p.id, region: r.id};
    }
    return {id: 'custom'};
}

function apHuman(t) {
    t = String(t || '');
    if (/\b40[13]\b/.test(t)) return 'Неверный ключ';
    if (/\b404\b/.test(t)) return 'Модель не найдена';
    if (/\b429\b/.test(t)) return 'Лимит запросов или не хватает средств на счёте';
    if (/\b400\b/.test(t)) return 'Запрос отклонён — проверьте модель';
    if (/недоступна|никто не отвечает|адреса нет|такого адреса|не дождались|не достать/.test(t))
        return 'Нет соединения — ' + t.replace(/^нейросеть недоступна:\s*/, '');
    return t || 'Не получилось подключиться';
}

/* Строка итога по реальной пробе: про картинки — только то, что показала проба. */
function apProbeStatus(r) {
    if (!r || !r.reachable || !r.text_ok)
        return {kind: 'bad', text: apHuman(r && r.detail) || 'Не получилось подключиться'};
    const tail = r.vision === 'yes' ? 'понимает картинки' : r.vision === 'no' ? 'только текст' : 'картинки не удалось проверить';
    return {kind: r.vision === 'yes' ? 'ok' : 'warn', text: 'Подключено · ' + tail};
}

async function apLoad() {
    AP.loading = true;
    try {
        AP.list = (await aiGet('/providers')).providers || [];
        AP.err = '';
    } catch (e) {
        AP.list = null;
        AP.err = e.message;
    }
    AP.loading = false;
    aiSetPaint();
}

function apUrl() {
    if (AP.sel === 'custom') return AP.url.trim();
    const p = apPreset(AP.sel);
    if (!p) return '';
    const r = (p.regions || []).find(x => x.id === AP.region);
    return r ? r.base_url : p.base_url;
}

const apSavedKey = (d, url) => !!(d && d.key && apNorm(d.url) === apNorm(url));

async function apFetchModels() {
    const url = apUrl();
    if (!url) return;
    const tok = ++AP.mseq;
    AP.mErr = '';
    const body = {url};
    if (AP.key) body.key = AP.key;
    try {
        const r = await aiPost('/models', body);
        if (tok !== AP.mseq) return;
        AP.models = (r.models || []).map(m => m.id);
        AP.mErr = r.error ? (/\b40[13]\b/.test(r.error) ? 'Неверный ключ' : 'Список моделей не получен — введите название вручную') : '';
        if (!AP.model && AP.models.length) AP.model = AP.models[0];
    } catch (e) {
        if (tok !== AP.mseq) return;
        AP.models = null;
        AP.mErr = 'Список моделей не получен — введите название вручную';
    }
    aiSetPaint();
}

function apPick(id) {
    const d = W.set;
    const was = apProvOf(d);
    AP.sel = id; AP.changing = true; AP.key = ''; AP.model = ''; AP.models = null; AP.mErr = ''; AP.status = null;
    AP.region = ''; AP.url = '';
    const p = apPreset(id);
    if (p && p.regions) AP.region = was && was.id === id && was.region ? was.region : p.regions[0].id;
    if (was && was.id === id && d) {
        AP.model = d.model || '';
        if (id === 'custom') AP.url = d.url || '';
    }
    aiSetPaint();
    if (id !== 'local' && was && was.id === id && apSavedKey(d, apUrl())) apFetchModels();
}

async function apConnect() {
    const d = W.set || {};
    const url = apUrl(), model = AP.model.trim(), cloud = AP.sel !== 'custom';
    if (!url) AP.status = {kind: 'bad', text: 'Укажите адрес сервера'};
    else if (cloud && !AP.key && !apSavedKey(d, url)) AP.status = {kind: 'bad', text: 'Вставьте ключ'};
    else if (!model) AP.status = {kind: 'bad', text: 'Выберите или введите модель'};
    else AP.status = null;
    if (AP.status) return aiSetPaint();
    AP.busy = true; AP.status = {kind: '', text: 'Проверяю связь и картинки…'};
    aiSetPaint();
    try {
        const body = {enabled: true, url, model, max_per_job: d.max_per_job, max_per_day: d.max_per_day};
        if (AP.key) body.key = AP.key;
        await api('/api/vlm', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        const r = await aiPost('/probe', {url, model});
        AP.status = apProbeStatus(r);
        W.probe = r;
        AP.busy = false;
        await aiSetLoad();
        if (AP.status.kind !== 'bad') { AP.sel = null; AP.changing = false; AP.key = ''; }
    } catch (e) {
        AP.busy = false;
        AP.status = {kind: 'bad', text: apHuman(e.message)};
    }
    aiSetPaint();
}

/* ------------------------------------------------------------------- разметка */

function apChip(d) {
    const pv = apProvOf(d);
    const nm = pv ? (AP_NAMES[pv.id] || [pv.id])[0] : '';
    const v = d.vision === 'yes' ? 'понимает картинки' : d.vision === 'no' ? 'только текст' : 'картинки не проверены';
    return `<div class="ap-now"><span class="ap-dot" data-kind="${d.vision === 'yes' ? 'ok' : 'warn'}" aria-hidden="true"></span>
      <div class="ap-nowtxt"><span><b>${esc(nm)}</b>${d.model ? ' · ' + esc(d.model) : ''}</span><small>${v}</small></div>
      <button class="sm" data-pact="change" aria-expanded="${AP.changing ? 'true' : 'false'}">Сменить</button></div>`;
}

function apTiles() {
    const ids = [...(AP.list || []).map(p => p.id), 'local', 'custom'];
    return `<div class="ap-tiles" role="group" aria-label="Нейросеть">${ids.map(id => {
        const n = AP_NAMES[id] || [id, ''];
        const ico = AP_ICON[id] || `<span>${esc(AP_MONO[id] || n[0].slice(0, 2))}</span>`;
        return `<button class="ap-tile" data-pact="pick" data-id="${esc(id)}" aria-pressed="${AP.sel === id}">
          <i class="ap-ico">${ico}</i><b>${esc(n[0])}</b><small>${esc(n[1])}</small></button>`;
    }).join('')}</div>`;
}

function apPanel(d) {
    const id = AP.sel, custom = id === 'custom';
    const p = apPreset(id) || {};
    const url = apUrl();
    const saved = apSavedKey(d, url);
    const st = AP.status;
    const hints = AP.models && AP.models.length ? [] : (p.models_hint || []).filter(m => m !== AP.model);
    const ms = AP.models || [];
    const other = !ms.includes(AP.model) && (AP.model || !ms.length);
    const modelCtl = ms.length
        ? `<select id="apModel" aria-label="Модель">${ms.map(m => `<option value="${esc(m)}"${m === AP.model ? ' selected' : ''}>${esc(m)}</option>`).join('')}
            <option value="__other"${other ? ' selected' : ''}>Другая…</option></select>
          ${other ? `<input id="apModelTxt" value="${esc(AP.model)}" placeholder="название модели" autocomplete="off" aria-label="Название модели">` : ''}`
        : `<input id="apModelTxt" value="${esc(AP.model)}" placeholder="название модели" autocomplete="off" aria-label="Название модели">`;
    return `<div class="ap-panel">
      <h3>${esc((AP_NAMES[id] || [id])[0])}</h3>
      ${custom ? `<label>Адрес<input id="apUrl" value="${esc(AP.url)}" placeholder="http://127.0.0.1:1234/v1" autocomplete="off"></label>` : ''}
      ${p.regions ? `<label>Регион<select id="apRegion">${p.regions.map(r => `<option value="${esc(r.id)}"${r.id === AP.region ? ' selected' : ''}>${esc(r.title)}</option>`).join('')}</select></label>` : ''}
      <label><span class="ap-lbl">Ключ${custom ? ' (если нужен)' : ''}${!custom && p.key_url ? `<a class="ai-link" href="${esc(p.key_url)}" target="_blank" rel="noopener">Где взять ключ</a>` : ''}</span>
        <input id="apKey" type="password" value="${esc(AP.key)}" autocomplete="off" placeholder="${saved ? 'ключ сохранён — менять не нужно' : custom ? 'для локальных не нужен' : 'вставьте ключ'}"></label>
      <div class="ap-field"><span class="ap-lbl">Модель</span>${modelCtl}
        ${AP.mErr ? `<p class="ai-note" data-kind="warn">${esc(AP.mErr)}</p>` : ''}
        ${hints.length ? `<div class="ap-hints">${hints.map(m => `<button class="sm" data-pact="hint" data-m="${esc(m)}">${esc(m)}</button>`).join('')}</div>` : ''}</div>
      ${p.note ? `<p class="ai-note">${esc(p.note)}</p>` : ''}
      <button class="primary" data-pact="connect"${AP.busy ? ' disabled' : ''}>Подключить</button>
      ${st ? `<p class="ai-msg" data-kind="${st.kind}" role="status">${esc(st.text)}</p>` : ''}
      <p class="ai-dim">${custom ? 'Шаги и скриншоты уходят на этот сервер' : 'Шаги и скриншоты уходят к провайдеру'}</p></div>`;
}

window.aiServerCard = function (d) {
    if (!d) return `${aiErr(W.setErr || 'Настройки не загрузились')}<button data-sact="reload">Повторить</button>`;
    if (AP.list === null) return AP.err
        ? `${aiErr(AP.err)}<button data-pact="reload">Повторить</button>` : '<p class="ai-note">Загружаю…</p>';
    const connected = !!(d.enabled && d.url);
    const show = !connected || AP.changing;
    const done = !AP.sel && AP.status && AP.status.kind !== 'bad' ? `<p class="ai-msg" data-kind="${AP.status.kind}" role="status">${esc(AP.status.text)}</p>` : '';
    return `${connected ? apChip(d) : ''}${connected ? done : ''}
      ${show ? apTiles() : ''}
      ${show && AP.sel && AP.sel !== 'local' ? apPanel(d) : ''}
      ${show && AP.sel === 'local' ? `<section class="ai-card ap-local" aria-label="Локальная модель">${aiLocalCard()}</section>` : ''}`;
};

window.aiSetPaint = function () {
    if (!aiSetAlive()) return;
    if (AP.list === null && !AP.loading && !AP.err) apLoad();
    const box = $('aiSet');
    if ($('mTitle')) $('mTitle').textContent = 'Подключить нейросеть';
    box.innerHTML = `<div class="ap">${aiServerCard(W.set)}</div>`;
    box.querySelectorAll('[data-sact]').forEach(b => b.addEventListener('click', aiSetClick));
    box.querySelectorAll('[data-pact]').forEach(b => b.addEventListener('click', apClick));
    const k = $('apKey'), m = $('apModel'), t = $('apModelTxt'), u = $('apUrl'), r = $('apRegion');
    if (k) {
        k.addEventListener('input', () => { AP.key = k.value; });
        k.addEventListener('change', () => { AP.key = k.value.trim(); if (AP.key) apFetchModels(); });
    }
    if (u) {
        u.addEventListener('input', () => { AP.url = u.value; });
        u.addEventListener('change', () => { AP.models = null; AP.mErr = ''; if (AP.url.trim()) apFetchModels(); });
    }
    if (t) t.addEventListener('input', () => { AP.model = t.value; });
    if (m) m.addEventListener('change', () => {
        AP.model = m.value === '__other' ? '' : m.value;
        aiSetPaint();
        if (m.value === '__other' && $('apModelTxt')) $('apModelTxt').focus();
    });
    if (r) r.addEventListener('change', () => { AP.region = r.value; AP.models = null; AP.mErr = ''; AP.model = ''; aiSetPaint(); if (AP.key || apSavedKey(W.set, apUrl())) apFetchModels(); });
};

function apClick(e) {
    const b = e.currentTarget, a = b.dataset.pact;
    if (a === 'reload') { AP.err = ''; return apLoad(); }
    if (a === 'change') { AP.changing = !AP.changing; AP.sel = null; AP.status = null; return aiSetPaint(); }
    if (a === 'pick') return apPick(b.dataset.id);
    if (a === 'hint') { AP.model = b.dataset.m; return aiSetPaint(); }
    if (a === 'connect') return apConnect();
}

/* Локальная модель подключается старым обработчиком; после успеха схлопываем окно до строки «сейчас». */
(function () {
    const old = aiSetClick;
    window.aiSetClick = async function (e) {
        const a = e.currentTarget.dataset.sact;
        await old.call(this, e);
        if (a === 'connect' && W.probe && apProvOf(W.set) && apProvOf(W.set).id === 'local') {
            AP.status = apProbeStatus(W.probe);
            if (AP.status.kind !== 'bad') { AP.sel = null; AP.changing = false; }
            aiSetPaint();
        }
    };
})();
