'use strict';

/* Конструктор сценариев: запись действий, список шагов, сохранение.

   Дамп UI кэшируется вперёд — читается при старте записи и заново после
   каждого действия. Тап поэтому улетает на устройство мгновенно, а селектор
   берётся из кэша. См. docs/GOTCHAS.md.

   Состояние на window, а не const: у обычного (не module) скрипта
   верхнеуровневый const не становится свойством window. */

const REC_REFRESH_MS = 400;
const REC_PAUSE_MIN_S = 1.0;
const REC_DRAFT_KEY = 'farm.recorder.draft';

/* Тултип объясняет «Якорь»/«Развилку» до клика, но тултип читает не
   каждый — наводить курсор специально, чтобы прочитать подсказку, никто не
   станет. Первое фактическое использование каждой кнопки в этом браузере
   получает развёрнутый тост вместо обычного короткого — дальше, когда
   смысл уже понятен, снова короткий. */
function recFirstHint(key, long, short) {
    const flagKey = 'farm.recorder.hint.' + key;
    if (store.get(flagKey, null)) return short;
    store.set(flagKey, 1);
    return long;
}

/* Запасные слои цели. Селектор ломается от перевёрстки, смены прошивки и
   локали, а на Compose и в WebView его часто нет вовсе — поэтому вместе с
   селектором пишем текст, картинку цели и координаты. На прогоне резолвер
   пробует их по очереди (см. farm/resolve.py). */
const REC_TEXTS_MAX = 3;        // столько же принимает steps.py
const REC_ASSETS_MAX = 60;      // потолок бэкенда на число ассетов
const REC_CROP_MAX_BYTES = 300000;  // потолок бэкенда на размер одного ассета
const REC_CROP_MIN_PX = 8;      // мельче matchTemplate находит что попало

/* Якоря экранов. На разных устройствах сценарий встречает разные экраны —
   A/B-онбординги, неожиданные пейволлы. Без якоря он уезжает не туда и
   тапает в пустоту несколько шагов подряд, а падает далеко от причины.
   Якорь ставится перед первым действием на новом экране и проверяет
   «я там, где думаю» (см. ctx.expect_screen). */
const REC_SCREEN_DIFF = 0.4;    // доля сменившихся узлов, считаем экран новым
const REC_ANCHOR_MAX = 3;       // столько признаков принимает steps.py

/* Развилка: «если на экране то-то — делай то». Потолок ветвей тот же, что в
   steps.py (ARMS_MAX): дальше это не сюжет, а таблица переходов. */
const REC_ARMS_MAX = 5;

/* Типы действий /action → виды шагов. Действия shell тут нет намеренно:
   adb shell из вкладки «Управление» это диагностика, и писать dumpsys в
   сценарий никто не просил. Шаг shell попадает в сценарий только из
   библиотеки готовых скриптов — см. recLibOpen(). */
const REC_KIND = {
    tap: 'tap', long_tap: 'long_tap', swipe: 'swipe', text: 'type',
    key: 'key', unlock: 'unlock',
    launch: 'launch_app', stop: 'stop_app', url: 'open_url',
};

/* Шаги, у которых есть одно строковое значение: его правят и выносят в PARAMS. */
const REC_VALUE_KEY = {
    type: 'value', launch_app: 'package', stop_app: 'package',
    open_url: 'url', shell: 'cmd', sleep: 'seconds', screenshot: 'name',
};

window.REC = {
    on: false,
    baseWidth: null,    // ширина устройства записи при правке — см. recPayload()
    steps: [],
    params: {},
    open: null,
    hover: null,
    nextId: 1,
    lib: null,
    packages: null,
    dump: null,
    screenWidth: null,  // ширина устройства записи — нужна для масштаба шаблона
    teach: null,        // слепок преграды, когда учим её обходить
    edit: null,         // {key, meta} — правим уже сохранённый сценарий
    builder: false,     // конструктор открыт; false — пульт телефона (pult.js)
    lastSig: null,      // отпечаток экрана на момент последнего шага
    screenN: 0,         // счётчик имён экранов для якорей
    branchN: 0,         // счётчик подписей развилок
    stale: false,
    pauses: false,
    lastAt: 0,
    timer: null,
    drag: null,       // id шага, который тащат мышью
    view: 'list',     // 'scheme' | 'list'; схема скрыта — список-фразы читаются проще графа
    schemeTimer: null,
    zoom: 1,          // масштаб холста схемы, см. grZoomSet()
};

const REC = window.REC;

/* ------------------------------------------------------------------ режимы */

/* Запись живёт в рабочем месте устройства: шаги пишутся кликами по экрану,
   а экран есть только там. Кнопка «Создать записью» на «Сценариях» поэтому
   не открывает форму на месте, а уводит к устройству. */
function recOpen(keepSteps) {
    if (!S.active) {
        toast('сначала откройте телефон', 'bad');
        showView('fleet');
        return;
    }
    REC.builder = true;
    showView('device');
    if (!keepSteps) recRestore();
    /* Список — единственный вид: схема-граф путала операторов, а всё, что
       она умела показать (блоки, развилки), список рисует рамками. */
    recSetView('list');
    recRender();
    recSync();
}

/* Запись закончена — показать результат. Имя важно: функция не «закрывает
   конструктор», а уводит к списку сценариев, где только что появился новый. */
function recDone() {
    if (REC.on) recPause();
    showView('scen');
}

function recSync() {
    const state = $('recState');
    if (state) {
        state.textContent = REC.on
            ? (REC.stale ? 'запись · обновляю…' : 'идёт запись')
            : (REC.steps.length ? 'запись остановлена' : 'не записывается');
        /* В покое чип молчит: «не записывается» повторяет то, что и так
           видно по кнопке «Запись» (она активна, «Пауза» погашена), а
           места в ряду занимает столько же, сколько кнопка. Появляется,
           когда есть что сказать — идёт запись или стоит на паузе. */
        state.hidden = !REC.on && !REC.steps.length;
    }
    const start = $('btnRecStart');
    if (start) {
        start.classList.toggle('on', REC.on);
        disableWithReason(start, REC.on, 'Уже идёт — чтобы остановить, нажмите «Пауза»');
    }
    disableWithReason($('btnRecPause'), !REC.on, 'Сначала нажмите «Запись»');

    /* Кнопка, которая ничего не сделает, должна об этом говорить заранее. */
    const нечего = !REC.steps.length;
    disableWithReason($('btnRecCode'), нечего, 'Сначала запишите хотя бы один шаг');
    disableWithReason($('btnRecBranch'), !S.active,
        'Сначала откройте телефон');
    disableWithReason($('btnRecSave'), нечего, 'Сначала запишите хотя бы один шаг');

    /* В режиме обучения сохраняется отвод, в режиме правки — уже существующий
       файл. Кнопка обязана называться тем, что произойдёт. */
    const save = $('btnRecSave');
    if (save) {
        setText(save.querySelector('span'),
            REC.teach ? 'Сохранить автозакрытие'
                : REC.edit ? 'Сохранить изменения' : 'Сохранить сценарий');
    }
    /* Выход из режима — один и тот же жест «ничего не сохранять», поэтому и
       кнопка одна: два соседних выхода читались бы как разные действия. */
    const выход = $('btnRecModeOff');
    if (выход) {
        выход.hidden = !REC.teach && !REC.edit;
        setText(выход.querySelector('span'), REC.teach ? 'Не учить' : 'Не править');
        выход.title = REC.teach
            ? 'Выйти из обучения, не сохраняя автозакрытие'
            : 'Выйти из правки, не сохраняя изменения';
    }
    /* Клики по экрану разрешены только на время записи — см. canInteract(). */
    if (window.syncInteractive) syncInteractive();
    if (window.pultSync) pultSync();
}

function recBanner(message) {
    REC.bannerMsg = message || '';
    const box = $('recBanner');
    if (!box) return;
    box.hidden = !message;
    box.innerHTML = message
        ? `<svg class="ic"><use href="#i-alert"/></svg><span>${esc(message)}</span>`
        : '';
}

/* ------------------------------------------------------------------ запись */

async function recStart() {
    if (!S.active) {
        toast('сначала выберите телефон', 'bad');
        return;
    }
    /* Кликать по экрану нечем, если зеркало свёрнуто: разворачиваем сами,
       а не отказываем — человек нажал «Запись», намерение однозначно. */
    if (window.mirrorShow) mirrorShow();
    if (window.liveControlOff) liveControlOff();   // запись сама даёт интерактивность
    REC.on = true;
    REC.builder = true;
    /* Экран «забывается» на старте: первое действие всегда получает якорь,
       иначе сценарий начинался бы без проверки, где он вообще находится. */
    REC.lastSig = null;
    REC.lastAt = Date.now();
    recSync();
    await recLoadDump();
    recSync();
}

function recPause() {
    REC.on = false;
    if (REC.insertAfter) {
        REC.insertAfter = null;
        recBanner(REC.bannerBefore || '');   // вернуть плашку правки, если была
    }
    recOverlayOff();
    recSync();
    recSave();
}

async function recLoadDump() {
    if (!S.active) return;
    REC.stale = true;
    recOverlayOff();
    recSync();
    try {
        REC.dump = await api(`/api/devices/${S.active}/inspect`);
        /* Ширина УСТРОЙСТВА, а не скриншота: скриншот отмасштабирован до 1080,
           а на прогоне масштаб шаблона считается от реального разрешения.
           Запоминаем отдельно — к моменту сохранения дамп может смениться. */
        if (REC.dump.width) REC.screenWidth = REC.dump.width;
        recBanner(REC.dump.nodes.length
            ? ''
            : 'кнопки не распознаются — шаги запишутся как нажатия в точку');
    } catch (e) {
        REC.dump = null;
        recBanner('не удалось разобрать экран — шаги запишутся как нажатия в точку: ' + e.message);
    }
    REC.stale = false;
    recOverlayRender();
    recSync();
}

function recRefreshDump() {
    clearTimeout(REC.timer);
    REC.stale = true;
    recOverlayOff();
    recSync();
    REC.timer = setTimeout(() => {
        if (REC.on) recLoadDump();
    }, REC_REFRESH_MS);
}

/* ------------------------------------------------------------------ шаги */

/* Наименьший по площади узел под точкой — тот же критерий, что в инспекторе.
   При равной площади берётся более поздний в дампе: это вложенный узел с
   теми же рамками (кнопка внутри обёртки) или то, что нарисовано поверх
   (диалог над лентой). Раньше выигрывал первый — обёртка или то, что под. */
function recHit(x, y, dump) {
    const src = dump || REC.dump;
    const nodes = (src && src.nodes) || [];
    let best = null, bestArea = Infinity;
    for (const node of nodes) {
        const [x1, y1, x2, y2] = node.bounds;
        if (x < x1 || x > x2 || y < y1 || y > y2) continue;
        const area = (x2 - x1) * (y2 - y1);
        if (area <= bestArea) {
            bestArea = area;
            best = node;
        }
    }
    return best;
}

function recNodeLabel(node) {
    const name = node.text || node.description
        || (node.resourceId || '').split('/').pop();
    return name ? `«${name}»` : (node.class || '').split('.').pop();
}

/* Подписи шагов читает не программист: «Тап по LinearLayout» и
   «shell pm clear …» ничего ему не говорят. Технические имена переводим,
   безымянные элементы описываем местом на экране. */
const REC_APPS = {
    'com.vkontakte.android': 'VK',
    'com.instagram.android': 'Instagram',
    'com.zhiliaoapp.musically': 'TikTok',
    'com.ss.android.ugc.trill': 'TikTok',
    'org.telegram.messenger': 'Telegram',
    'org.telegram.messenger.web': 'Telegram',
    'com.android.chrome': 'Chrome',
    'com.android.settings': 'Настройки',
};

const REC_KEYS = {
    BACK: 'Назад', HOME: 'Домой', ENTER: 'Enter', APP_SWITCH: 'Недавние приложения',
    POWER: 'Питание', DEL: 'Стереть', TAB: 'Tab', VOLUME_UP: 'Громче', VOLUME_DOWN: 'Тише',
};

/* Неизвестный пакет — имя из самого пакета: com.wildberries.ru.dev →
   «Wildberries». Полный пакет остаётся в подсказке и в коде. */
const REC_PKG_NOISE = new Set(['com', 'org', 'net', 'ru', 'io', 'app', 'apps', 'android',
    'mobile', 'dev', 'debug', 'release', 'client', 'lite', 'beta', 'main']);

function recApp(pkg) {
    if (REC_APPS[pkg]) return `«${REC_APPS[pkg]}»`;
    const word = String(pkg || '').split('.').find(p => p.length > 2 && !REC_PKG_NOISE.has(p.toLowerCase()));
    return word ? `«${word[0].toUpperCase()}${word.slice(1)}»` : pkg;
}

/* Автоимя экрана «screen8» — для человека просто «экран 8». */
function recScreenName(name) {
    const m = /^screen(\d+)$/i.exec(name || '');
    return m ? `экран ${m[1]}` : `«${name}»`;
}

function recWhere(p) {
    if (Array.isArray(p)) p = {x: p[0], y: p[1]};
    if (!p || p.x == null) return '';
    const col = p.x < 0.34 ? 'слева' : p.x > 0.66 ? 'справа' : 'по центру';
    const row = p.y < 0.2 ? 'вверху' : p.y > 0.8 ? 'внизу' : p.y < 0.45 ? 'выше середины'
        : p.y > 0.55 ? 'ниже середины' : 'в середине';
    return `${row} ${col}`;
}

/* «layout_email_or_phone» → «email or phone»; голое имя класса
   (View, LinearLayout) — это не подпись, а её отсутствие. */
function recHumanNote(note) {
    const m = /^«(.+)»$/.exec(note || '');
    if (!m) return '';
    /* Обычная подпись («Продолжить») — как есть; переводим только
       технические имена: с подчёркиванием или в camelCase. */
    if (!/_|[a-z][A-Z]/.test(m[1])) return note;
    const t = m[1].replace(/([a-zа-я])([A-ZА-Я])/g, '$1_$2')   // getCodeButton → get_Code_Button
        .replace(/^(layout|btn|button|tv|iv|et|text|edit)_/i, '')
        .replace(/_(button|btn|view|container|layout|text|textview)$/i, '')
        .replace(/_/g, ' ').trim().toLowerCase();
    return t ? `«${t}»` : note;
}

function recLabel(step) {
    const a = step.args;
    switch (step.kind) {
        case 'expect':
            return `Проверка экрана: ${recScreenName(a.name)}`;
        case 'branch': {
            const ветки = (step.arms || []).map(arm => arm.name).join(' / ');
            return `Развилка «${a.name}»: ${ветки}`;
        }
        case 'click': {
            /* У безымянного View подпись часто есть в самом селекторе:
               description="Закрыть" — это и есть имя кнопки для человека. */
            const sel = step.selector && typeof step.selector.args === 'string'
                ? /(?:text|description)="([^"]+)"/.exec(step.selector.args) : null;
            const name = recHumanNote(step.note) || (sel ? `«${sel[1]}»` : '');
            return name ? 'Нажать ' + name : 'Нажать элемент ' + (recWhere(step.point) || 'на экране');
        }
        case 'tap':
            return 'Нажать ' + recWhere(a);
        case 'long_tap':
            return 'Долгое нажатие ' + recWhere(a);
        case 'swipe': {
            const dy = a.y2 - a.y1, dx = a.x2 - a.x1;
            const dir = Math.abs(dy) >= Math.abs(dx) ? (dy < 0 ? 'вверх' : 'вниз') : (dx < 0 ? 'влево' : 'вправо');
            return `Свайп ${dir}`;
        }
        case 'type':
            if (a.account) {
                return `Ввести ${REC_ACC_FIELDS[a.field] || a.field} аккаунта ${PLATFORM_NAMES[a.account] || a.account}`;
            }
            return (a.clear ? 'Стереть и ввести «' : 'Ввести «') + a.value + '»';
        case 'key':
            return `Кнопка «${REC_KEYS[String(a.name).toUpperCase()] || a.name}»`;
        case 'unlock':
            return 'Разблокировать экран';
        case 'launch_app':
            return `Открыть ${recApp(a.package)}`;
        case 'stop_app':
            return `Закрыть ${recApp(a.package)}`;
        case 'open_url':
            return `Открыть ссылку ${a.url}`;
        case 'shell': {
            const clear = /^pm clear (\S+)$/.exec((a.cmd || '').trim());
            return clear ? `Очистить данные ${recApp(clear[1])}` : `Команда: ${a.cmd}`;
        }
        case 'sleep':
            return `Подождать ${a.seconds} с`;
        case 'screenshot':
            return 'Снимок экрана' + (a.name ? ` «${a.name}»` : '');
        case 'loop':
        case 'chance':
        case 'until':
        case 'if_seen':
            return blockLabel(step);
        case 'break':
            return t('rec.vyyti_iz_povtora');
        case 'finish':
            return a.result === 'fail'
                ? t('rec.zakonchit_oshibka', {why: a.reason || '—'})
                : t('rec.zakonchit_uspeh');
        case 'call':
            return t('rec.zapustit_stsenariy', {name: recScenName(a.scenario)});
        default:
            return step.kind;
    }
}

