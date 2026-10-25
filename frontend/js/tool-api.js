'use strict';

/* Инструмент «Для программистов»: адрес и справка API. Сам API уже есть —
   здесь только подсказка, куда смотреть и как закрыть доступ из сети. */

function apiToolOpen() {
    const base = location.origin;
    $('mTitle').textContent = 'Для программистов';
    $('mBody').innerHTML = `
      <p class="tool-note">Всё, что делает сайт, можно делать из своих программ по HTTP.</p>
      <ul>
        <li>Справка по всем действиям: <a href="${esc(base)}/docs" target="_blank" rel="noopener">${esc(base)}/docs</a></li>
        <li>Адрес API: <code>${esc(base)}/api</code></li>
        <li>Описание с примерами: файл <code>docs/public-api.md</code> в папке фермы</li>
      </ul>
      <p class="tool-warn">Если открываете ферму в сеть, задайте секрет <code>FARM_TOKEN</code> — иначе любой в сети управляет вашими телефонами.</p>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'api', icon: 'external', title: 'Для программистов',
               sub: 'управлять фермой из своих программ', open: apiToolOpen});
