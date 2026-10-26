'use strict';

/* Инструмент «Уведомления»: что пришло на телефоны. Видна только шторка
   уведомлений, не содержимое приложений. Текст по умолчанию скрыт. */

function notifSummary(results) {
    const per = new Map();
    for (const r of Object.values(results || {})) {
        const mine = new Map();
        for (const item of (r && r.items) || []) mine.set(item.pkg, (mine.get(item.pkg) || 0) + 1);
        for (const [pkg, n] of mine) {
            const g = per.get(pkg) || {pkg, phones: 0, total: 0};
            g.phones += 1;
            g.total += n;
            per.set(pkg, g);
        }
    }
    return [...per.values()].sort((a, b) => b.phones - a.phones || b.total - a.total);
}

async function notifOpen() {
    let watch = {packages: []};
    try {
        watch = await api('/api/notifications/watch');
    } catch (e) { /* список пуст — покажем форму */ }
    $('mTitle').textContent = 'Уведомления';
    $('mBody').innerHTML = `
      <p class="tool-note">Видны только уведомления в шторке; сообщения внутри приложений недоступны.
        Проверьте на одном телефоне: формат уведомлений зависит от версии Android.</p>
      <label>Приложения (по строке, пакет): <textarea id="notifPkgs" rows="3"
        placeholder="com.whatsapp">${esc(watch.packages.join('\n'))}</textarea></label>
      <div class="bp-row">
        <label><input type="checkbox" id="notifText"> показать текст (коды и банки скрываются)</label>
        <button class="sm primary" onclick="notifScan()">Проверить</button></div>
      <div id="notifOut"></div>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

async function notifScan() {
    const pkgs = $('notifPkgs').value.split(/\s+/).map(s => s.trim()).filter(Boolean);
    const out = $('notifOut');
    out.textContent = 'Проверяю телефоны…';
    try {
        const saved = await api('/api/notifications/watch', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({packages: pkgs})});
        const res = await api(`/api/notifications?packages=${encodeURIComponent(saved.packages.join(','))}&text=${$('notifText').checked ? 1 : 0}`);
        const sum = notifSummary(res);
        out.innerHTML = sum.length
            ? `<table class="tool-table"><thead><tr><th>Приложение</th><th>Телефонов</th><th>Всего</th></tr></thead><tbody>
                ${sum.map(g => `<tr><td>${esc(g.pkg)}</td><td>${g.phones}</td><td>${g.total}</td></tr>`).join('')}</tbody></table>`
              + Object.values(res).filter(r => (r.items || []).some(i => i.title)).map(r =>
                  `<p><b>${esc(r.name)}</b>: ` + r.items.filter(i => i.title)
                      .map(i => `${esc(i.title)} — ${esc(i.text || '')}`).join('; ') + '</p>').join('')
            : '<p class="tool-note">Новых уведомлений нет.</p>';
    } catch (e) {
        out.textContent = e.message;
    }
}

toolsRegister({id: 'notify', icon: 'info', title: 'Уведомления',
               sub: 'где пришло сообщение или код', open: notifOpen});