function recRecordAfter(id) {
    const index = REC.steps.findIndex(s => s.id === id);
    if (index < 0) return;
    if (!REC.insertAfter) REC.bannerBefore = REC.bannerMsg || '';
    REC.insertAfter = id;
    recBanner(`Запись после шага ${index + 1}. Пауза — вернуться в конец.`);
    if (!REC.on) recStart();
}

function recPush(step) {
    step.id = REC.nextId++;
    step.param = step.param || null;
    step.note = step.note || '';
    step.warn = step.warn || '';
    /* «Записать после этого шага»: новые шаги встают за выбранным и дальше
       друг за другом, а не в конец сюжета. */
    const at = REC.insertAfter ? REC.steps.findIndex(s => s.id === REC.insertAfter) : -1;
    if (at >= 0) {
        /* Запись внутри блока дописывает его. */
        const prev = REC.steps[at];
        step.parent = blockIsHead(prev) ? prev.id : (prev.parent ?? null);
        REC.steps.splice(at + 1, 0, step);
        REC.insertAfter = step.id;
    } else {
        REC.steps.push(step);
    }
    REC.lastAt = Date.now();
    recRender();
    recSave();
    return step;
}

/* Пауза перед действием — только если её явно попросили галкой: ctx.click()
   и так ждёт элемент до 10 секунд, автопаузы просто зашумили бы код. */
function recAutoPause() {
    if (!REC.pauses || !REC.lastAt) return;
    const gap = (Date.now() - REC.lastAt) / 1000;
    if (gap < REC_PAUSE_MIN_S) return;
    recPush({kind: 'sleep', args: {seconds: Math.round(gap * 2) / 2}});
}

/* Шаг click по узлу дампа — чистая часть recNoteTap, её же берёт починка шага
   (repair.js). Без id/param: их проставляет recPush. Селектор узла обязан быть
   кликабельным и не oversized — это проверяет вызывающий. */
/* Пометка способа поиска словами — рядом с каждым вариантом в «Как искать».
   Номер среди одинаковых («2-й из 3») — это и есть «нужен вот этот». */
function recSelMark(alt) {
    if (!alt || alt.matches == null) return '';
    const parts = [alt.nth ? t('rec.sel_nth', {k: alt.nth[0], n: alt.nth[1]})
        : alt.matches === 1 ? t('rec.sel_odin') : t('rec.sel_pohozhih', {n: alt.matches})];
    if (alt.dynamic) parts.push(t('rec.sel_menyaetsya'));
    return parts.join(' · ');
}

/* Предупреждение шага по выбранному способу. Шаг из файла (matches нет) —
   дампа того экрана нет, предупреждать не о чем. */
function recSelWarn(alt) {
    if (!alt || alt.matches == null) return '';
    const warns = [];
    if (alt.nth) {
        warns.push(t('rec.warn_nth', {k: alt.nth[0], n: alt.nth[1]}));
    } else {
        if (alt.matches !== 1) warns.push(t('rec.warn_mnogo', {n: alt.matches}));
        if (alt.fragile) warns.push(t('rec.warn_hrupkiy'));
    }
    if (alt.dynamic) warns.push(t('rec.warn_menyaetsya'));
    return warns.join('; ');
}

function recBuildClickStep(target, dump, point) {
    const selector = target.selectors[0];
    const warns = [recSelWarn(selector)].filter(Boolean);
    return {
        kind: 'click',
        args: {},
        selector: {call: selector.call, args: selector.args},
        alts: target.selectors,
        note: recNodeLabel(target),
        bounds: target.bounds,
        shot: dump.screenshot,
        texts: recTexts(target),
        point: point || recPoint(target.bounds),
        warn: warns.join('; '),
    };
}

function recNoteTap(payload) {
    const node = recHit(payload.x, payload.y);
    const target = node ? REC.dump.nodes[node.target] : null;
    const selector = target && (target.selectors || [])[0];

    recMaybeAnchor();

    /* oversized — цель размером с пол-экрана. Она уникальна, поэтому раньше
       писалась как обычный click и выглядела надёжной, но на прогоне такой
       клик бьёт в центр контейнера, а не туда, куда нажимал человек.
       Координаты в этом случае честнее селектора. */
    if (!selector || selector.call !== 'click' || selector.oversized) {
        const шаг = recPush({kind: 'tap', args: {x: payload.x, y: payload.y}});
        if (selector && selector.oversized) {
            шаг.warn = 'под пальцем контейнер во весь экран — записано нажатие в точку';
        } else {
            /* Раньше это ветвление ничего не писало в warn: голые координаты —
               самый хрупкий из возможных шагов (текст и картинку с этого узла
               взять неоткуда), а сообщал об этом интерфейс только у гораздо
               более безобидного oversized-случая выше. На динамических
               списках (подсказки поиска, сетка товаров) именно такой шаг
               чаще всего и промахивается на повторном прогоне — и раньше об
               этом узнавали только после прогона, а не во время записи. */
            шаг.warn = 'элемент не распознан — записано нажатие в точку, может промахнуться';
        }
        recRender();
        return;
    }
    const step = recPush(recBuildClickStep(target, REC.dump));
    recCropStep(step);
}

/* Отпечаток экрана: набор опознавательных знаков его узлов. Сравнивать сами
   дампы бесполезно — таймеры, счётчики и анимации меняют их постоянно. */
function recScreenSig(dump) {
    if (!dump || !dump.nodes) return null;
    const marks = [];
    dump.nodes.forEach(node => {
        const mark = node.resourceId || node.text || node.description;
        if (mark && marks.indexOf(mark) < 0) marks.push(mark);
    });
    return marks;
}

/* Экран считается новым, если сменилась большая часть опознавательных знаков.
   Порог, а не точное равенство: на одном и том же экране всегда что-то
   плывёт — время, бейдж уведомлений, подгрузившаяся картинка. */
function recScreenChanged(sig) {
    const was = REC.lastSig;
    if (!sig || !sig.length) return false;
    if (!was || !was.length) return true;
    const общих = sig.filter(mark => was.indexOf(mark) >= 0).length;
    return 1 - общих / Math.max(sig.length, was.length) >= REC_SCREEN_DIFF;
}

/* Признаки экрана для якоря: самые надёжные однозначные селекторы.
   resourceId устойчивее текста — он не меняется от локали. */
