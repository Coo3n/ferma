'use strict';

/* Модальное окно с подробностями об устройстве.

   Открытие идёт через openModal() из core.js — там ловушка фокуса и Escape,
   общие для всех диалогов приложения. */

function closeModal() {
    $('modal').classList.remove('on');
    /* Широкий лист просит только «Управление» (там консоль adb): следующий
       диалог обязан открыться обычной ширины. */
    $('modal').querySelector('.sheet').classList.remove('wide');
    if (modalReturn && modalReturn.isConnected) modalReturn.focus();
    modalReturn = null;
}

function formatTime(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleString('ru-RU') : '—';
}

function currentAppName(device) {
    const value = device.current_app;
    if (value && typeof value === 'object') {
        return value.package || JSON.stringify(value);
    }
    return value;
}

function deviceRows(device) {
    return [
        ['Серийный номер', device.serial],
        ['Модель', [device.brand, device.model].filter(Boolean).join(' ') || '—'],
        ['Android', device.android || '—'],
        ['Экран', device.width ? `${device.width}×${device.height}` : '—'],
        ['Состояние', device.online ? 'в сети' : device.state],
        ['Батарея', device.battery != null
            ? device.battery + '%' + (device.charging ? ' · ' + device.charging : '')
            : '—'],
        ['Температура', device.temperature != null ? device.temperature.toFixed(1) + '°C' : '—'],
        ['Идёт запуск', device.busy_job ? 'да' : 'нет'],
        ['Запись шагов', device.u2 ? 'готова' : 'подключится при первой записи'],
        ['Текущее приложение', currentAppName(device) || '—'],
        ['Впервые замечено', formatTime(device.first_seen)],
        ['Последний раз в сети', formatTime(device.last_seen)],
    ];
}

function modalActions(device) {
    const serial = esc(device.serial);
    const visibility = S.hidden.has(device.serial)
        ? `<button class="sm" onclick="unhideDevice('${serial}')">
             <svg class="ic"><use href="#i-undo"/></svg>Показать в списке</button>`
        : `<button class="sm" onclick="hideDevice('${serial}')">
             <svg class="ic"><use href="#i-eye-off"/></svg>Скрыть из списка</button>`;
    return `
    <button class="sm" onclick="closeModal();renameDevice('${serial}')">
      <svg class="ic"><use href="#i-pencil"/></svg>Переименовать</button>
    ${visibility}
    <span class="sp"></span>
    <button class="primary" onclick="closeModal()">Закрыть</button>`;
}

function deviceBody(device) {
    return deviceRows(device)
            .map(([key, value]) => `<div class="kv"><span>${esc(key)}</span><b>${esc(value)}</b></div>`)
            .join('')
        + (device.warnings.length
            ? `<div class="warn"><svg class="ic"><use href="#i-alert"/></svg>
                 <span>${esc(device.warnings.join('; '))}</span></div>`
            : '');
}

/* Окно открывается сразу по данным из списка, а подробности догружаются.

   Полный /api/devices/{serial} спрашивает у телефона текущее приложение через
   adb, и это занимает секунды — на спящем эмуляторе замерено 11. Ждать ответа
   перед показом окна нельзя: клик по «ⓘ» выглядел бы как промах. Поэтому
   сначала рисуем то, что уже известно из опроса фермы, а медленное поле
   подставляем по приезде. */
async function deviceInfo(serial) {
    const known = S.devices.find(d => d.serial === serial);
    if (known) {
        $('mTitle').textContent = known.name;
        $('mBody').innerHTML = deviceBody(Object.assign({}, known, {current_app: '…'}));
        $('mActs').innerHTML = modalActions(known);
        openModal();
    }

    let device;
    try {
        device = await api('/api/devices/' + serial);
    } catch (e) {
        if (!known) toast(e.message, 'bad');
        return;
    }

    // Пока ходили на сервер, окно могли закрыть или открыть другое.
    if (known && (!$('modal').classList.contains('on')
        || $('mTitle').textContent !== known.name)) return;

    $('mTitle').textContent = device.name;
    $('mBody').innerHTML = deviceBody(device);
    $('mActs').innerHTML = modalActions(device);
    if (!known) openModal();
}

/* Диалог подтверждения и ввода строки — замена нативным confirm()/prompt().

   Нативные окна блокируют поток, не стилизуются и в части браузеров молча
   подавляются. Здесь же работает общая ловушка фокуса, а текст можно
   разметить. */

function confirmModal(title, html, okLabel, onOk, danger) {
    $('mTitle').textContent = title;
    $('mBody').innerHTML = html;
    $('mActs').innerHTML = `
    <span class="sp"></span>
    <button class="sm" id="mCancel">Отмена</button>
    <button class="${danger ? 'danger' : 'primary'}" id="mOk">${esc(okLabel)}</button>`;
    $('mCancel').onclick = closeModal;
    $('mOk').onclick = () => {
        closeModal();
        onOk();
    };
    openModal();
    $('mOk').focus();
}

function promptModal(title, label, value, okLabel, onOk) {
    $('mTitle').textContent = title;
    $('mBody').innerHTML = `<div class="row">
      <label for="mInput">${esc(label)}</label>
      <input type="text" id="mInput" class="grow" value="${esc(value)}">
    </div>`;
    $('mActs').innerHTML = `
    <span class="sp"></span>
    <button class="sm" id="mCancel">Отмена</button>
    <button class="primary" id="mOk">${esc(okLabel)}</button>`;

    const submit = () => {
        const text = $('mInput').value.trim();
        closeModal();
        onOk(text);
    };
    $('mCancel').onclick = closeModal;
    $('mOk').onclick = submit;
    $('mInput').onkeydown = ev => {
        if (ev.key === 'Enter') submit();
    };
    openModal();
    $('mInput').select();
}
