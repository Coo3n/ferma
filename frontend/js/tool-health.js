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
    const warnings = {battery: t('health.low_battery'), temp: t('health.hot'),
        rom: t('health.low_storage'), ram: t('health.low_memory')};
    const cell = (row, key, value, suffix) =>
        `<td${row.bad.includes(key) ? ' class="bad"' : ''}>${value == null ? '—' : esc(value) + suffix}${
            row.bad.includes(key) ? `<span class="health-warning">${esc(warnings[key])}</span>` : ''}</td>`;
    $('mTitle').textContent = t('health.title');
    $('mBody').innerHTML = rows.length ? `
      <div class="tool-table-scroll" role="region" tabindex="0" aria-label="${t('health.title')}">
      <table class="tool-table">
        <thead><tr><th>${t('health.phone')}</th><th>${t('health.battery')}</th><th>${t('health.temperature')}</th><th>${t('health.storage')}</th><th>${t('health.memory')}</th><th>${t('health.cpu')}</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.name)}</td>
          ${cell(r, 'battery', r.battery, '%')}${cell(r, 'temp', r.temp, '°C')}
          ${cell(r, 'rom', r.rom, '%')}${cell(r, 'ram', r.ram, '%')}${cell(r, 'cpu', r.cpu, '%')}</tr>`).join('')}</tbody>
      </table></div>`
        : `<p class="tool-note">${t('health.empty')}</p>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">${t('health.close')}</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'health', icon: 'sliders', title: t('health.title'),
               sub: t('health.subtitle'), open: healthOpen});