function recAnchorFeatures(dump) {
    const строгие = [];
    const прочие = [];
    (dump.nodes || []).forEach(node => {
        const sel = (node.selectors || [])[0];
        if (!sel || sel.call !== 'click' || sel.fragile || sel.dynamic || sel.matches !== 1) return;
        /* Системная панель есть на любом экране — якорь на ней ничего не проверяет. */
        if (/com\.android\.systemui|android:id\//.test(sel.args)) return;
        const куда = sel.args.indexOf('resourceId=') === 0 ? строгие : прочие;
        if (куда.indexOf(sel.args) < 0) куда.push(sel.args);
    });
    return строгие.concat(прочие).slice(0, REC_ANCHOR_MAX);
}

/* Поставить якорь, если экран сменился. Зовётся перед записью действия:
   якорь должен стоять ПЕРЕД первым действием на новом экране, иначе он
   проверяет экран уже после того, как по нему кликнули. */
/* Авто-проверки экрана — по желанию, по умолчанию выключены: экраны
   приложений меняются от обновления к обновлению, и проверка на каждом шаге
   роняла сценарий там, где он прошёл бы. Нужная проверка ставится руками
   («Проверка экрана»), там, где экран действительно важен. */
const REC_AUTO_ANCHOR_KEY = 'farm.recorder.autoAnchor';

function recAutoAnchorOn() {
    return !!store.get(REC_AUTO_ANCHOR_KEY, false);
}

function recAutoAnchorSet(on) {
    store.set(REC_AUTO_ANCHOR_KEY, on ? 1 : 0);
}

function recMaybeAnchor() {
    if (!REC.dump || !recAutoAnchorOn()) return;
    const sig = recScreenSig(REC.dump);
    if (!recScreenChanged(sig)) {
        if (sig) REC.lastSig = sig;
        return;
    }
    REC.lastSig = sig;
    const features = recAnchorFeatures(REC.dump);
    if (!features.length) return;  // опознать экран нечем — якорь был бы пустым
    REC.screenN += 1;
    recPush({
        kind: 'expect',
        args: {name: 'screen' + REC.screenN},
        any: features,
        shot: REC.dump.screenshot,
    });
}

/* ------------------------------------------------------------- развилка */

/* «Если на экране то-то — делай то». До развилки сюжет был прямолинейным:
   сценарий шёл одним путём и падал, если экран оказывался другим. На живой
   ферме это не так — один и тот же шаг встречает то онбординг, то пейволл,
   то сразу каталог.

   Ветка описывается тем же способом, что якорь (признаки экрана), а действие
   на ней — это блок, обычный записанный сценарий. Поэтому список шагов
   остаётся плоским: развилка — один шаг, а ветвление живёт в блоках, у
   которых уже есть и защита от рекурсии, и своя правка. */

/* Ветка описывает тот экран, который сейчас на устройстве. Поэтому и первая
   ветка, и каждая следующая добавляются с него же: перейдите на телефоне к
   нужному экрану и нажмите. */
async function recBranchArm() {
    if (!S.active) {
        toast('сначала выберите телефон', 'bad');
        return null;
    }
    await recLoadDump();
    if (!REC.dump) {
        toast('не удалось снять экран', 'bad');
        return null;
    }
    const features = recAnchorFeatures(REC.dump);
    if (!features.length) {
        toast('экран нечем опознать: на нём нет элементов, по которым его можно надёжно узнать', 'bad');
        return null;
    }
    return {name: recBranchName(REC.dump), any: features, run: ''};
}

/* Имя ветки — подсказка, а не истина: человек его тут же правит. Берём
   заголовок экрана, если он есть: «онбординг» узнаётся по нему, а не по
   resourceId. */
function recBranchName(dump) {
    const текст = (dump.nodes || [])
        .map(node => (node.text || '').trim())
        .find(t => t.length >= 3 && t.length <= 24);
    return текст || 'ветка';
}

async function recBranchHere() {
    const ветка = await recBranchArm();
    if (!ветка) return;
    REC.branchN = (REC.branchN || 0) + 1;
    const step = recPush({
        kind: 'branch',
        args: {name: 'развилка ' + REC.branchN},
        arms: [ветка],
        report: true,
        shot: REC.dump.screenshot,
    });
    REC.open = step.id;   // ветку без блока ставить незачем — раскрываем сразу
    recRender();
    toast(recFirstHint('branch',
        'Развилка поставлена. Выберите блок для этого экрана; другие ветки — со своих экранов.',
        'развилка поставлена — выберите блок для этой ветки'));
}

async function recBranchAdd(id) {
    const step = recFind(id);
    if (!step) return;
    if ((step.arms || []).length >= REC_ARMS_MAX) {
        toast(`больше ${REC_ARMS_MAX} ветвей в одной развилке не читается — `
            + 'разнесите по блокам', 'bad');
        return;
    }
    const ветка = await recBranchArm();
    if (!ветка) return;
    if (step.arms.some(a => a.name === ветка.name)) ветка.name += ' 2';
    step.arms.push(ветка);
    recRender();
    recSave();
    toast('ветка добавлена');
}

function recBranchDrop(id, index) {
    const step = recFind(id);
    if (!step || step.arms.length <= 1) {
        toast('в развилке должна остаться хотя бы одна ветка', 'bad');
        return;
    }
    step.arms.splice(index, 1);
    recRender();
    recSave();
}

function recBranchEdit(id, index, field, value) {
    const step = recFind(id);
    if (!step) return;
    const ветка = step.arms[index];
    if (!ветка) return;
    if (field === 'name') {
        /* Пустое имя сделало бы ветку неотличимой в коде и в журнале: по имени
           выбирается блок. Пустое поле означает «верни подсказку». */
        ветка.name = value.split('\n')[0].trim() || ('ветка ' + (index + 1));
    } else {
        ветка.run = value;
    }
    recSave();
    if (field === 'name') recRender();   // имя видно в предпросмотре кода
}

function recBranchRename(id, value) {
    const step = recFind(id);
    if (!step) return;
    step.args.name = value.split('\n')[0].trim() || 'развилка';
    recSave();
}

function recBranchReport(id, on) {
    const step = recFind(id);
    if (!step) return;
    step.report = !!on;
    recRender();
    recSave();
}

/* Блоки — обычные сценарии. Свой же сценарий в список не попадает: вызвать
   себя из себя нельзя, ctx.run это прямо запрещает. */
function recBranchBlocks(выбран) {
    const свой = REC.edit ? REC.edit.key : null;
    const живые = (S.scenarios || []).filter(s => s.key !== свой && !s.error);
    const опции = живые
        .map(s => `<option value="${esc(s.key)}" ${s.key === выбран ? 'selected' : ''}>`
            + `${esc(s.name)}</option>`).join('');
    /* Блок мог быть удалён после записи развилки. Без этой строки select не
       нашёл бы совпадения и показал бы первый вариант — «ничего не делать», —
       то есть соврал бы: в коде остаётся ctx.run на пропавший блок, и на
       прогоне он упадёт «блок не найден». */
    const пропал = выбран && !живые.some(s => s.key === выбран)
        ? `<option value="${esc(выбран)}" selected>«${esc(выбран)}» — блок не найден</option>`
        : '';
    return `<option value="" ${выбран ? '' : 'selected'}>— ничего не делать —</option>`
        + пропал + опции;
}

function recBranchEditor(step) {
    if (step.kind !== 'branch') return '';
    const ветки = (step.arms || []).map((arm, i) => {
        const признаки = (arm.any || [])
            .map(args => `<span class="rs-feat" title="${esc(args)}">${esc(recFeatText(args))}</span>`).join(' ');
        return `<div class="rs-arm">
      <div class="row">
        <input type="text" value="${esc(arm.name)}" placeholder="имя ветки"
               oninput="recBranchEdit(${step.id}, ${i}, 'name', this.value)">
        <select onchange="recBranchEdit(${step.id}, ${i}, 'run', this.value)">
          ${recBranchBlocks(arm.run)}
        </select>
        <button class="sm danger" title="Убрать ветку"
                onclick="recBranchDrop(${step.id}, ${i})">⌫</button>
      </div>
      <div class="rs-alts">опознаётся по: ${признаки}</div>
    </div>`;
    }).join('');

    return `<div class="row">
    <label>Подпись развилки</label>
    <input type="text" value="${esc(step.args.name || '')}"
           oninput="recBranchRename(${step.id}, this.value)">
  </div>
  ${ветки}
  <div class="row">
    <button class="sm accent" onclick="recBranchAdd(${step.id})"
            title="Перейдите на другой экран и нажмите">
      + ветка с текущего экрана</button>
  </div>
  <div class="row"><label class="kb"
      title="Снимите, если «ни одна» — штатный случай">
    <input type="checkbox" ${step.report === false ? '' : 'checked'}
           style="accent-color:var(--accent)"
           onchange="recBranchReport(${step.id}, this.checked)">
    жаловаться, если ни одна ветка не совпала</label></div>`;
}

/* --------------------------------------------------------------- схема */

/* Геометрия холста. Фиксированные пиксельные шаги, не проценты: карточки
   не тянутся под контент — длинная подпись обрезается многоточием (см.
   CSS), иначе рёбра, посчитанные по этим константам, разъехались бы с
   реальной высотой карточки. */
const GR_NODE_W_MIN = 190;  // узкая боковая панель: меньше подпись не читается
const GR_NODE_W_MAX = 380;  // шире карточка не нужна: подписи короче
const GR_NODE_H = 44;      // высота карточки хребта (шаг, экшен, якорь, развилка)
const GR_ARM_H = 54;       // высота карточки ветки (имя + блок/«ничего не делать»)
const GR_COL_X = 16;       // x хребта
const GR_ROW_H = 70;       // шаг между карточками хребта по вертикали
const GR_ARM_GAP = 60;     // просвет между карточкой развилки и дорожкой ветки
const GR_ARM_ROW_H = 66;   // шаг между дорожками одной развилки

/* Ширина карточки подстраивается под холст. Фиксированные 190px достались
   от узкой боковой панели: в полноэкранном режиме они оставляли 1300px
   пустоты справа, а подписи при этом резались многоточием. Ширина считается
   один раз за отрисовку и кладётся в layout — рёбра считаются из неё же,
   иначе линии разъехались бы с карточками. */
function grNodeW() {
    const host = $('recCanvas');
    /* Ширина холста в его собственных координатах: на уменьшенном масштабе
       видимого места больше, и карточки должны считаться от него, иначе
       «вписать» делало бы подписи вдвое короче, чем нужно. */
    const avail = host ? host.clientWidth / grZoom() : 0;
    if (!avail) return GR_NODE_W_MIN;
    /* 0.26 резало «Проверка экрана «scr…» на 25 символах — подписи шагов
       теперь словами, им нужно больше места. */
    /* На узком холсте (1280 рядом с экраном телефона) доля 0.36 давала
       минимальную карточку и резала подписи — там отдаём карточке больше. */
    const share = avail < 800 ? 0.6 : 0.36;
    return Math.max(GR_NODE_W_MIN, Math.min(Math.floor(avail * share), GR_NODE_W_MAX));
}
/* Цвет дорожки по индексу ветки — столько же оттенков, сколько ARMS_MAX
   в steps.py: развилка на 5 ветвей — предел и в бэкенде, и здесь. */
const GR_LANES = ['#6dc4ff', '#ffcf5c', '#ff9f6b', '#8fe3a0', '#d99bff'];

/* Раскладка холста: позиция каждой карточки хребта плюс дорожек развилки.
   Карточка без сохранённой step.pos встаёт в поток — следующей вниз по
   хребту от той точки, на которой остановилась предыдущая (в том числе
   перетащенная руками). Так ручная правка одной карточки не спорит с
   автоматической раскладкой всех, что идут после неё. */
function grLayout() {
    const pos = new Map();     // stepId -> {x, y}, карточки хребта
    const arms = new Map();    // stepId -> [{x, y}, ...], параллельно step.arms
    const nodeW = grNodeW();
    const armX = nodeW + GR_ARM_GAP;
    let y = 16;
    let maxX = GR_COL_X + nodeW;

    REC.steps.forEach(step => {
        const here = step.pos ? {x: step.pos[0], y: step.pos[1]}
            : {x: GR_COL_X + blockDepth(step) * GR_BLOCK_INDENT, y};
        pos.set(step.id, here);

        let blockHeight = GR_ROW_H;
        if (step.kind === 'branch') {
            const armList = (step.arms || []).map((arm, i) => ({
                x: here.x + armX,
                y: here.y + i * GR_ARM_ROW_H,
            }));
            arms.set(step.id, armList);
            const armSpan = armList.length
                ? (armList.length - 1) * GR_ARM_ROW_H + GR_ARM_H
                : 0;
            blockHeight = Math.max(GR_ROW_H, armSpan + GR_ROW_H - GR_NODE_H);
            maxX = Math.max(maxX, here.x + armX + nodeW);
        }
        y = here.y + blockHeight;
        maxX = Math.max(maxX, here.x + nodeW);
    });

    return {pos, arms, nodeW, width: maxX + 40, height: y + 40};
}

/* Карточка шага хребта. Ручка ⠿ — отдельный элемент: тащим за неё
   (перетаскивание), а клик по телу карточки открывает шаг в списке — то
   же разделение, что у строк списка (recRow), и по той же причине:
   внутри раскрытой карточки будут поля ввода, и перетаскивание за
   произвольное место отнимало бы у них выделение текста. */
/* Иконка из спрайта frontend/icons.svg — тот же <svg class="ic"><use></svg>,
   что у обычных кнопок, только с классом gr-icon под размер карточки. */
function grIcon(id) {
    return `<svg class="ic gr-icon" aria-hidden="true"><use href="#i-${id}"/></svg>`;
}

/* Тот же спрайт, но без gr-icon: та задаёт цвет акцентом, и внутри красной
   кнопки «Удалить» значок вышел бы зелёным, споря с её смыслом. Здесь цвет
   наследуется от кнопки или строки. */
function recIcon(id) {
    return `<svg class="ic" aria-hidden="true"><use href="#i-${id}"/></svg>`;
}

/* Номер на карточке — тот же, что в «Списке»: без него два вида одного
   сюжета невозможно сопоставить глазами, а «шаг 12 упал» из журнала не с
   чем сличить на холсте. */
function grNode(step, xy, index, nodeW) {
    const [cls, iconId] = schIcon(step);
    return `<div class="gr-node ${cls}" style="left:${xy.x}px;top:${xy.y}px;width:${nodeW}px" data-id="${step.id}">
      <span class="gr-grip" title="Перетащите карточку" onpointerdown="grDragStart(event, ${step.id})">${grIcon('grip')}</span>
      <button class="gr-body" onclick="schOpenStep(${step.id})" title="Открыть шаг в списке">
        <span class="gr-n">${index + 1}</span>
        ${grIcon(iconId)}<span class="gr-label">${esc(schLabel(step))}</span>
      </button>
      <button class="gr-try" onclick="recRunStep(${index})"
              title="Проверить этот шаг на телефоне" aria-label="Проверить шаг ${index + 1}">${grIcon('play')}</button>
    </div>`;
}

/* Карточка ветки развилки: блок (кликабелен — открывает его в
   конструкторе), «ничего не делать» или «блок не найден» (пропал после
   записи развилки — молчать нельзя, иначе на прогоне ctx.run упадёт
   далеко отсюда). Позиция не хранится — считается в grLayout()
   относительно родительской развилки. */
function grArmNode(arm, index, xy, nodeW, parentId) {
    const цвет = GR_LANES[index % GR_LANES.length];
    const блок = (S.scenarios || []).find(s => s.key === arm.run);
    let inner, extra = '';
    if (!arm.run) {
        inner = '<span class="gr-arm-empty">ничего не делать</span>';
        extra = 'ghost';
    } else if (!блок) {
        inner = `<span class="gr-arm-lost">блок «${esc(arm.run)}» не найден</span>`;
        extra = 'missing';
    } else {
        inner = `<button class="gr-arm-block" onclick="schOpenBlock('${esc(arm.run)}')"
                   title="Открыть блок в конструкторе">${grIcon('external')} ${esc(блок.name)}</button>`;
    }
    return `<div class="gr-node gr-arm ${extra}" data-arm-of="${parentId}"
         style="left:${xy.x}px;top:${xy.y}px;width:${nodeW}px;border-left-color:${цвет}">
      <div class="gr-arm-name" style="color:${цвет}">${esc(arm.name)}</div>
      ${inner}
    </div>`;
}

/* Кривая между двумя точками: пологая при горизонтальной связи (развилка
   → ветка), почти прямая при вертикальной (шаг → следующий шаг). Один и
   тот же кубический безье справляется с обоими — не нужно две формулы. */
function grEdgePath(x1, y1, x2, y2, color) {
    const midX = (x1 + x2) / 2;
    return `<path d="M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}"
      fill="none" stroke="${color}" stroke-width="2"/>`;
}

/* Рёбра холста: хребет — нейтральным цветом, дорожки развилки — цветом
   своей дорожки от развилки до карточки ветки и от карточки ветки до
   следующего шага хребта. Место слияния веток нигде не хранится отдельной
   сущностью: это просто следующий шаг в REC.steps, и все ветки рисуют
   ребро туда же — так же, как codegen.py безусловно эмитит его после
   развилки для любой сработавшей ветки. */
function grEdges(layout) {
    const parts = [];
    const nodeW = layout.nodeW;
    for (let i = 0; i < REC.steps.length; i++) {
        const step = REC.steps[i];
        const xy = layout.pos.get(step.id);
        const next = REC.steps[i + 1];

        if (step.kind === 'branch') {
            const armXY = layout.arms.get(step.id) || [];
            armXY.forEach((axy, ai) => {
                const цвет = GR_LANES[ai % GR_LANES.length];
                parts.push(grEdgePath(
                    xy.x + nodeW, xy.y + GR_NODE_H / 2,
                    axy.x, axy.y + GR_ARM_H / 2, цвет));
                if (next) {
                    const nxy = layout.pos.get(next.id);
                    parts.push(grEdgePath(
                        axy.x + nodeW, axy.y + GR_ARM_H / 2,
                        nxy.x + nodeW / 2, nxy.y, цвет));
                }
            });
        } else if (next) {
            const nxy = layout.pos.get(next.id);
            parts.push(grEdgePath(
                xy.x + nodeW / 2, xy.y + GR_NODE_H,
                nxy.x + nodeW / 2, nxy.y, '#3a4256'));
        }
    }
    return parts.join('');
}

/* Холст целиком: SVG с рёбрами под карточками (pointer-events:none — клики
   и перетаскивание обязаны доходить до карточек, не до линий), сверху —
   карточки хребта и веток. Ширина/высота — инлайн из раскладки: контейнер
   с абсолютно позиционированными детьми сам себя не размеряет, а скролл
   внешней панели (#recScheme.scroll) должен знать, докуда прокручивать. */
/* Один текст на оба вида: «Схема» и «Список» пусты по одной причине, и
   две разные формулировки на одном и том же месте читались бы как два
   разных состояния. Кнопка ведёт туда же, куда «● Запись» в шапке. */
function recEmptySteps() {
    return emptyBig({
        art: 'steps',
        title: t('rec.pusto_title'),
        text: t('rec.pusto_text'),
    });
}

function grRender() {
    if (!REC.steps.length) {
        return recEmptySteps();
    }
    const layout = grLayout();
    const edges = grEdges(layout);
    const nodes = REC.steps.map((step, index) => {
        const xy = layout.pos.get(step.id);
        let html = grNode(step, xy, index, layout.nodeW);
        if (step.kind === 'branch') {
            const armXY = layout.arms.get(step.id) || [];
            html += (step.arms || [])
                .map((arm, i) => grArmNode(arm, i, armXY[i], layout.nodeW, step.id))
                .join('');
        }
        return html;
    }).join('');
    return `<div class="gr-canvas" style="width:${layout.width}px;height:${layout.height}px">
      <svg class="gr-edges" width="${layout.width + 40}" height="${layout.height}">${grBlockFrames(layout)}${edges}</svg>
      ${nodes}
    </div>`;
}

/* Перетаскивание карточки хребта. Не HTML5 DnD (тот снап-based — годится
   для смены порядка в списке, но не для произвольных x,y) и не глобальные
   слушатели на document — Pointer Events с setPointerCapture: элемент сам
   получает все move/up, даже если курсор уйдёт с карточки во время тяги.

   Рёбра и ветки развилки едут вместе с карточкой: на каждый кадр
   (requestAnimationFrame, не каждый pointermove — их бывает больше 60 в
   секунду) step.pos временно ставится в текущую точку, grLayout()/grEdges()
   пересчитывают только SVG и позиции веток этой карточки. Линии, которые
   стоят на месте и запрыгивают на отпускании, читались как поломка.
   Полный перерендер (recSchemeSpine) — по-прежнему на отпускании. */
function grDragStart(ev, id) {
    ev.preventDefault();
    const host = ev.target.closest('.gr-node');
    if (!host) return;
    const startX = ev.clientX, startY = ev.clientY;
    const baseLeft = host.offsetLeft, baseTop = host.offsetTop;

    host.setPointerCapture(ev.pointerId);
    host.classList.add('dragging');

    /* Курсор ходит по экрану, карточка живёт в координатах сюжета: на
       масштабе 50% сдвиг мыши на 100px обязан двигать её на 200. */
    const zoom = grZoom();
    /* Ноль — левый верхний край полотна: за него карточку не пускаем,
       иначе она уезжает туда, куда холст не прокручивается. */
    const at = e => [
        Math.max(0, Math.round(baseLeft + (e.clientX - startX) / zoom)),
        Math.max(0, Math.round(baseTop + (e.clientY - startY) / zoom)),
    ];

    const step = recFind(id);
    const canvas = host.parentElement;
    const svg = canvas.querySelector('.gr-edges');
    let frame = 0, last = null;

    /* Блоки без сохранённой позиции стоят «под предыдущим», и сдвиг одного
       тянул за собой весь хвост сюжета. Перед перетаскиванием закрепляем
       текущее место каждого — двигается только тот, кого тянут. */
    const pinned = grLayout();
    REC.steps.forEach(st => {
        if (st.pos || st === step) return;
        const xy = pinned.pos.get(st.id);
        if (xy) st.pos = [xy.x, xy.y];
    });

    /* Шаги без сохранённой позиции стоят под предыдущим (grLayout), так
       что двигаются не только тащимая карточка и её ветки — раскладку
       применяем ко всем карточкам, иначе линии разойдутся с ними. */
    function place(el, xy) {
        if (!el || !xy) return;
        el.style.left = xy.x + 'px';
        el.style.top = xy.y + 'px';
    }
    function paint() {
        frame = 0;
        if (!step || !svg) {
            place(host, {x: last[0], y: last[1]});
            return;
        }
        step.pos = last;
        const layout = grLayout();
        svg.innerHTML = grEdges(layout);
        canvas.querySelectorAll('.gr-node[data-id]').forEach(el =>
            place(el, layout.pos.get(Number(el.dataset.id))));
        layout.arms.forEach((list, parentId) => {
            const els = canvas.querySelectorAll(`[data-arm-of="${parentId}"]`);
            list.forEach((xy, i) => place(els[i], xy));
        });
    }
    function onMove(e) {
        last = at(e);
        if (!frame) frame = requestAnimationFrame(paint);
    }
    function onUp(e) {
        host.removeEventListener('pointermove', onMove);
        host.removeEventListener('pointerup', onUp);
        if (frame) cancelAnimationFrame(frame);
        host.classList.remove('dragging');
        if (step) {
            step.pos = at(e);
            recSave();
        }
        recSchemeSpine();
    }
    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerup', onUp);
}

/* Значок шага на холсте — id иконки из спрайта (frontend/icons.svg), не
   юникод-символ: значки на узлах опознают тип шага так же, как кнопки
   «Якорь экрана»/«Развилка» — одна иконка = один смысл во всём
   конструкторе, а не набор символов, которые надо запоминать отдельно. */
/* Свой значок на каждый вид шага. Раньше всё, кроме развилки, якоря и
   запуска, сводилось к одной «молнии» — а это 11 из 15 видов: тап, свайп,
   ввод текста, пауза, shell. Сюжет из восемнадцати шагов читался как
   восемнадцать одинаковых строк, и глазу не за что было зацепиться. */
const SCH_ICONS = {
    branch: ['branch', 'branch'],
    loop: ['loop', 'rotate'],
    chance: ['chance', 'dice'],
    until: ['until', 'search'],
    if_seen: ['until', 'eye-off'],
    break: ['block', 'stop'],
    finish: ['block', 'check'],
    call: ['block', 'layers'],
    expect: ['anchor', 'crosshair'],
    launch_app: ['block', 'play'],
    stop_app: ['block', 'stop'],
    open_url: ['block', 'external'],
    shell: ['block', 'terminal'],
    sleep: ['block', 'pause'],
    screenshot: ['block', 'image'],
    type: ['', 'keyboard'],
    key: ['', 'enter'],
    unlock: ['', 'unlock'],
    swipe: ['', 'scroll'],
};

function schIcon(step) {
    return SCH_ICONS[step.kind] || ['', 'zap'];   // click / tap / long_tap
}

/* Подпись узла на хребте. У развилки она короче, чем в списке шагов: имена
   ветвей стоят дорожками прямо под ней, и повторять их в подписи значило бы
   дважды сказать одно и то же в двух строках подряд. */
function schLabel(step) {
    if (step.kind === 'branch') return `Развилка «${step.args.name}»`;
    return recLabel(step);
}

function schOpenStep(id) {
    recSetView('list');
    REC.open = id;
    recRender();
    const row = document.querySelector('#recSteps .rs.open');
    if (row) row.scrollIntoView({block: 'center', behavior: 'smooth'});
}

/* Блок — обычный сценарий, поэтому «открыть» значит «открыть на правку», а
   если рецепта нет (написан руками) — хотя бы выбрать его в списке. */
function schOpenBlock(key) {
    const блок = (S.scenarios || []).find(s => s.key === key);
    if (блок && блок.editable) {
        editScenario(key);
        return;
    }
    showView('scen');
    pickScenario(key);
    if (блок) toast('этот блок написан руками — правьте его в редакторе');
}

/* Знакомые системные экраны зовём по имени. Ферма подписывает преграду
   текстами, которые сумела прочитать, и для этих случаев получается
   бессмыслица: на рабочем столе это список ярлыков, на заблокированном
   экране — одни часы. Пакет знает правду, тексты — нет. */
const SCH_KNOWN = [
    [/launcher|nexuslauncher|\.home$/i, 'Рабочий стол', 'сценарий вышел из приложения'],
    [/permissioncontroller/i, 'Запрос разрешения', 'системный диалог доступа'],
    [/systemui/i, 'Системное окно', 'шторка, громкость или диалог Android'],
    [/packageinstaller/i, 'Установка приложения', 'диалог установки или обновления'],
];

/* Текст-пустышка: часы, дата, проценты заряда. Такие подписи ничего не
   говорят о том, куда уткнулся сценарий, и в заголовок их пускать нельзя. */
function schJunkText(t) {
    return /^\d{1,2}:\d{2}$/.test(t)                 // 17:02
        || /^\d{1,3}\s*%$/.test(t)                   // 84 %
        || /^[А-Яа-яA-Za-z]{2},?\s*\d{1,2}\s/.test(t); // Вс, 13 сент.
}

function schObstacleLabel(o) {
    const пакет = o.package || '';
    const известный = SCH_KNOWN.find(([re]) => re.test(пакет));
    if (известный) return {title: известный[1], hint: известный[2]};

    const тексты = (o.texts || []).filter(t => t && !schJunkText(t));
    if (тексты.length) {
        return {title: тексты.slice(0, 2).join(' · '), hint: пакет};
    }
    /* Ни одного осмысленного текста — значит опознать экран нечем, и
       честнее сказать это прямо, чем показать «17:02» как название. */
    return {title: 'Экран без читаемого текста', hint: пакет};
}

function schSide(карта) {
    const отводы = (карта.rules || []).filter(r => r.action && r.action.run);
    const дыры = карта.obstacles || [];

    const строкиОтводов = отводы.length
        ? отводы.map(r => `<div class="sch-rule">
             <svg class="ic" aria-hidden="true"><use href="#i-shield"/></svg>
             <span class="sch-gap-txt">
               <b>${esc(r.name)}</b>
               <span class="sch-gap-sub">запускает блок «${esc(r.action.run)}»</span>
             </span>
             <span class="sp"></span>
             ${r.source === 'global'
            ? '<span class="sch-hits">на всех приложениях</span>' : ''}
           </div>`).join('')
        : `<div class="sch-empty">
             <svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>
             <span>Пока нет. Покажите ферме раз, как закрыть окно, — дальше сама.</span></div>`;

    /* «Обошли вслепую» показываем отдельно от «уронили»: по журналу задач
       первого не видно вообще — прогоны доезжают, — и без этой пометки
       преграда выглядит безобидной. */
    const строкиДыр = дыры.length
        ? дыры.map(o => {
            const {title, hint} = schObstacleLabel(o);
            /* Счётчик и кнопка — одной группой у правого края. Порознь
               (счётчик сразу за подписью, кнопка через распорку) между
               ними зияла пустота во всю строку, и глазу приходилось
               прыгать через неё, чтобы связать «×1» с «научить». */
            const встречи = `${o.hits} ${declOfNum(o.hits,
                ['встреча', 'встречи', 'встреч'])}`;
            return `<div class="sch-gap">
             <svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>
             <span class="sch-gap-txt">
               <b>${esc(title)}</b>
               ${hint ? `<span class="sch-gap-sub">${esc(hint)}</span>` : ''}
             </span>
             <span class="sp"></span>
             <span class="sch-hits tnum">${встречи}${o.escapes
                ? ` · вслепую ${o.escapes}` : ''}</span>
             <button class="sm" onclick="teachDetour('${esc(o.job || '')}',
                     '${esc(o.file || '')}')"
                     ${o.job ? '' : 'disabled'}>научить обходить</button></div>`;
        }).join('')
        : `<div class="sch-empty">
             <svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>
             <span>Чисто: незнакомых экранов не было.</span></div>`;

    /* Тот же концепт преград виден и на вкладке «Отклонения» — но по всей
       ферме и по всем пакетам, а не только по этому. Разные срезы одних и
       тех же данных должны знать друг о друге, а не выглядеть как две
       разные фичи. */
    /* Счётчик в заголовке — чтобы свёрнутый подвал можно было оценить, не
       разворачивая: «преград 2» видно сразу, а список уже по желанию. */
    const счёт = n => n
        ? `<span class="sch-count">${n}</span>`
        : '<span class="sch-count ok">0</span>';

    /* Шапка карточки — div, а не <header>: в layout.css есть правило на
       голый тег header (это шапка приложения, display:flex), и оно ловит
       любой header на странице. Внутри карточки из-за него заголовок и
       пояснение вставали в строку вместо друг друга. */
    return `<section class="sch-side">
      <div class="sch-side-head">
        <h4>Закрываются сами ${счёт(отводы.length)}</h4>
        <p>Окна, которые ферма закрывает сама.</p>
      </div>
      ${строкиОтводов}
    </section>
    <section class="sch-side">
      <div class="sch-side-head">
        <h4>Мешают сценарию ${счёт(дыры.length)}
          <button class="sch-side-link" onclick="showView('deviations')"
                  title="Все помехи фермы">
            все по ферме →</button></h4>
        <p>Экраны, которые ферма ещё не умеет обходить.</p>
      </div>
      ${строкиДыр}
    </section>`;
}

/* Схема — постоянная панель, а не модалка: растёт по мере кликов по экрану
   устройства, а не открывается по отдельной команде. Холст (grRender)
   рисуем сразу и бесплатно — он строится из REC.steps на месте. Боковая
   часть (schSide — отводы и непокрытые преграды) требует сетевого похода
   за /api/detours и обновляется реже: на переключении вида и после
   заметных изменений записи, а не на каждый клик подряд. */
function recSetView(name) {
    REC.view = name;
    $('recScheme').hidden = name !== 'scheme';
    $('recSteps').hidden = name !== 'list';
    /* Масштабировать нечего, пока смотрят список: кнопки, которые ни на
       что не влияют, читаются как сломанные. */
    const zoom = $('recZoom');
    if (zoom) zoom.hidden = name !== 'scheme';
    document.querySelectorAll('#recViewToggle .chip[data-view]').forEach(chip => {
        const on = chip.dataset.view === name;
        chip.classList.toggle('on', on);
        chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    /* Пока схема была скрыта, её могли перерисовать (правка в списке) —
       тогда ширина карточек посчиталась от нулевого холста и осталась
       минимальной: ResizeObserver этого не видит, ширина-то не менялась. */
    if (name === 'scheme') {
        recSchemeSpine();
        recSchemeRefresh();
    }
}

/* --------------------------------------------------- масштаб холста

   Развилка на пять веток шире любой панели: без масштаба её концы просто
   уходили за край, и «посмотреть сюжет целиком» было нечем. Масштаб —
   transform на полотне, а не пересчёт координат: карточки хранят свои
   x,y в координатах сюжета, и ни раскладка, ни рёбра о зуме не знают. */
const GR_ZOOM_MIN = 0.3;
const GR_ZOOM_MAX = 2;
const GR_ZOOM_STEP = 1.2;
const GR_FIT_PAD = 32;

function grZoom() {
    return REC.zoom || 1;
}

function grZoomSet(value, anchor) {
    const view = $('recCanvas');
    const было = grZoom();
    const стало = Math.min(GR_ZOOM_MAX, Math.max(GR_ZOOM_MIN, value));
    if (стало === было) return;
    REC.zoom = стало;

    /* Точка под курсором (или центр окна) обязана остаться на месте:
       иначе зум колесом уводит взгляд с той карточки, к которой
       присматривались. */
    let keepX = 0, keepY = 0;
    if (view) {
        keepX = anchor ? anchor.x : view.clientWidth / 2;
        keepY = anchor ? anchor.y : view.clientHeight / 2;
    }
    const worldX = view ? (view.scrollLeft + keepX) / было : 0;
    const worldY = view ? (view.scrollTop + keepY) / было : 0;

    /* Карточки считают свою ширину от видимого места (grNodeW), поэтому
       холст перерисовывается целиком, а не только масштабируется. */
    recSchemeSpine();

    if (view) {
        view.scrollLeft = worldX * стало - keepX;
        view.scrollTop = worldY * стало - keepY;
    }
}

function grZoomBy(direction) {
    grZoomSet(direction > 0 ? grZoom() * GR_ZOOM_STEP : grZoom() / GR_ZOOM_STEP);
}

/* «Вписать» никогда не увеличивает: сюжет из трёх шагов, растянутый на
   двести процентов, читается как ошибка вёрстки, а не как помощь. */
function grZoomFit() {
    const view = $('recCanvas');
    if (!view || !REC.steps.length) return;
    const layout = grLayout();
    const scale = Math.min(
        (view.clientWidth - GR_FIT_PAD) / layout.width,
        (view.clientHeight - GR_FIT_PAD) / layout.height,
        1);
    grZoomSet(scale);
    view.scrollTo({left: 0, top: 0});
}

function grZoomSync() {
    const label = $('btnZoomLevel');
    if (label) setText(label, Math.round(grZoom() * 100) + '%');
}

function recSchemeSpine() {
    const box = document.querySelector('#recScheme .sch-spine');
    if (!box) return;
    box.innerHTML = grRender();
    const canvas = box.querySelector('.gr-canvas');
    const zoom = grZoom();
    if (canvas) {
        canvas.style.transform = `scale(${zoom})`;
        /* Размер полотна несёт обёртка: у масштабированного элемента
           прокрутка считается по исходной ширине, и уменьшенный сюжет
           оставлял бы за собой пустую полосу в полэкрана. */
        box.style.width = Math.round(canvas.offsetWidth * zoom) + 'px';
        box.style.height = Math.round(canvas.offsetHeight * zoom) + 'px';
    } else {
        box.style.width = '';
        box.style.height = '';
    }
    grZoomSync();
}

/* Колесо с Ctrl/⌘ — масштаб, без него — обычная прокрутка холста: тот же
   уговор, что в картах и редакторах схем, переучивать незачем. */
function grWheel(ev) {
    if (!ev.ctrlKey && !ev.metaKey) return;
    ev.preventDefault();
    const view = $('recCanvas');
    const rect = view.getBoundingClientRect();
    const anchor = {x: ev.clientX - rect.left, y: ev.clientY - rect.top};
    grZoomSet(ev.deltaY < 0 ? grZoom() * GR_ZOOM_STEP : grZoom() / GR_ZOOM_STEP, anchor);
}

/* Панорама: тянем пустое место холста. Карточка тащится сама (grDragStart
   гасит событие), поэтому проверка одна — что под курсором не она. */
function grPanStart(ev) {
    const view = $('recCanvas');
    if (!view || ev.button !== 0) return;
    if (ev.target.closest('.gr-node')) return;
    const startX = ev.clientX, startY = ev.clientY;
    const baseLeft = view.scrollLeft, baseTop = view.scrollTop;

    view.setPointerCapture(ev.pointerId);
    view.classList.add('panning');

    function onMove(e) {
        view.scrollLeft = baseLeft - (e.clientX - startX);
        view.scrollTop = baseTop - (e.clientY - startY);
    }
    function onUp() {
        view.removeEventListener('pointermove', onMove);
        view.removeEventListener('pointerup', onUp);
        view.classList.remove('panning');
    }
    view.addEventListener('pointermove', onMove);
    view.addEventListener('pointerup', onUp);
}

/* Боковая часть дёргает сеть — не чаще раза в 400мс, даже если recRender()
   зовётся на каждый клик подряд: иначе активная запись била бы по
   /api/detours с той же частотой, что и по экрану устройства. */
/* Панель «Всплывающие окна» живёт под списком, а не на схеме: грузим её,
   только пока она открыта — закрытую никто не читает. */
function recSchemeRefresh() {
    const side = $('recSide');
    if (!side || !side.open) return;
    clearTimeout(REC.schemeTimer);
    REC.schemeTimer = setTimeout(recSchemeSideLoad, REC_REFRESH_MS);
}

function recSideOpen() {
    const side = $('recSide');
    if (!side) return;
    side.open = true;
    recSchemeSideLoad();
    side.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

async function recSchemeSideLoad() {
    const side = document.querySelector('#recSide .sch-side-wrap');
    if (!side) return;
    let карта = {rules: [], obstacles: []};
    try {
        const пакет = (REC.teach && REC.teach.package) || recGuessPackage();
        карта = await api('/api/detours' + (пакет ? `?package=${encodeURIComponent(пакет)}` : ''));
    } catch (e) {
        /* Фоновый автообновление, не явное действие: со времён, когда схема
           открывалась отдельной командой, это был toast('bad'), но теперь
           recSchemeSideLoad зовётся после каждого шага записи — упавший
           /api/detours стал бы стопкой одинаковых красных тостов. Тихо
           молчим: панель просто не обновится, человек занят записью, а не
           ждёт эти данные. */
        console.warn('список автозакрытий недоступен:', e.message);
        return;
    }
    /* Зовётся после каждого шага записи — тот же список не пересобираем. */
    setHTML(side, schSide(карта));
}

/* Пакет берём из шага запуска приложения: отводы хранятся по пакетам, и
   показывать чужие незачем. */
function recGuessPackage() {
    const step = REC.steps.find(s => s.kind === 'launch_app');
    return step ? (step.args.package || '') : '';
}

/* ------------------------------------------------------------- обучение */

/* Сценарий упал на незнакомом экране. Условие («как узнать эту преграду»)
   ферма сняла в момент падения — устройство к этому времени уже могла
   забрать следующая задача. Человек показывает только действие: как выйти.
   Поэтому здесь мы берём слепок из задачи, а шаги пишем заново, вживую. */
async function teachDetour(jobId, file) {
    let слепок;
    try {
        /* Слепков у задачи несколько: один от падения и по одному на каждый
           экран, обойдённый вслепую. Имя приходит из тревоги. */
        const имя = file ? `?name=${encodeURIComponent(file)}` : '';
        слепок = await api(`/api/jobs/${jobId}/obstacle${имя}`);
    } catch (e) {
        toast('снимок окна недоступен: ' + e.message, 'bad');
        return;
    }
    /* Запуск ещё ждёт на этом экране — после «Сохранить» он продолжится сам. */
    const held = (S.jobs || []).find(j => j.id === jobId && j.status === 'held');
    if (held) слепок.resume = jobId;
    if (!(слепок.candidates || []).length) {
        if (held) {
            openDevice(held.serial);
            toast('экран нечем запомнить — поправьте его и нажмите «я поправил — продолжить»', 'bad');
            return;
        }
        toast('окно нечем узнать: на экране не было надёжных признаков', 'bad');
        return;
    }
    const начатьОбучение = async () => {
        if (слепок.serial && S.active !== слепок.serial) openDevice(слепок.serial);

        REC.steps = [];              // учим обходить, а не дописываем чужой сценарий
        REC.params = {};
        REC.nextId = 1;
        REC.teach = слепок;
        recOpen(true);   // шаги уже обнулены — черновик предлагать незачем
        await recStart();
        recRender();
        const где = (слепок.texts || []).slice(0, 2).join(' · ') || слепок.package;
        recBanner(слепок.resume
            ? `запуск ждёт: ${где}. Покажите, что делать, и «Сохранить» — запуск продолжится.`
            : `учим закрывать окно: ${где}. Покажите, как закрыть, и «Сохранить автозакрытие».`);
        recSync();
    };

    /* Кнопка «научить» теперь всегда на виду в боковой панели схемы — один
       случайный клик стирает активную запись без предупреждения, если её не
       остановить здесь. */
    if (REC.steps.length) {
        confirmModal('Научить ферму закрывать это окно?',
            `<p>Шаги в конструкторе (${REC.steps.length}) будут стёрты.</p>`,
            'Стереть и учить', начатьОбучение, true);
        return;
    }
    начатьОбучение();
}

/* Якорь вручную. Автоматика ставит якорь только при заметной смене экрана и
   только перед кликом — а проверить, где мы находимся, бывает нужно и там,
   где она промолчала: после запуска приложения, после свайпа внутри одного
   экрана, перед длинным блоком ввода. */
async function recAnchorHere() {
    if (!S.active) {
        toast('сначала выберите телефон', 'bad');
        return;
    }
    /* Дамп мог устареть после последнего действия, а якорь описывает экран
       «прямо сейчас» — берём свежий, иначе зафиксируем прошлый экран. */
    await recLoadDump();
    if (!REC.dump) {
        toast('не удалось снять экран', 'bad');
        return;
    }
    const features = recAnchorFeatures(REC.dump);
    if (!features.length) {
        toast('экран нечем опознать: на нём нет элементов, по которым его можно надёжно узнать', 'bad');
        return;
    }
    REC.lastSig = recScreenSig(REC.dump);   // чтобы автоматика не задвоила якорь
    REC.screenN += 1;
    const step = recPush({
        kind: 'expect',
        args: {name: 'screen' + REC.screenN},
        any: features,
        shot: REC.dump.screenshot,
    });
    REC.open = step.id;   // раскрываем сразу: имя экрана осмысленно задать здесь же
    recRender();
    toast(recFirstHint('anchor',
        'Проверка экрана добавлена: сценарий сверит, что дошёл сюда. Задайте имя экрана.',
        'проверка экрана добавлена — задайте имя экрана'));
}

/* Тексты цели для слоёв «текст по дереву» и OCR: на другой прошивке или
   локали селектор не совпадёт, а подпись кнопки чаще всего та же. */
function recTexts(target) {
    const seen = [];
    /* Счётчик или время («125», «12:45») к следующему прогону станет другим:
       искать по нему текстом — найти чужой элемент или ничего. */
    [target.textDynamic ? '' : target.text,
        target.descriptionDynamic ? '' : target.description].forEach(raw => {
        const value = (raw || '').trim();
        if (value && seen.indexOf(value) < 0) seen.push(value);
    });
    return seen.slice(0, REC_TEXTS_MAX);
}

/* Центр рамки — последний резерв резолвера, когда не сработало ничего. */
function recPoint(bounds) {
    if (!bounds) return null;
    const round = v => Math.round(v * 1e4) / 1e4;
    return [round((bounds[0] + bounds[2]) / 2), round((bounds[1] + bounds[3]) / 2)];
}

/* Кроп цели для слоя поиска по картинке — единственный слой, работающий там,
   где дерева нет вовсе (WebView, SurfaceView, игры).

   Декодирование скриншота асинхронное, поэтому кроп досыпается в уже
   добавленный шаг: запись не должна ждать раскодирования JPEG, иначе тап
   и шаг разъедутся во времени. */
function recCropStep(step) {
    if (!step.shot || !step.bounds) return;
    const img = new Image();
    img.onload = () => {
        const [x1, y1, x2, y2] = step.bounds;
        const sw = Math.round((x2 - x1) * img.naturalWidth);
        const sh = Math.round((y2 - y1) * img.naturalHeight);
        if (sw < REC_CROP_MIN_PX || sh < REC_CROP_MIN_PX) return;
        const data = recCropData(
            img, x1 * img.naturalWidth, y1 * img.naturalHeight, sw, sh, 1);
        if (!data) return;
        step.crop = data;
        recRender();
        recSave();
    };
    img.onerror = () => { /* кроп необязателен: остальные слои работают без него */ };
    img.src = step.shot;
}

/* Не влез в потолок бэкенда — режем вдвое и пробуем снова. Не помогло —
   шаг остаётся без картинки, это не ошибка записи. */
function recCropData(img, sx, sy, sw, sh, scale) {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(sw * scale));
    canvas.height = Math.max(1, Math.round(sh * scale));
    canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    const data = (canvas.toDataURL('image/png').split(',')[1] || '');
    if (data.length * 0.75 <= REC_CROP_MAX_BYTES) return data;
    return scale > 0.25 ? recCropData(img, sx, sy, sw, sh, scale / 2) : '';
}

/* Живая клавиатура шлёт по символу — иначе «qwerty» это шесть строк кода. */
function recNoteType(payload) {
    const last = REC.steps[REC.steps.length - 1];
    if (last && last.kind === 'type' && !payload.clear && !last.args.clear) {
        last.args.value += payload.value;
        recRender();
        recSave();
        REC.lastAt = Date.now();
        return;
    }
    recPush({kind: 'type', args: {value: payload.value, clear: !!payload.clear}});
}

function recArgs(kind, p) {
    switch (kind) {
        case 'long_tap':
            return {x: p.x, y: p.y, duration: p.duration || 0.8};
        case 'swipe':
            return {x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, duration: p.duration || 0.25};
        case 'key':
            return {name: p.name};
        case 'unlock':
            return {};
        case 'launch_app':
        case 'stop_app':
            return {package: p.package};
        case 'open_url':
            return {url: p.url};
        default:
            return {};
    }
}

function recNote(payload) {
    if (!REC.on) return;
    const kind = REC_KIND[payload.type];
    if (!kind) return;

    recAutoPause();
    const stale = REC.stale ? 'экран изменился — проверьте, что шаг нажимает нужное' : '';

    if (kind === 'tap') {
        recNoteTap(payload);
        /* Дописываем к предупреждению об однозначности, а не затираем его:
           устаревший дамп и неоднозначный селектор — разные беды. */
        if (stale) {
            const last = REC.steps[REC.steps.length - 1];
            last.warn = last.warn ? `${last.warn}; ${stale}` : stale;
        }
    } else if (kind === 'type') {
        recNoteType(payload);
    } else {
        recPush({kind, args: recArgs(kind, payload)});
    }
    recRefreshDump();
}

/* --------------------------------------------------- библиотека скриптов */

/* Готовые скрипты объявлены на сервере (farm/recorder/presets.py) и
   добавляются в сценарий без устройства: команды уедут на телефон только
   при запуске. Поэтому библиотека работает даже с пустой фермой. */

/* Список пакетов запрашивается один раз на устройство: adb его выдаёт секунду,
   а форма открывается часто. Сбрасывается сменой устройства в setActive(). */
async function recPackages() {
    if (REC.packages) return REC.packages;
    if (!S.active) return [];
    try {
        REC.packages = await api(`/api/devices/${S.active}/packages`);
    } catch (e) {
        REC.packages = [];
    }
    return REC.packages;
}

async function recLibOpen() {
    if (!REC.lib) {
        try {
            REC.lib = await api('/api/recorder/presets');
        } catch (e) {
            toast(e.message, 'bad');
            return;
        }
    }
    $('mTitle').textContent = t('device.dobavit_shag');
    $('mBody').innerHTML = addStepHtml(addStepPlan(recAddCtx()), REC.lib);
    $('mActs').innerHTML = `<span class="sp"></span>
        <button class="sm" onclick="closeModal()">${esc(t('modal.zakryt'))}</button>`;
    $('modal').querySelector('.sheet').classList.add('wide');
    openModal();
}

/* ------------------------------------------------------------ логика */

/* Куда встанет новый шаг — туда же, куда встала бы запись (recPush): в
   конец сюжета или за шагом «записать после этого». Отсюда — глубина и
   «внутри повтора» для выбора в addStepPlan. */
function recAddCtx() {
    const prev = REC.insertAfter ? recFind(REC.insertAfter) : null;
    const probe = {parent: prev ? (blockIsHead(prev) ? prev.id : (prev.parent ?? null)) : null};
    return {
        sel: REC.sel ? REC.sel.size : 0,
        depth: blockChain(probe).length,
        depthMax: BLOCK_DEPTH_MAX,
        inLoop: recBreakInLoop(probe),
        phone: !!S.active,
    };
}

function recAddPick(key) {
    if (key === 'anchor') {
        closeModal();
        recAnchorHere();
        return;
    }
    if (BLOCK_KINDS[key] || key === 'if_not') {
        const kind = key === 'if_not' ? 'if_seen' : key;
        if (REC.sel && REC.sel.size) recSelBlock(kind);
        else recBlockNew(kind);
        if (key === 'if_not') {
            const head = recFind(REC.open);
            if (head && head.kind === 'if_seen') {
                head.args.negate = true;
                recRender();
                recSave();
            }
        }
        closeModal();
        return;
    }
    recLogicPick(key);
}

/* Новый блок без выделения. Блоку нужен хотя бы один шаг внутри — пауза-
   заготовка, её заменяют записью («записать после этого шага») или
   удаляют. Рамку ставит recBlockWrap — те же проверки, что у выделения. */
function recBlockNew(kind) {
    const pause = recPush({kind: 'sleep', args: {seconds: 1}});
    const headId = REC.nextId;
    recBlockWrap(kind, [pause.id]);
    if (pause.parent !== headId) {          // рамка не встала — заготовка не нужна
        REC.steps = REC.steps.filter(s => s !== pause);
        if (REC.insertAfter === pause.id) REC.insertAfter = null;
        recRender();
        recSave();
    }
}

function recScenName(key) {
    const sc = (S.scenarios || []).find(x => x.key === key);
    return sc ? sc.name : key;
}

function recLogicPick(key) {
    if (key === 'break') {
        const step = recPush({kind: 'break', args: {}});
        closeModal();
        if (!recBreakInLoop(step)) toast(t('rec.break_vne'), 'bad');
        return;
    }
    if (key === 'finish') {
        $('modal').querySelector('.sheet').classList.remove('wide');
        $('mTitle').textContent = t('rec.l_finish');
        $('mBody').innerHTML = `<div class="row"><label>${esc(t('rec.kak'))}</label>
            <select id="logFinRes" class="grow">
              <option value="ok">${esc(t('rec.zakonchit_uspeh'))}</option>
              <option value="fail">${esc(t('rec.kak_oshibku'))}</option></select></div>
          <div class="row"><label>${esc(t('rec.prichina'))}</label>
            <input type="text" id="logFinWhy" class="grow" placeholder="${esc(t('rec.prichina_primer'))}"></div>`;
        $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>
            <button class="sm primary" onclick="recLogicFinish()">${esc(t('rec.dobavit'))}</button>`;
        return;
    }
    if (key === 'call') {
        const свой = REC.edit ? REC.edit.key : null;
        const own = (S.scenarios || []).filter(x => /^[a-z][a-z0-9_]{0,47}$/.test(x.key) && x.key !== свой && !x.error);
        if (!own.length) {
            toast(t('rec.net_stsenariev'), 'bad');
            return;
        }
        $('mTitle').textContent = t('rec.l_call');
        $('mBody').innerHTML = `<div class="lib">` + own.map(x => `
          <div class="li" onclick="recLogicCall('${esc(x.key)}')"><b>${esc(x.name || x.key)}</b>
            <span>${esc(x.description || x.key)}</span></div>`).join('') + '</div>';
        $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>`;
    }
}

function recLogicFinish() {
    const result = $('logFinRes').value === 'fail' ? 'fail' : 'ok';
    recPush({kind: 'finish', args: {result, reason: $('logFinWhy').value.trim()}});
    closeModal();
}

function recLogicCall(key) {
    recPush({kind: 'call', args: {scenario: key}});
    closeModal();
}

function recBreakInLoop(step) {
    const byId = blockById();
    return blockChain(step, byId).some(id => ['loop', 'until'].includes(byId.get(id).kind));
}

function recLibPick(index) {
    const preset = REC.lib[index];
    if (!(preset.inputs || []).length) {
        recLibAdd(preset, {});
        return;
    }
    $('modal').querySelector('.sheet').classList.remove('wide');
    $('mTitle').textContent = preset.title;
    $('mBody').innerHTML = preset.inputs.map(input => `
      <div class="row"><label>${esc(input.label)}</label>
        <input type="${input.number ? 'number' : 'text'}" step="any" class="grow"
               id="lib_${esc(input.name)}" placeholder="${esc(input.hint || '')}"
               value="${esc(input.default ?? '')}"
               ${input.packages ? 'list="libPkgs"' : ''}
               onkeydown="if(event.key==='Enter')recLibSubmit(${index})">
      </div>`).join('')
        + (preset.inputs.some(i => i.packages) ? '<datalist id="libPkgs"></datalist>' : '');
    $('mActs').innerHTML = `<button class="sm" onclick="recLibOpen()">← ${esc(t('rec.dob_nazad'))}</button>`
        + '<span class="sp"></span>'
        + `<button class="primary" onclick="recLibSubmit(${index})">Добавить</button>`;
    const first = $('lib_' + preset.inputs[0].name);
    if (first) first.focus();

    if (preset.inputs.some(i => i.packages)) {
        recPackages().then(list => {
            const box = $('libPkgs');
            if (box) box.innerHTML = list.map(name => `<option value="${esc(name)}">`).join('');
        });
    }
}

function recLibSubmit(index) {
    const preset = REC.lib[index];
    const values = {};
    for (const input of preset.inputs) {
        const value = ($('lib_' + input.name).value || '').trim();
        if (!value && !input.optional) {
            toast(`не заполнено: ${input.label}`, 'bad');
            return;
        }
        values[input.name] = value;
    }
    recLibAdd(preset, values);
}

/* Та же подстановка, что presets.fill на сервере: {имя} → значение формы. */
function recFill(preset, values) {
    return preset.steps.map(step => ({
        kind: step.kind,
        args: Object.fromEntries(Object.entries(step.args).map(([key, raw]) => {
            let value = raw;
            if (typeof value === 'string') {
                for (const [name, filled] of Object.entries(values)) {
                    value = value.split(`{${name}}`).join(filled);
                }
            }
            return [key, value];
        })),
    }));
}

function recLibAdd(preset, values) {
    recFill(preset, values).forEach(step => recPush(step));
    closeModal();
    toast(`добавлено: ${preset.title}`, 'ok');
}

/* ------------------------------------------------------------------ список */

function recFind(id) {
    return REC.steps.find(step => step.id === Number(id));
}

function recNum(value) {
    return String(Math.round(Number(value) * 1000) / 1000);
}

/* Запасные селекторы шага click: надёжные альтернативы выбранному. Уезжают
   на сервер и превращаются в ctx.click_any — на другой прошивке или локали
   основной селектор может не совпасть, цепочка спасает прогон. */
function recFallbacks(step) {
    if (step.kind !== 'click' || !step.selector) return [];
    /* step.or — выбор человека («или по id, или по тексту»), включая свои
       варианты. Пока его нет, берём надёжные альтернативы из дампа. */
    if (Array.isArray(step.or)) return step.or.filter(args => args !== step.selector.args).slice(0, REC_OR_MAX);
    if (!step.alts) return [];
    return step.alts
        .filter(alt => alt.call === 'click' && !alt.fragile && !alt.dynamic && alt.args !== step.selector.args)
        .map(alt => alt.args)
        .slice(0, 3);
}

/* Повторяет таблицу генерации из farm/recorder/codegen.py — это предпросмотр
   строки прямо в списке, полный текст файла всё равно собирает сервер. */
/* Какие запасные слои записались у шага. Порядок — как их пробует резолвер. */
function recLayers(step) {
    const out = [];
    if (step.texts && step.texts.length) out.push('текст');
    if (step.crop) out.push('картинка');
    if (step.point) out.push('координаты');
    return out;
}

function recCode(step, index) {
    const a = step.args;
    if (blockIsHead(step)) return blockCode(step);
    /* Зеркалит codegen._branch: единственный шаг, который занимает больше
       одной строки, — ветвление и есть несколько строк. */
    if (step.kind === 'branch') {
        const хвост = [];
        if (a.timeout != null) хвост.push(`timeout=${recNum(a.timeout)}`);
        if (step.report === false) хвост.push('report=False');
        const ветви = (step.arms || []).map(arm =>
            `    ${JSON.stringify(arm.name)}: [`
            + (arm.any || []).map(args => `dict(${args})`).join(', ') + '],').join('\n');
        const блоки = (step.arms || []).filter(arm => arm.run).map(arm =>
            `if ветка == ${JSON.stringify(arm.name)}:\n    ctx.run(${JSON.stringify(arm.run)})`
        ).join('\n');
        return 'ветка = ctx.which_screen({\n' + ветви + '\n}'
            + (хвост.length ? ', ' + хвост.join(', ') : '') + ')'
            + (блоки ? '\n' + блоки : '');
    }
    if (step.kind === 'expect') {
        return `ctx.expect_screen(${JSON.stringify(a.name)}, any=[`
            + (step.any || []).map(args => `dict(${args})`).join(', ') + '])';
    }
    if (step.kind === 'click') {
        const fallbacks = recFallbacks(step);
        const chain = [step.selector.args].concat(fallbacks);
        /* Зеркалит ветку click в farm/recorder/codegen.py: что здесь видно,
           то и попадёт в файл. Расхождение читалось бы как враньё. */
        if (recLayers(step).length) {
            const parts = ['sel=[' + chain.map(args => `dict(${args})`).join(', ') + ']'];
            if (step.texts && step.texts.length) {
                parts.push('text=[' + step.texts.map(t => JSON.stringify(t)).join(', ') + ']');
            }
            if (step.crop) parts.push(`img=${JSON.stringify(recAssetName(index || 0))}`);
            if (step.point) parts.push(`at=(${recNum(step.point[0])}, ${recNum(step.point[1])})`);
            return 'ctx.click_target(' + parts.join(', ') + ')';
        }
        if (fallbacks.length) {
            return 'ctx.click_any(' + chain.map(args => `dict(${args})`).join(', ') + ')';
        }
        return `ctx.click(${step.selector.args})`;
    }

    const key = REC_VALUE_KEY[step.kind];
    if (key) {
        const value = step.param
            ? `ctx.params["${step.param}"]`
            : (step.kind === 'sleep' ? recNum(a.seconds) : JSON.stringify(a[key] ?? ''));
        if (step.kind === 'type') {
            const src = a.account ? `ctx.account("${a.account}")["${a.field}"]` : value;
            return `ctx.type(${src}${a.clear ? ', clear=True' : ''})`;
        }
        if (step.kind === 'screenshot' && !a.name && !step.param) return 'ctx.screenshot()';
        return `ctx.${step.kind}(${value})`;
    }

    switch (step.kind) {
        case 'break':
            return 'break';
        case 'finish':
            return a.result === 'fail'
                ? `ctx.fail(${JSON.stringify(a.reason || 'сценарий остановлен шагом')})`
                : `ctx.finish(${JSON.stringify(a.reason || '')})`;
        case 'call':
            return `ctx.run(${JSON.stringify(a.scenario)})`;
        case 'tap':
            return `ctx.tap(${recNum(a.x)}, ${recNum(a.y)})`;
        case 'long_tap':
            return `ctx.long_tap(${recNum(a.x)}, ${recNum(a.y)}, ${recNum(a.duration ?? 0.8)})`;
        case 'swipe':
            return `ctx.swipe(${recNum(a.x1)}, ${recNum(a.y1)}, `
                + `${recNum(a.x2)}, ${recNum(a.y2)}, ${recNum(a.duration ?? 0.25)})`;
        case 'key':
            return `ctx.key(${JSON.stringify(a.name)})`;
        default:
            return `ctx.${step.kind}()`;
    }
}

/* Предупреждение видно всегда — это повод вмешаться. Подтверждение («из
   файла», «✓ уникален») — только у раскрытого шага: под каждым вторым
   кликом оно давало зелёную строку, которая ничего не требует, но тянет на
   себя внимание сильнее самой подписи шага. */
function recMark(step, open) {
    if (step.warn) return `<div class="rs-warn">⚠ ${esc(step.warn)}</div>`;
    if (!open) return '';
    if (step.kind !== 'click') return '';
    const layers = recLayers(step);
    const tail = layers.length ? ' · запасные слои: ' + layers.join(', ') : '';
    /* Про шаг из файла мы не знаем, однозначен ли его селектор: дампа того
       экрана давно нет. Писать «✓ уникален» было бы враньём. */
    if (step.adopted) return `<div class="rs-ok">из файла${esc(tail)}</div>`;
    return `<div class="rs-ok">✓ уникален на экране${esc(tail)}</div>`;
}

/* Признак поиска словами: description="Закрыть" → по подписи «Закрыть».
   Сырой вызов ctx.click(resourceId=…) человеку ничего не говорит. */
const REC_FEAT = {
    text: 'по тексту', textContains: 'по части текста', description: 'по подписи',
    descriptionContains: 'по части подписи', resourceId: 'по внутреннему имени',
    resourceIdMatches: 'по внутреннему имени',
    className: 'по типу элемента', index: 'по номеру', instance: 'по номеру',
};

function recFeatText(args) {
    const parts = [];
    String(args || '').replace(/(\w+)\s*=\s*(?:"([^"]*)"|(\S+?))(?=,|$)/g, (m, k, q, v) => {
        let val = q != null ? q : v;
        if (k === 'resourceIdMatches') val = val.replace(/^\.\*\//, '').replace(/\$$/, '').replace(/\\(.)/g, '$1');
        if (k === 'resourceId' || k === 'resourceIdMatches') val = val.split('/').pop().replace(/_/g, ' ');
        if (k === 'className') val = val.split('.').pop();
        /* instance считается с нуля: instance=1 — второй по счёту. */
        if (k === 'instance' && /^\d+$/.test(val)) {
            parts.push(t('rec.feat_nomer', {k: Number(val) + 1}));
            return m;
        }
        parts.push(`${REC_FEAT[k] || k} «${val}»`);
        return m;
    });
    return parts.join(' и ') || String(args);
}

const REC_OR_MAX = 3;   // = MAX_FALLBACKS в backend/farm/recorder/steps.py
const REC_OR_KINDS = ['resourceId', 'text', 'textContains', 'description', 'descriptionContains'];

function recOrKindName(k) {
    return k === 'resourceId' ? t('rec.feat_id') : k === 'text' ? t('rec.feat_text')
        : k === 'textContains' ? t('rec.feat_text_contains') : k === 'description' ? t('rec.feat_podpis')
            : t('rec.feat_opisanie');
}

/* «Как искать»: основной способ (радио) и «или так» — запасные (галочки).
   Шаг нажмёт первое, что найдёт: «или по id like_button, или по тексту
   «Нравится»». Свой вариант дописывается руками — на другой прошивке у
   кнопки бывает другой текст, а записать его с этого телефона нельзя. */
function recAlts(step) {
    if (step.kind !== 'click' || !step.selector) return '';
    const main = step.selector.args;
    const alts = step.alts || [];
    const picked = recFallbacks(step);
    /* Координаты — не способ поиска, а последний слой шага (step.point):
       основной селектор click обязан быть вызовом click, иначе сохранение
       получит 400. Индекс в alts сохраняем — по нему recPickSelector
       берёт вариант. */
    const choices = alts.map((alt, index) => ({alt, index})).filter(c => c.alt.call === 'click');
    const radios = choices.length > 1 ? choices.map(({alt, index}) => `
      <label><input type="radio" name="sel${step.id}" ${alt.args === main ? 'checked' : ''}
             onchange="recPickSelector(${step.id}, ${index})">
        <span title="${esc('ctx.' + alt.call + '(' + alt.args + ')')}">${esc(recFeatText(alt.args))}</span>
        <span class="${alt.matches === 1 && !alt.dynamic ? 'rs-sel-ok' : 'rs-sel-bad'}">${esc(recSelMark(alt))}</span></label>`).join('') : `
      <span class="rs-feat">${esc(recFeatText(main))}</span>`;
    const others = [...new Set([...alts.filter(a => a.call === 'click' && !a.fragile && !a.dynamic).map(a => a.args), ...picked])]
        .filter(args => args !== main);
    const full = picked.length >= REC_OR_MAX;
    const checks = others.map(args => {
        const on = picked.includes(args);
        return `<label><input type="checkbox" ${on ? 'checked' : ''} ${!on && full ? 'disabled' : ''}
             onchange="recOrToggle(${step.id}, this.dataset.args, this.checked)" data-args="${esc(args)}">
        <span title="${esc(args)}">${esc(recFeatText(args))}</span></label>`;
    }).join('');
    return `<div class="rs-alts">${esc(t('rec.kak_iskat_dvoetochie'))}${radios}
      <span class="rs-alts-k">${esc(t('rec.ili_tak'))}</span>${checks}
      ${full ? `<span class="dim">${esc(t('rec.ili_maks', {n: REC_OR_MAX}))}</span>` : `<div class="rs-or-add">
        <select id="orKind${step.id}" aria-label="${esc(t('rec.kak_iskat'))}">${REC_OR_KINDS.map(k =>
            `<option value="${k}">${esc(recOrKindName(k))}</option>`).join('')}</select>
        <input type="text" id="orVal${step.id}" placeholder="${esc(t('rec.svoy_variant'))}"
               onkeydown="if(event.key==='Enter')recOrAdd(${step.id})">
        <button class="sm" onclick="recOrAdd(${step.id})">${esc(t('rec.dobavit'))}</button>
      </div>`}
    </div>`;
}

function recOrToggle(id, args, on) {
    const step = recFind(id);
    if (!step) return;
    const cur = recFallbacks(step).filter(a => a !== args);
    step.or = on ? [...cur, args].slice(0, REC_OR_MAX) : cur;
    recRender();
    recSave();
}

function recOrAdd(id) {
    const step = recFind(id);
    const kind = ($('orKind' + id) || {}).value;
    const value = String(($('orVal' + id) || {}).value || '').trim();
    if (!step || !value || !REC_OR_KINDS.includes(kind)) return;
    /* Короткий id («like_button») без пакета не совпал бы с полным
       «com.vk:id/like_button» — ищем по окончанию. */
    const args = kind === 'resourceId' && !value.includes(':')
        ? `resourceIdMatches=${JSON.stringify('.*/' + value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$')}`
        : `${kind}=${JSON.stringify(value)}`;
    if (args === step.selector.args) return;
    step.or = [...recFallbacks(step).filter(a => a !== args), args].slice(0, REC_OR_MAX);
    recRender();
    recSave();
}

/* Имя экрана правится отдельно, а не через REC_VALUE_KEY: тот механизм несёт
   с собой кнопку выноса в PARAMS, а бэкенд параметризовать expect не даёт
   (его нет в PARAMETRIZABLE) и ответил бы 400.

   Имя попадает в сообщение об ошибке прогона — «ожидал экран «вход», вижу
   com.app.main». Поэтому здесь же показываем, по каким признакам якорь
   опознаёт экран: без этого непонятно, что именно проверяется. */
function recAnchorEditor(step) {
    if (step.kind !== 'expect') return '';
    const признаки = (step.any || [])
        .map(args => `<span class="rs-feat" title="${esc(args)}">${esc(recFeatText(args))}</span>`).join('');
    return `<div class="row">
    <label>Имя экрана</label>
    <input type="text" value="${esc(step.args.name || '')}"
           placeholder="например: вход"
           oninput="recEditAnchor(${step.id}, this.value)">
  </div>
  <div class="rs-alts">опознаётся по:${признаки}</div>`;
}

function recEditAnchor(id, value) {
    const step = recFind(id);
    /* Пустое имя дало бы «ожидал экран «»» — бесполезное сообщение ровно в
       тот момент, когда от него всё зависит. Пустое поле означает «верни
       автоматическое имя», а не «имени нет». */
    const имя = value.split('\n')[0].trim();
    step.args.name = имя || ('screen' + step.id);
    recSave();
}

/* Что вводит шаг «Ввести»: свой текст или поле аккаунта этого телефона из
   раздела «Аккаунты». Записанный логин — частный случай одного телефона;
   с аккаунтом тот же сценарий работает на всей ферме. */
const REC_ACC_FIELDS = {login: 'логин', password: 'пароль', phone: 'телефон'};

function recTypeSource(step) {
    const a = step.args;
    const cur = a.account ? `${a.account}:${a.field}` : '';
    const opts = ['<option value="">свой текст</option>'];
    for (const [p, pn] of Object.entries(PLATFORM_NAMES)) {
        for (const [f, fn] of Object.entries(REC_ACC_FIELDS)) {
            opts.push(`<option value="${p}:${f}">${fn} аккаунта ${pn}</option>`);
        }
    }
    return `<div class="row"><label class="inline">Что вводить
      <select onchange="recSetTypeSource(${step.id}, this.value)">${opts.join('')
        .replace(`value="${cur}"`, `value="${cur}" selected`)}</select></label></div>`;
}

function recSetTypeSource(id, value) {
    const step = recFind(id);
    if (value) {
        const [account, field] = value.split(':');
        step.args.account = account;
        step.args.field = field;
        step.param = null;
    } else {
        delete step.args.account;
        delete step.args.field;
    }
    recRender();
    recSave();
}

function recValueEditor(step) {
    const key = REC_VALUE_KEY[step.kind];
    if (!key) return '';
    if (step.kind === 'type') {
        if (step.args.account) return recTypeSource(step);
        return recTypeSource(step) + recValueEditorPlain(step, key);
    }
    return recValueEditorPlain(step, key);
}

function recValueEditorPlain(step, key) {
    if (step.param) {
        return `<div class="rs-param">параметр <b>${esc(step.param)}</b>
      <button class="sm" onclick="recUnparam(${step.id})">вернуть значение</button></div>`;
    }
    const type = key === 'seconds' ? 'number' : 'text';
    return `<div class="row">
    <input type="${type}" step="any" value="${esc(step.args[key] ?? '')}"
           oninput="recEditValue(${step.id}, this.value)">
    <button class="sm" title="Вынести в параметры" onclick="recParam(${step.id})">{}</button>
  </div>`;
}

function recThumb(step) {
    /* У шага из файла скриншота экрана нет, но есть кроп цели — он и отвечает
       на вопрос «по чему это был тап». */
    if (!step.shot && step.crop) {
        return `<div class="rs-thumb"><img src="data:image/png;base64,${step.crop}" alt=""></div>`;
    }
    if (!step.shot) return '';
    const frame = step.bounds
        ? `<div class="rs-box" style="left:${step.bounds[0] * 100}%;top:${step.bounds[1] * 100}%;
             width:${(step.bounds[2] - step.bounds[0]) * 100}%;
             height:${(step.bounds[3] - step.bounds[1]) * 100}%"></div>`
        : '';
    return `<div class="rs-thumb"><img src="${step.shot}" alt="">${frame}</div>`;
}

/* Главное в строке — проверить шаг; остальное (записать после, дублировать,
   двигать, удалить) живёт в «⋯»: семь иконок без подписей подряд читались
   как шум, а корзина рядом со стрелкой «вниз» ловила промахи. */
function recRow(step, index) {
    const open = REC.open === step.id;
    const sel = REC.sel && REC.sel.has(step.id);
    return `<div class="rs ${open ? 'open' : ''} ${sel ? 'sel' : ''} ${blockRowClass(step)}"
       data-id="${step.id}"
       ondragstart="recDragStart(event, ${step.id})" ondragend="recDragEnd(event)"
       ondragover="recDragOver(event, ${step.id})" ondragleave="recDragLeave(event)"
       ondrop="recDrop(event, ${step.id})">
    <div class="rs-head" onclick="recToggle(${step.id})">
      <span class="rs-grip" onmousedown="recDragOn(event)"
            title="${esc(t('rec.m_peretaschite'))}">${recIcon('grip')}</span>
      <input type="checkbox" class="rs-sel" aria-label="${esc(t('rec.m_vybrat', {n: index + 1}))}"
             ${sel ? 'checked' : ''}
             onclick="event.stopPropagation();recSelToggle(${step.id}, event)">
      <span class="rs-n">${index + 1}</span>
      ${grIcon(schIcon(step)[1])}
      <span class="rs-label">${esc(recLabel(step))}</span>
      ${recBadges(step)}
      <span class="rs-acts">
        <button class="sm ghost" title="${esc(t('rec.m_proverit'))}" aria-label="${esc(t('rec.m_proverit'))}"
                onclick="event.stopPropagation();recRunStep(${index})">${recIcon('play')}</button>
        <button class="sm ghost rs-more-btn" title="${esc(t('rec.m_esche'))}" aria-label="${esc(t('rec.m_esche'))}"
                aria-haspopup="menu"
                onclick="event.stopPropagation();recRowMenu(event, ${step.id})">⋯</button>
      </span>
    </div>
    ${recMark(step, open)}
    ${open ? recStepBody(step, index) : ''}
  </div>`;
}

/* Раскрытый шаг: сверху то, что правят каждый день (картинка, имя экрана,
   ветки развилки, значение, блок, «если не нашёл»), ниже под
   «Дополнительно» — код строки и запасные признаки «как искать». Раскрыт
   сам, если запасные уже выбраны: спрятать заданное — потерять его из виду. */
function recStepBody(step, index) {
    const main = recThumb(step) + recAnchorEditor(step) + recBranchEditor(step)
        + recValueEditor(step) + recBlockEditor(step) + recFlexEditor(step);
    const busy = step.kind === 'click' && recFallbacks(step).length > 0;
    return main + `<details class="rs-more" ${busy ? 'open' : ''}>
      <summary>${esc(t('rec.dopolnitelno'))}</summary>
      <div class="rs-code">${esc(recCode(step, index))}</div>
      ${recAlts(step)}
    </details>`;
}

/* Подписи — t() прямо здесь, а не ключи: test_strings ищет ключи по t('…'). */
const REC_ROW_MENU = () => [
    [t('rec.m_zapisat_posle'), 'plus', (id) => recRecordAfter(id)],
    [t('rec.m_zapustit_otsyuda'), 'play', (id, index) => recRunFrom(index)],
    [t('rec.m_dublirovat'), 'copy', (id) => recDup(id)],
    [t('rec.m_vyshe'), 'up', (id) => recMove(id, -1)],
    [t('rec.m_nizhe'), 'down', (id) => recMove(id, 1)],
    [t('rec.m_udalit'), 'trash', (id) => recDelete(id), 'danger'],
];

/* Открытое меню помнится по id шага (REC.menuFor), а не живёт только в
   DOM: список пересобирается и без участия человека (селектор приехал с
   опозданием, автосохранение), и меню, висящее на старой строке, пропадало
   бы из-под мыши. recRender рисует его заново через recRowMenuShow. */
function recRowMenuClose() {
    REC.menuFor = null;
    document.querySelectorAll('.rs-menu').forEach(menu => menu.remove());
    document.removeEventListener('click', recRowMenuClose);
    document.removeEventListener('keydown', recRowMenuKey);
}

function recRowMenuKey(ev) {
    if (ev.key === 'Escape') recRowMenuClose();
}

function recRowMenu(ev, id) {
    const again = REC.menuFor === id;
    recRowMenuClose();
    if (again) return;
    REC.menuFor = id;
    recRowMenuShow(true);
    setTimeout(() => {
        document.addEventListener('click', recRowMenuClose);
        document.addEventListener('keydown', recRowMenuKey);
    });
}

function recRowMenuShow(focus) {
    const id = REC.menuFor;
    const acts = id != null && document.querySelector(`#recSteps .rs[data-id="${id}"] .rs-acts`);
    if (!acts) {
        if (id != null) recRowMenuClose();   // шага больше нет — и меню не нужно
        return;
    }
    const menu = document.createElement('div');
    menu.className = 'rs-menu';
    menu.setAttribute('role', 'menu');
    REC_ROW_MENU().forEach(([label, icon, run, kind]) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'rs-menu-i ' + (kind || '');
        item.setAttribute('role', 'menuitem');
        item.innerHTML = recIcon(icon) + `<span>${esc(label)}</span>`;
        item.onclick = (e) => {
            e.stopPropagation();
            recRowMenuClose();
            /* Номер берём сейчас: за время открытого меню шаги могли сдвинуться. */
            run(id, REC.steps.findIndex(step => step.id === id));
        };
        menu.appendChild(item);
    });
    acts.appendChild(menu);
    if (focus) menu.querySelector('button').focus();
}

function recRender() {
    recBlocksFix();
    recSchemeSpine();
    recSchemeRefresh();
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = recEmptySteps();
        return;
    }
    box.classList.toggle('has-sel', !!(REC.sel && REC.sel.size));
    /* Список пересобирается и без участия человека — например, когда
       селектор записанного нажатия приехал с опозданием. Раскрытое «ещё» у
       шага и фокус в поле при этом не должны пропадать (uikeep.js). Без
       пропуска одинаковой разметки: поле с отвергнутым вводом обязано
       вернуться к сохранённому значению. */
    const html = recSelBar() + REC.steps.map(recRow).join('');
    if (window.keepUi) keepUi(box, () => { box.innerHTML = html; });
    else box.innerHTML = html;
    if (REC.menuFor != null) recRowMenuShow(false);
}

