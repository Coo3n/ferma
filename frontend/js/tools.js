'use strict';

/* «Инструменты фермы»: окно для вещей, которые относятся ко всей ферме, а не к
   одному телефону или сценарию (здоровье, уведомления, резервная копия, API,
   черновик по описанию). Вкладка регистрирует себя сама через toolsRegister,
   поэтому новый инструмент — отдельный файл и одна строка в index.html. */

const TOOLS = [];

function toolsRegister(tool) {
    const at = TOOLS.findIndex(x => x.id === tool.id);
    if (at >= 0) TOOLS[at] = tool;
    else TOOLS.push(tool);
}

function toolsTilesHtml(list) {
    return list.map(tool => `<button onclick="toolsRun('${esc(tool.id)}')">
        <svg class="ic" aria-hidden="true"><use href="#i-${esc(tool.icon)}"/></svg>
        <b>${esc(tool.title)}</b><span>${esc(tool.sub)}</span></button>`).join('');
}

function toolsBackButton() {
    return `<button onclick="toolsOpen()">${esc(t('tools.nazad'))}</button>`;
}

function toolsOpen() {
    $('mTitle').textContent = t('tools.zagolovok');
    $('mBody').innerHTML = `<div class="bulk-grid">${toolsTilesHtml(TOOLS)}</div>`;
    $('mActs').innerHTML = `<span class="sp"></span><button onclick="closeModal()">${esc(t('tools.zakryt'))}</button>`;
    modalSheet('wide');
    openModal();
}

function toolsRun(id) {
    const tool = TOOLS.find(x => x.id === id);
    if (tool) tool.open();
}
