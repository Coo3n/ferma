'use strict';

/* Инструмент «Здоровье телефонов»: заряд, температура, место, оперативная
   память и загрузка процессора по всей ферме. Данные уже приходят с опросом
   /api/devices, отдельного запроса нет. Пороги те же, что на сервере
   (config.py: TEMP_ALERT_C, BATTERY_LOW, ROM_ALERT_PCT, RAM_ALERT_FREE_PCT). */

const HEALTH_LIMITS = {temp: 42, battery: 20, rom: 92, ramFree: 8};

function healthRows(devices) {
    return devices.filter(d => d.online).map(d => {
        const bad = [];
        if (d.temperature != null && d.temperature >= HEALTH_LIMITS.temp) bad.push('temp');
        if (d.battery != null && d.battery <= HEALTH_LIMITS.battery) bad.push('battery');
        if (d.rom_used != null && d.rom_used >= HEALTH_LIMITS.rom) bad.push('rom');
        if (d.ram_free != null && d.ram_free <= HEALTH_LIMITS.ramFree) bad.push('ram');
        return {name: d.name, battery: d.battery, temp: d.temperature,
                rom: d.rom_used, ram: d.ram_free, cpu: d.cpu, bad};
    }).sort((a, b) => b.bad.length - a.bad.length || String(a.name).localeCompare(String(b.name), 'ru'));
}

function healthOpen() {
    const rows = healthRows(S.devices || []);
    const cell = (row, key, value, suffix) =>
        `<td${row.bad.includes(key) ? ' class="bad"' : ''}>${value == null ? '—' : esc(value) + suffix}</td>`;
    $('mTitle').textContent = 'Здоровье телефонов';
    $('mBody').innerHTML = rows.length ? `
      <p class="tool-note">Красным — то, что пора починить: заряд, перегрев, мало места или памяти. Обновляется само.</p>
      <table class="tool-table">
        <thead><tr><th>Телефон</th><th>Заряд</th><th>Температура</th><th>Место занято</th><th>ОЗУ свободно</th><th>Процессор</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.name)}</td>
          ${cell(r, 'battery', r.battery, '%')}${cell(r, 'temp', r.temp, '°C')}
          ${cell(r, 'rom', r.rom, '%')}${cell(r, 'ram', r.ram, '%')}${cell(r, 'cpu', r.cpu, '%')}</tr>`).join('')}</tbody>
      </table>`
        : '<p class="tool-note">Нет телефонов в сети.</p>';
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'health', icon: 'sliders', title: 'Здоровье телефонов',
               sub: 'заряд, нагрев, память, процессор', open: healthOpen});