/* ------------------------------------------------------------------ правка */

function recToggle(id) {
    REC.open = REC.open === id ? null : id;
    recRender();
}

/* Без «Вы уверены?»: подтверждение на каждое удаление приучает жать «Да»
   не читая. Ошибку чинит «Вернуть» в тосте — та же отмена, что Ctrl+Z. */
function recDelete(id) {
    const index = REC.steps.findIndex(step => step.id === id);
    REC.steps = REC.steps.filter(step => step.id !== id);
    recPrune();
    recRender();
    recSave();
    if (index >= 0) toast(t('rec.shag_udalen', {n: index + 1}), '', {label: t('rec.vernut'), onClick: recUndo});
}

function recMove(id, delta) {
    const index = REC.steps.findIndex(step => step.id === id);
    if (index < 0) return;
    /* Блок двигается целиком — заголовок вместе со всем внутри (blockOf). */
    const block = blockOf(REC.steps[index]);
    const target = delta < 0 ? index - 1 : index + block.length;
    if (target < 0 || target >= REC.steps.length) return;
    REC.steps.splice(index, block.length);
    REC.steps.splice(delta < 0 ? target : target - block.length + 1, 0, ...block);
    blockPlace(block[0], delta < 0);
    recRender();
    recSave();
}

/* ------------------------------------------------- перетаскивание шагов

   Кнопки ↑↓ остаются: с клавиатуры и на пятнадцати шагах они быстрее, чем
   тащить мышью через весь список. Но собирать сюжет удобнее руками, поэтому
   шаг можно взять за ручку и уронить куда надо.

   Тащим только за ручку, а не за всю строку: внутри строки живут поля ввода
   и селекты, и строка, которую можно схватить в любом месте, отняла бы у них
   выделение текста. HTML5 DnD стартует от ближайшего draggable-предка, кто бы
   ни был под курсором, — поэтому draggable включается на mousedown по ручке и
   гасится по окончании. */
