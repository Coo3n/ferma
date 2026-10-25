'use strict';

/* Инструмент «Резервная копия»: один архив с аккаунтами, группами,
   расписанием и записанными сценариями. Ключ adb кладётся только по галке. */

async function backupDownload() {
    const withKey = $('backupKey').checked;
    let res;
    try {
        res = await fetch('/api/backup/export', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({adb_key: withKey})});
    } catch (e) {
        return toast('нет связи с фермой', 'bad');
    }
    if (!res.ok) return toast('не удалось собрать копию', 'bad');
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = (res.headers.get('content-disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'farm-backup.zip';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
}

let BACKUP_FILE = null;

async function backupPick(file) {
    BACKUP_FILE = file || null;
    const box = $('backupInfo');
    if (!file) { box.textContent = ''; return; }
    try {
        const info = await api('/api/backup/inspect', {method: 'POST', body: file});
        box.textContent = `В архиве файлов: ${info.files.length}`
            + (info.has_adb_key ? ' · есть ключ adb' : '');
        $('backupRestoreBtn').disabled = false;
    } catch (e) {
        box.textContent = e.message;
        $('backupRestoreBtn').disabled = true;
    }
}

async function backupRestore(ev) {
    if (!BACKUP_FILE) return;
    if (!armConfirm(ev.currentTarget, 'Заменить текущие данные фермы данными из архива?')) return;
    try {
        const res = await api('/api/backup/restore?adb_key=' + ($('backupRestoreKey').checked ? 1 : 0),
                              {method: 'POST', body: BACKUP_FILE});
        toast(`Восстановлено: ${res.restored.length}`
            + (res.skipped.length ? `, пропущено: ${res.skipped.length}` : '')
            + (res.saved_previous_to ? '. Прежние файлы сохранены в data/.restore-backup' : ''), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function backupOpen() {
    $('mTitle').textContent = 'Резервная копия';
    $('mBody').innerHTML = `
      <p class="tool-note">Сохраняет аккаунты, группы, теги, расписание, имена телефонов и записанные сценарии.
        Если ферма переедет на другой компьютер, всё вернётся из этого файла.</p>
      <label><input type="checkbox" id="backupKey"> положить ключ adb (телефоны не придётся авторизовать заново)</label>
      <p class="tool-warn">Ключ и пароли аккаунтов — секреты. Не отправляйте архив никому и не храните в общей папке.</p>
      <div class="bp-row"><button class="sm primary" onclick="backupDownload()">Скачать копию</button></div>
      <hr>
      <p class="tool-note">Восстановить из файла:</p>
      <div class="bp-row"><input type="file" accept=".zip" onchange="backupPick(this.files[0])" aria-label="Архив">
        <label><input type="checkbox" id="backupRestoreKey"> вернуть и ключ adb</label>
        <button class="sm danger" id="backupRestoreBtn" disabled onclick="backupRestore(event)"><span>Восстановить</span></button></div>
      <small class="dim" id="backupInfo"></small>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'backup', icon: 'upload', title: 'Резервная копия',
               sub: 'аккаунты, расписание, сценарии — одним файлом', open: backupOpen});
