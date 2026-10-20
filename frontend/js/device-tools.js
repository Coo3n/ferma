'use strict';

/* Разовые команды устройству: запуск приложения, ссылка, adb shell, дамп
   иерархии и logcat.

   Живут в диалоге «Управление», а не отдельной вкладкой рабочего места:
   нужны раз за сеанс, а постоянного места на экране стоили столько же,
   сколько конструктор сюжета. Вывод один на все команды (#devOut): раньше
   их было два — отдельный для дампов, — и по какому из них смотреть
   результат, приходилось помнить. */

const LOGCAT_LINES = 300;

function devToolsOpen() {
    if (!S.active) {
        toast('сначала откройте телефон', 'bad');
        return;
    }
    const device = (S.devices || []).find(d => d.serial === S.active);
    $('mTitle').textContent = 'Управление телефоном';
    $('mBody').innerHTML = `
    <!-- Состояние и «Починить» переехали сюда из панели рабочего места:
         заряд с температурой видно на плитке фермы, а чинить соединение
         нужно раз в день — обе вещи не стоили строки над экраном. -->
    <div class="box">
        <h3>${esc(device ? device.name : 'Телефон')}</h3>
        <div class="row">
            <span class="stat sm">${esc(device ? fleetMeta(device) : S.active)}</span>
            <span class="sp"></span>
            <button class="sm" onclick="recoverDevice()"
                    title="Переподключить только этот телефон">
                <svg class="ic" aria-hidden="true"><use href="#i-wrench"/></svg>
                Починить
            </button>
        </div>
    </div>
    <div class="box">
        <h3>Запуск приложения</h3>
        <div class="row">
            <input type="text" id="pkgInput" placeholder="Название приложения, например VK"
                   aria-label="Название приложения" list="pkgList">
            <datalist id="pkgList"></datalist>
            <button class="sm" onclick="launchPkg()">Открыть</button>
        </div>
        <div class="row">
            <button class="sm" onclick="loadPackages()">Загрузить список приложений</button>
            <button class="sm danger" onclick="stopPkg()">Закрыть принудительно</button>
        </div>
    </div>
    <div class="box">
        <h3>Открыть ссылку</h3>
        <div class="row">
            <input type="text" id="urlInput" placeholder="https://example.com"
                   aria-label="Ссылка">
            <button class="sm" onclick="openUrl()">Открыть</button>
        </div>
    </div>
    <div class="box">
        <h3>Консоль (для опытных)</h3>
        <div class="row">
            <input type="text" id="shellInput" placeholder="dumpsys battery"
                   aria-label="Команда для телефона (для опытных)"
                   onkeydown="if(event.key==='Enter')runShell()">
            <button class="sm" onclick="runShell()" aria-label="Выполнить">
                <svg class="ic" aria-hidden="true"><use href="#i-enter"/></svg>
            </button>
        </div>
    </div>
    <div class="box">
        <h3>Диагностика (для опытных)</h3>
        <div class="row">
            <button class="sm" onclick="dumpUi()">Разметка экрана</button>
            <button class="sm" onclick="showLogcat()">Журнал телефона</button>
            <span class="sp"></span>
            <button class="sm" onclick="clearDevOut()">
                <svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg>
                Очистить
            </button>
        </div>
    </div>
    <pre class="log" id="devOut"></pre>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="sm" onclick="closeModal()">Закрыть</button>';
    modalSheet('wide');
    openModal();
}

/* Вписали название («VK») — берём его приложение; не нашли — считаем, что
   вписали код приложения руками. */
function packageField() {
    const typed = $('pkgInput').value.trim();
    const hit = ((APP_PICK.byDevice[S.active] || {}).rows || []).find(a => a.label.toLowerCase() === typed.toLowerCase());
    return hit ? hit.package : typed;
}

/* Диалог пересобирается при каждом открытии — вывода может уже не быть
   (например, команда доехала после закрытия). Молча пропускаем: тост об
   ошибке команда показывает сама. */
function devOut(text) {
    const box = $('devOut');
    if (box) box.textContent = text;
}

async function loadPackages() {
    if (!S.active) return;
    try {
        const list = await appChoices(S.active);
        const options = $('pkgList');
        if (options) options.innerHTML = list.map(a => `<option value="${esc(a.label)}" label="${esc(a.package)}">`).join('');
        devOut(list.map(a => `${a.label} — ${a.package}`).join('\n'));
        toast(`приложений: ${list.length}`, 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function launchPkg() {
    const name = packageField();
    if (name) act({type: 'launch', package: name});
}

function stopPkg() {
    const name = packageField();
    if (name) act({type: 'stop', package: name});
}

function openUrl() {
    const url = $('urlInput').value.trim();
    if (url) act({type: 'url', url});
}

async function runShell() {
    const command = $('shellInput').value.trim();
    if (!command) return;
    try {
        const result = await act({type: 'shell', cmd: command});
        devOut(result.output || '(пусто)');
    } catch (e) {
        devOut(e.message);
    }
}

function clearDevOut() {
    devOut('');
}

async function dumpUi() {
    if (!S.active) return;
    try {
        devOut(await api(`/api/devices/${S.active}/hierarchy`));
    } catch (e) {
        toast(e.message, 'bad');
    }
}

async function showLogcat() {
    if (!S.active) return;
    try {
        devOut(await api(`/api/devices/${S.active}/logcat?lines=${LOGCAT_LINES}`));
    } catch (e) {
        toast(e.message, 'bad');
    }
}