function recDragOn(ev) {
    const row = ev.target.closest('.rs');
    if (row) row.draggable = true;
}

function recDragStart(ev, id) {
    REC.drag = id;
    ev.dataTransfer.effectAllowed = 'move';
    /* Без setData часть браузеров не начинает перетаскивание вообще. */
    ev.dataTransfer.setData('text/plain', String(id));
    ev.target.closest('.rs').classList.add('dragging');
}

function recDragEnd(ev) {
    REC.drag = null;
    const row = ev.target.closest('.rs');
    if (row) {
        row.draggable = false;
        row.classList.remove('dragging');
    }
    document.querySelectorAll('#recSteps .rs')
        .forEach(el => el.classList.remove('over-up', 'over-down'));
}

/* Куда уронить — выше или ниже цели, по половине её высоты. Это не
   украшение: без показанной границы человек не знает, встанет шаг до или
   после, и первое перетаскивание всегда получается не туда. */
function recDragOver(ev, id) {
    if (REC.drag == null || REC.drag === id) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    const row = ev.currentTarget;
    const rect = row.getBoundingClientRect();
    const выше = (ev.clientY - rect.top) < rect.height / 2;
    row.classList.toggle('over-up', выше);
    row.classList.toggle('over-down', !выше);
}

function recDragLeave(ev) {
    ev.currentTarget.classList.remove('over-up', 'over-down');
}

