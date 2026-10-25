'use strict';

/* Инструмент «Черновик по описанию»: пишете задачу словами, нейросеть
   предлагает шаги. Это черновик: он сохраняется как обычный сценарий, который
   надо проверить на одном телефоне. Нужен включённый помощник (значок в шапке). */

let DRAFT = null;

function draftStepText(step) {
    const a = step.args || {};
    return {launch_app: `открыть приложение ${a.package}`, open_url: `открыть ссылку ${a.url}`,
            tap: `нажать в точку (${a.x}, ${a.y})`, swipe: `провести (${a.x1}, ${a.y1}) → (${a.x2}, ${a.y2})`,
            type: `ввести «${a.value}»`, key: `клавиша ${a.name}`, sleep: `подождать ${a.seconds} с`}[step.kind] || step.kind;
}

function draftOpen() {
    const phones = (S.devices || []).filter(d => d.online);
    $('mTitle').textContent = 'Черновик по описанию';
    $('mBody').innerHTML = `
      <p class="tool-note">Опишите, что делать. Нейросеть посмотрит на экран выбранного телефона и предложит шаги.
        Кадр экрана уходит во внешнюю модель — помощник должен быть включён вами.</p>
      <label>Телефон для снимка: <select id="draftPhone">${phones.map(d =>
        `<option value="${esc(d.serial)}">${esc(d.name)}</option>`).join('')}</select></label>
      <textarea id="draftTask" rows="3" placeholder="Например: открой Telegram и пролистай ленту вниз пять раз"></textarea>
      <div class="bp-row"><button class="sm primary" id="draftBtn" onclick="draftMake()">Составить шаги</button></div>
      <div id="draftOut"></div>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

async function draftMake() {
    const out = $('draftOut');
    const serial = $('draftPhone').value, task = $('draftTask').value.trim();
    if (!serial) return toast('нет телефона в сети', 'bad');
    if (!task) return toast('опишите задачу', 'bad');
    $('draftBtn').disabled = true;
    out.textContent = 'Думаю…';
    try {
        DRAFT = await api('/api/vlm/plan', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial, task})});
        out.innerHTML = `<ol>${DRAFT.steps.map(s => `<li>${esc(draftStepText(s))}</li>`).join('')}</ol>
          <div class="bp-row"><button class="sm primary" onclick="draftSave()">Сохранить как сценарий</button></div>
          <small class="dim">Это черновик. Откройте его в конструкторе, проверьте и запустите на одном телефоне.</small>`;
    } catch (e) {
        DRAFT = null;
        out.textContent = e.message;
    }
    $('draftBtn').disabled = false;
}

async function draftSave() {
    if (!DRAFT) return;
    try {
        const res = await api('/api/recorder/save', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(DRAFT.recipe)});
        toast(`Сохранено: ${DRAFT.recipe.meta.name}. Найдите его на вкладке «Сценарии».`, 'ok');
        DRAFT = null;
        await loadScenarios(true);
        return res;
    } catch (e) {
        toast(e.message, 'bad');
    }
}

toolsRegister({id: 'draft', icon: 'record', title: 'Черновик по описанию',
               sub: 'нейросеть предложит шаги, вы проверите', open: draftOpen});