function recDrop(ev, id) {
    ev.preventDefault();
    const row = ev.currentTarget;
    const выше = row.classList.contains('over-up');
    row.classList.remove('over-up', 'over-down');
    if (REC.drag == null || REC.drag === id) return;

    const from = REC.steps.findIndex(step => step.id === REC.drag);
    if (from < 0) return;
    const block = blockOf(REC.steps[from]);   // блок переезжает целиком
    if (block.some(s => s.id === id)) return;
    REC.steps.splice(from, block.length);
    /* Цель ищем ПОСЛЕ изъятия: индексы за вырезанным шагом сдвинулись, и
       поиск до splice ставил бы шаг на позицию мимо на единицу. */
    const to = REC.steps.findIndex(s => s.id === id);
    const цель = REC.steps[to];
    REC.steps.splice(выше ? to : to + 1, 0, ...block);
    /* Бросили под строку блока — значит, в блок. */
    blockPlace(block[0], !выше && (blockIsHead(цель) || цель.parent != null));
    REC.drag = null;
    recRender();
    recSave();
}

function recEditValue(id, value) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    step.args[key] = key === 'seconds' ? Number(value) || 0 : value;
    recSave();
}

function recPickSelector(id, index) {
    const step = recFind(id);
    const alt = step && (step.alts || [])[index];
    if (!alt || alt.call !== 'click') return;
    step.selector = {call: alt.call, args: alt.args};
    step.warn = recSelWarn(alt);
    recRender();
    recSave();
}

/* Два поля сразу, а не два prompt() подряд: подпись почти всегда выводится
   из имени, и вводить её вслепую вторым окном неудобно. */
function recParam(id) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];

    $('mTitle').textContent = 'Вынести в параметры';
    $('mBody').innerHTML = `
    <div class="row"><label for="pmName">Имя</label>
      <input type="text" id="pmName" class="grow" placeholder="package"
             oninput="if(!$('pmLabel').dataset.touched)$('pmLabel').value=this.value"></div>
    <div class="row"><label for="pmLabel">Подпись в форме</label>
      <input type="text" id="pmLabel" class="grow" oninput="this.dataset.touched=1"></div>
    <div class="warn"><svg class="ic"><use href="#i-info"/></svg>
      <span>Латиница в нижнем регистре, цифры и подчёркивание.
      Текущее значение станет значением по умолчанию.</span></div>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="sm" onclick="closeModal()">Отмена</button>'
        + `<button class="primary" onclick="recParamSubmit(${id})">Вынести</button>`;
    openModal();
    $('pmName').focus();
}

function recParamSubmit(id) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    const name = $('pmName').value.trim();
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(name)) {
        toast('имя настройки — только маленькие латинские буквы, цифры и _, например login_text', 'bad');
        $('pmName').focus();
        return;
    }
    REC.params[name] = {label: $('pmLabel').value.trim() || name, default: step.args[key]};
    step.param = name;
    closeModal();
    recRender();
    recSave();
}

function recUnparam(id) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    const spec = REC.params[step.param];
    if (spec) step.args[key] = spec.default;
    step.param = null;
    recPrune();
    recRender();
    recSave();
}

/* Параметр без единого шага-владельца сервер отвергнет с 400. */
function recPrune() {
    const used = new Set(REC.steps.map(step => step.param).filter(Boolean));
    for (const name of Object.keys(REC.params)) {
        if (!used.has(name)) delete REC.params[name];
    }
}

/* ------------------------------------------------------------------ черновик */

/* Миниатюры в localStorage не кладём: лимит 5 МБ выбирается десятком кадров. */
function recSave() {
    /* Скриншоты и кропы в черновик не кладём: их там десятки, а квота
       localStorage маленькая. Черновик хранит структуру, не картинки.

       У шагов из файла (правка) alts и имя кропа сохраняем: заново из дампа
       они не возьмутся — дампа того экрана уже нет, — а без них перезапись
       молча выкинула бы запасные селекторы и слой шаблона. Сами байты кропа
       вернёт /api/recorder/recipe по имени. */
    const light = REC.steps.map(step => Object.assign({}, step, {
        shot: null,
        crop: null,
        alts: step.adopted ? step.alts : null,
    }));
    try {
        localStorage.setItem(recDraftKey(), JSON.stringify(
            {steps: light, params: REC.params, nextId: REC.nextId}));
    } catch (e) {
        /* переполнение хранилища не должно ронять запись */
    }
}

/* Отказ от восстановления черновик не стирает: прошлый вариант удалял его
   сразу, и случайный «нет» уносил работу безвозвратно. Черновик переживает
   отказ и предлагается снова — стирается он только сохранением сценария. */
function recRestore() {
    if (REC.steps.length) return;
    let draft;
    try {
        draft = JSON.parse(localStorage.getItem(REC_DRAFT_KEY) || 'null');
    } catch (e) {
        return;
    }
    if (!draft || !draft.steps || !draft.steps.length) return;

    confirmModal('Восстановить черновик?',
        `<p>С прошлого раза остался незаконченный сценарий на
         <b>${draft.steps.length}</b> шагов.</p>
         <p style="color:var(--dim)">Отказ черновик не стирает.</p>`,
        'Восстановить', () => {
            REC.steps = draft.steps;
            REC.params = draft.params || {};
            REC.nextId = draft.nextId || (REC.steps.length + 1);
            recRender();
            recSync();
        });
}

/* ------------------------------------------------------------------ оверлей */

/* Слой позиционируется по прямоугольнику картинки, а не .stage: #screen
   центрируется во flex-контейнере и ужат max-width/max-height — рамки,
   посчитанные по .stage, уехали бы на её поля. */
function recOverlaySync() {
    const layer = $('recLayer'), img = $('screen');
    if (!layer || !img) return;
    const image = img.getBoundingClientRect();
    const stage = img.parentElement.getBoundingClientRect();
    layer.style.left = (image.left - stage.left) + 'px';
    layer.style.top = (image.top - stage.top) + 'px';
    layer.style.width = image.width + 'px';
    layer.style.height = image.height + 'px';
}

function recOverlayOff() {
    const layer = $('recLayer');
    if (!layer) return;
    layer.style.display = 'none';
    layer.innerHTML = '';
}

function recOverlayRender() {
    const layer = $('recLayer');
    if (!layer) return;
    if (!REC.on || REC.stale || !REC.dump || !REC.dump.nodes.length) {
        recOverlayOff();
        return;
    }
    recOverlaySync();
    layer.style.display = 'block';
    /* Рамку получает и кликабельный узел без подписи: Compose-плитки часто
       не несут ни text, ни resourceId, но по ним нужно уметь записать шаг.
       Прятать их — «не видно всё дерево» глазами пользователя. */
    layer.innerHTML = REC.dump.nodes
        .filter(node => node.clickable || node.text || node.resourceId || node.description)
        .map(node => {
            const [x1, y1, x2, y2] = node.bounds;
            const on = REC.hover === node.id ? ' hov' : '';
            const anon = (node.text || node.resourceId || node.description) ? '' : ' anon';
            return `<div class="rb${on}${anon}" style="left:${x1 * 100}%;top:${y1 * 100}%;`
                + `width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%"></div>`;
        })
        .join('');
}

/* Подсветка под курсором. Слушаем .stage, а не слой: у слоя выключена мышь,
   а узел #screen пересоздаётся при каждом startStream(). */
(function initRecorderHover() {
    const stage = document.querySelector('.stage');
    if (!stage) return;

    stage.addEventListener('mousemove', ev => {
        if (!REC.on || REC.stale) return;
        const rect = $('screen').getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const hit = recHit((ev.clientX - rect.left) / rect.width,
            (ev.clientY - rect.top) / rect.height);
        const id = hit ? hit.id : null;
        if (id !== REC.hover) {
            REC.hover = id;
            recOverlayRender();
        }
    });

    stage.addEventListener('mouseleave', () => {
        if (REC.hover != null) {
            REC.hover = null;
            recOverlayRender();
        }
    });

    if (window.ResizeObserver) new ResizeObserver(recOverlaySync).observe(stage);
    window.addEventListener('resize', recOverlaySync);

    /* Холст тоже зависит от ширины окна: карточка считает свою ширину от
       ширины #recScheme (grNodeW). Перерисовываем не на каждый пиксель
       ресайза, а по его окончании — раскладка всего сюжета не стоит того,
       чтобы считаться сотню раз за одно перетаскивание края окна. */
    let schemeResize;
    let lastNodeW = null;
    const host = $('recScheme');
    if (host && window.ResizeObserver) {
        new ResizeObserver(() => {
            clearTimeout(schemeResize);
            schemeResize = setTimeout(() => {
                if (REC.view !== 'scheme') return;
                /* Перерисовываем, только если ширина карточки правда
                   изменилась. recSchemeSpine() пересобирает innerHTML
                   целиком, и без этой проверки каждый тик ресайза
                   создавал узлы заново — вместе с ними заново
                   проигрывались анимации появления (рисунок заглушки
                   моргал на всю ширину экрана). grNodeW() к тому же
                   меняется ступенькой, а не на каждый пиксель: между
                   ступеньками перерисовывать нечего. */
                const w = grNodeW();
                if (w === lastNodeW) return;
                lastNodeW = w;
                recSchemeSpine();
            }, 120);
        }).observe(host);
    }
})();

/* ------------------------------------------------------------------ сохранение */

/* На сервер уезжает только то, что нужно генератору: миниатюры,
   альтернативы селекторов и метки уникальности остаются в браузере. */
/* Имя файла кропа. Только латиница: бэкенд проверяет имя регуляркой, а
   подписи элементов русские, и транслитерация тут ненадёжна. Номер берётся
   от текущей позиции шага, а не от момента записи, — шаги переставляют и
   удаляют, и иначе имена разъехались бы со своими шагами. */
function recAssetName(index) {
    return String(index + 1).padStart(2, '0') + '_click.png';
}

function recPayload(meta) {
    const assets = {};
    const steps = REC.steps.map((step, index) => {
        const out = {
            kind: step.kind,
            args: step.args,
            selector: step.selector
                ? Object.assign({}, step.selector, {fallbacks: recFallbacks(step)})
                : null,
            param: step.param || null,
            note: step.kind === 'click' ? step.note : '',
        };
        if (step.kind === 'expect') out.any = step.any || [];
        if (blockIsHead(step)) out.args = blockPayloadArgs(step);
        if (step.kind === 'until' || step.kind === 'if_seen') out.any = step.any || [];
        if (step.kind === 'branch') {
            out.arms = (step.arms || []).map(arm => ({
                name: arm.name, any: arm.any || [], run: arm.run || '',
            }));
            out.report = step.report !== false;
        }
        if (step.kind === 'click') {
            if (step.texts && step.texts.length) out.texts = step.texts;
            if (step.point) out.point = step.point;
            if (step.crop && Object.keys(assets).length < REC_ASSETS_MAX) {
                out.crop = recAssetName(index);
                assets[out.crop] = step.crop;
            }
        }
        if (step.pos) out.pos = step.pos;
        if (step.optional) out.optional = true;
        if (step.retries) out.retries = step.retries;
        return out;
    });

    const body = {meta: meta, params: REC.params, steps: steps};
    if (Object.keys(assets).length) {
        body.assets = assets;
        /* При правке масштаб считается от устройства ЗАПИСИ: кропы приехали с
           него, а правят сценарий часто с другого телефона. */
        body.screen_width = REC.baseWidth || REC.screenWidth || null;
    }
    return body;
}

function recMeta() {
    return {
        name: ($('recName') && $('recName').value.trim()) || 'Записанный сценарий',
        description: ($('recDesc') && $('recDesc').value.trim()) || '',
        watch_popups: !$('recPopups') || $('recPopups').checked,
        human: !$('recHuman') || $('recHuman').checked,
    };
}

async function recPreview() {
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return;
    }
    try {
        const source = await api('/api/recorder/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(recPayload(recMeta())),
        });
        $('mTitle').textContent = 'Сгенерированный код';
        $('mBody').innerHTML = `<pre class="log" style="max-height:60vh">${esc(source)}</pre>`;
        $('mActs').innerHTML = '<span class="sp"></span>'
            + '<button class="sm" onclick="closeModal()">Закрыть</button>';
        openModal();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

const REC_TRANSLIT = {
    а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z',
    и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r',
    с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch',
    ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

/* Имя файла — подсказка, не защита: ключ всё равно проверяется на сервере. */
function recSlug(name) {
    const latin = String(name).toLowerCase().split('')
        .map(ch => (ch in REC_TRANSLIT ? REC_TRANSLIT[ch] : ch)).join('');
    const key = latin.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48);
    return /^[a-z]/.test(key) ? key : ('s_' + key).slice(0, 48);
}

function recSaveForm() {
    if (REC.teach) return recTeachForm();   // учим обходить, а не пишем сценарий
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return;
    }
    if (REC.on) recPause();

    /* При правке форма не спрашивает заново то, что уже известно: она
       показывает нынешние название, описание и флаги файла. Имя файла
       менять нельзя — смена ключа означала бы «сохранить копию», а нажали
       «править». */
    const правка = REC.edit;
    const meta = (правка && REC.edit.meta) || {};
    const имя = meta.name || 'Записанный сценарий';
    const ключ = правка ? REC.edit.key : recSlug(имя);
    const popups = meta.watch_popups === undefined ? true : !!meta.watch_popups;
    const human = meta.human === undefined ? true : !!meta.human;

    $('mTitle').textContent = правка ? 'Сохранить изменения' : 'Сохранить сценарий';
    $('mBody').innerHTML = `
    <div class="row"><label>Название</label>
      <input type="text" id="recName" value="${esc(имя)}"
             ${правка ? '' : `oninput="$('recKey').value = recSlug(this.value)"`}></div>
    <div class="row"><label>Имя файла</label>
      <input type="text" id="recKey" value="${esc(ключ)}" ${правка ? 'readonly' : ''}></div>
    <div class="row"><label>Описание</label>
      <input type="text" id="recDesc" value="${esc(meta.description || '')}"
             placeholder="что делает сценарий"></div>
    <div class="row"><label class="kb">
      <input type="checkbox" id="recPopups" ${popups ? 'checked' : ''} style="accent-color:var(--accent)">
      закрывать всплывающие диалоги</label></div>
    <div class="row"><label class="kb" title="Паузы, разброс тапов, живые свайпы и печать">
      <input type="checkbox" id="recHuman" ${human ? 'checked' : ''} style="accent-color:var(--accent)">
      человечный режим (паузы, промахи, живые движения)</label></div>
    <div class="row"><label class="kb" title="Сразу проверить сценарий на телефоне">
      <input type="checkbox" id="recStay" ${recRunAfterPending() ? 'checked' : ''} style="accent-color:var(--accent)">
      остаться в конструкторе</label></div>
    ${правка ? `<div class="warn"><svg class="ic"><use href="#i-alert"/></svg>
      <span>«${esc(ключ)}» перезапишется — ручные правки в коде пропадут.</span></div>` : ''}`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="sm" onclick="closeModal()">Отмена</button>'
        + `<button class="primary" onclick="recSubmit(${правка ? 'true' : 'false'})">`
        + (правка ? 'Перезаписать' : 'Сохранить') + '</button>';
    openModal();
}

/* Диалог сохранения отвода. Условие человек выбирает сам: идентификатор
   переживает смену языка, но бывает пуст; текст нагляднее, но ломается на
   другой локали. Какой признак действительно отличает эту преграду, знает
   только тот, кто её видел. */
function recTeachForm() {
    if (!REC.teach) return;
    if (!REC.steps.length) {
        toast('сначала покажите кликами, как выйти', 'bad');
        return;
    }
    if (REC.on) recPause();

    const варианты = REC.teach.candidates.map((c, i) =>
        `<label class="kb"><input type="radio" name="teachWhen" value="${i}"
           ${i === 0 ? 'checked' : ''} style="accent-color:var(--accent)">
         ${esc(c.label)}</label>`).join('');

    $('mTitle').textContent = 'Сохранить автозакрытие';
    $('mBody').innerHTML = `
    <div class="row"><label>Название</label>
      <input type="text" id="teachName" value="Закрыть всплывающее окно"
             oninput="$('teachKey').value = recSlug(this.value)"></div>
    <div class="row"><label>Имя файла</label>
      <input type="text" id="teachKey" value="${esc(recSlug('Закрыть всплывающее окно'))}"></div>
    <div class="row"><label>Как узнать окно</label></div>
    <div class="rs-alts">${варианты}</div>
    <div class="row"><label class="kb">
      <input type="checkbox" id="teachGlobal" style="accent-color:var(--accent)">
      применять во всех приложениях, не только в ${esc(REC.teach.package || '—')}</label></div>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="sm" onclick="closeModal()">Отмена</button>'
        + '<button class="primary" onclick="recTeachSubmit()">Сохранить автозакрытие</button>';
    openModal();
}

async function recTeachSubmit() {
    const выбран = document.querySelector('input[name="teachWhen"]:checked');
    const body = recPayload(recMeta());
    body.key = $('teachKey').value.trim();
    body.name = $('teachName').value.trim();
    body.when = REC.teach.candidates[Number(выбран.value)].selector;
    body.package = $('teachGlobal').checked ? '' : (REC.teach.package || '');

    try {
        await post('/api/detours', body);
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    closeModal();
    const resume = REC.teach.resume;
    REC.teach = null;
    REC.steps = [];
    REC.params = {};
    REC.open = null;
    localStorage.removeItem(REC_DRAFT_KEY);
    recRender();
    recSync();
    recBanner('');
    if (resume) {
        /* Человек уже прошёл экран руками, пока показывал, — запуск
           пересверится и пойдёт дальше; в следующий раз отвод сработает сам. */
        await decideJob(resume, 'retry');
        toast('запомнил — запуск продолжается', 'ok');
    } else {
        toast('автозакрытие сохранено', 'ok');
    }
    await loadScenarios(true);
}

async function recSubmit(overwrite) {
    const key = REC.edit ? REC.edit.key : $('recKey').value.trim();
    const body = recPayload(recMeta());
    body.key = key;
    body.overwrite = !!overwrite;
    const правка = !!REC.edit;
    const stay = !!($('recStay') && $('recStay').checked);

    try {
        await post('/api/recorder/save', body);
    } catch (e) {
        if (!overwrite && /уже существует/.test(e.message)) {
            confirmModal('Такой сценарий уже есть',
                `<p>Сценарий <b>${esc(key)}</b> уже есть.
                 Заменить его новым?</p>`,
                'Заменить', () => recSubmit(true), true);
            return;
        }
        toast(e.message, 'bad');
        return;
    }

    if (stay) {
        await recStayAfterSave(key, body.meta, правка);
        return;
    }
    closeModal();
    localStorage.removeItem(recDraftKey());   // до сброса REC.edit: ключ зависит от него
    REC.steps = [];
    REC.params = {};
    REC.open = null;
    REC.edit = null;
    REC.baseWidth = null;
    recBanner('');
    recRender();
    recSync();
    recDone();
    await loadScenarios(true);
    pickScenario(key);
    toast(правка ? 'изменения сохранены' : 'сценарий сохранён', 'ok',
        {label: 'Запустить на ферме →', onClick: () => openRunDialog({scenario: key})});
}

/* Выйти из режима, ничего не сохранив. Без этого режим был ловушкой:
   попал в него — и единственный выход перезагрузить страницу. */
function recModeOff(confirmed) {
    const учили = !!REC.teach;
    const грязно = REC.steps.length && window.stCurSig && stCurSig() !== REC.savedSig;
    if (!confirmed && (грязно || учили && REC.steps.length)) {
        return confirmModal(учили ? 'Прервать обучение?' : 'Выйти без сохранения?',
            '<p>Несохранённые шаги пропадут. Файл сценария не изменится.</p>',
            'Выйти без сохранения', () => recModeOff(true), true);
    }
    /* Правка бросается вместе со шагами: они пришли из файла, и оставить их
       в конструкторе значило бы предложить сохранить копию под новым именем —
       не то, о чём просили. Черновик правки тоже стираем: он относится к
       сценарию, из которого мы только что вышли. */
    if (REC.edit) {
        localStorage.removeItem(recDraftKey());
        REC.edit = null;
        REC.steps = [];
        REC.params = {};
        REC.open = null;
        REC.baseWidth = null;
        recRender();
    }
    REC.teach = null;
    recBanner('');
    recSync();
    toast(учили ? 'обучение прервано, автозакрытие не сохранено'
        : 'правка отменена, файл не тронут');
}

/* ------------------------------------------------------------------ правка файла */

/* Сгенерированный .py в шаги обратно не разбирается — это односторонняя
   сборка. Поэтому конструктор сохраняет рядом рецепт (шаги в том виде, в
   каком их прислал браузер), и правка открывает именно его. */
async function editScenario(key) {
    let рецепт;
    try {
        рецепт = await api('/api/recorder/recipe/' + encodeURIComponent(key));
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    if (!S.active) {
        return pickPhone('На каком телефоне править?', serial => {
            openDevice(serial);
            editScenario(key);
        });
    }

    REC.teach = null;
    REC.nextId = 1;
    REC.params = рецепт.params || {};
    REC.steps = (рецепт.steps || []).map(шаг => recAdopt(шаг, рецепт.assets || {}));
    recBlocksFromSpan();
    REC.open = null;
    REC.edit = {key: key, meta: рецепт.meta || {}};
    /* Ширина устройства записи: кропы приехали с него, и масштаб шаблона на
       прогоне считается от неё. Устройство, на котором правят, может быть
       другим — тогда новые кропы окажутся в чужом масштабе, поэтому дописывать
       картиночные шаги лучше на том же экране, что и записывали. */
    REC.baseWidth = рецепт.screen_width || null;

    recOpen(true);
    /* recBanner сам экранирует текст — esc() здесь дал бы «&laquo;» в глаза. */
    recBanner(`правим сценарий «${recRecipeName(рецепт)}»: шаги можно удалять,`
        + ' переставлять и дописывать.');
    recSync();
    recEditRestore(key, рецепт.assets || {});
}

function recRecipeName(рецепт) {
    return (рецепт.meta && рецепт.meta.name) || рецепт.key || '';
}

/* Шаг из рецепта в шаг конструктора. Рецепт хранит то, что уедет в файл, а
   конструктору нужно чуть больше: свой id и цепочка alts под радиокнопки
   выбора селектора. Скриншота и рамки цели в рецепте нет — миниатюры у
   загруженных шагов не будет, пока их не перезапишут записью. */
function recAdopt(шаг, assets) {
    const out = {
        id: REC.nextId++,
        kind: шаг.kind,
        args: Object.assign({}, шаг.args || {}),
        selector: шаг.selector
            ? {call: шаг.selector.call, args: шаг.selector.args}
            : null,
        param: шаг.param || null,
        note: шаг.note || '',
        warn: '',
        adopted: true,
        texts: шаг.texts || [],
        point: шаг.point || null,
        any: шаг.any || null,
        arms: шаг.arms || null,
        pos: шаг.pos || null,
        optional: шаг.optional || false,
        retries: шаг.retries || 0,
        /* report значим только у развилки — у остальных шагов его нет ни в
           рецепте, ни в payload. */
        report: шаг.kind === 'branch' ? шаг.report !== false : undefined,
        crop: (шаг.crop && assets[шаг.crop]) || null,
        cropName: шаг.crop || null,   // по нему кроп находится после черновика
    };
    /* Запасные селекторы живут в alts: recFallbacks() собирает их оттуда, и
       без восстановления цепочка терялась бы при первой же перезаписи. */
    if (шаг.selector) {
        out.alts = [{call: шаг.selector.call, args: шаг.selector.args}].concat(
            (шаг.selector.fallbacks || []).map(
                args => ({call: 'click', args: args})));
    }
    return out;
}

/* Черновик правки лежит под своим ключом: иначе сеанс правки затирал бы
   незаконченную запись нового сценария. */
function recDraftKey() {
    return REC.edit ? REC_DRAFT_KEY + '.' + REC.edit.key : REC_DRAFT_KEY;
}

function recEditRestore(key, assets) {
    let draft;
    try {
        draft = JSON.parse(localStorage.getItem(REC_DRAFT_KEY + '.' + key) || 'null');
    } catch (e) {
        return;
    }
    if (!draft || !draft.steps || !draft.steps.length) return;
    /* Как и у черновика новой записи: отказ черновик не стирает. Уносить
       работу случайным «нет» дороже, чем спросить второй раз. Стирается он
       сохранением изменений или выходом из правки. */
    confirmModal('Вернуться к незаконченной правке?',
        `<p>С прошлого раза остались несохранённые изменения этого сценария:
         <b>${draft.steps.length}</b> шагов.</p>
         <p style="color:var(--dim)">Отказ черновик не стирает.</p>`,
        'Вернуться к правке',
        () => {
            REC.steps = draft.steps;
            REC.params = draft.params || {};
            REC.nextId = draft.nextId || (REC.steps.length + 1);
            /* Кропы в черновик не попали — возвращаем их по именам из файла. */
            REC.steps.forEach(шаг => {
                if (шаг.cropName && assets[шаг.cropName]) шаг.crop = assets[шаг.cropName];
            });
            recRender();
            recSync();
        });
}
