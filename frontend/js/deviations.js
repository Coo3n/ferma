'use strict';

/* Отклонения от сценария: то, что должен разобрать человек.

   Не «тревоги»: этим словом на ферме уже зовут здоровье устройств — перегрев
   и заряд (см. фильтр «Тревоги» на ферме).

   Журнал задач отвечает «что стало с задачей», отклонения — «где ферма пошла
   не по сценарию». Поэтому это отдельный раздел, а не фильтр по журналу:
   строка тут одна на причину, со счётчиком по устройствам, и с ней можно
   что-то сделать — научить обходить, дойти до задачи, закрыть. */

const DEVIATIONS_LIMIT = 60;

/* Подписи видов. Ключи — те же строки, что в farm/deviations.py: список там
   закрытый, и незнакомый вид означает, что сервер и интерфейс разъехались. */
const DEVIATION_KIND = {
    fail: {label: 'Сценарий упал', many: 'Падения', hint: 'сценарий остановился'},
    hold: {label: 'Ждёт решения', many: 'Ждут решения', hint: 'запуск ждёт на шаге'},
    escape: {label: 'Пройдено вслепую', many: 'Вслепую', hint: 'незнакомый экран обошли наугад'},
    branch: {label: 'Новый экран', many: 'Новые экраны', hint: 'развилка не узнала экран'},
    lost: {label: 'Сбился с пути', many: 'Сбился', hint: 'приложение закрылось или экран застыл'},
    layer: {label: 'Шаг на грани', many: 'Шаг на грани', hint: 'кнопка нашлась запасным способом — шаг может сломаться'},
};

/* Фильтр по типу: человек приходит с вопросом «что упало», а не листать всё. */
const DVN = {kind: '', unseenOnly: false};

function setDeviationFilter(kind) {
    DVN.kind = DVN.kind === kind ? '' : kind;
    renderDeviations();
}

function renderDeviationKinds(list) {
    const box = $('dvnKinds');
    if (!box) return;
    const counts = {};
    list.forEach(d => { counts[d.kind] = (counts[d.kind] || 0) + 1; });
    const kinds = Object.keys(DEVIATION_KIND).filter(k => counts[k]);
    setHTML(box, kinds.length > 1 || DVN.kind ? `<button class="hs-f${DVN.kind ? '' : ' on'}" aria-pressed="${!DVN.kind}"
        onclick="setDeviationFilter('')">Все <b>${list.length}</b></button>` + kinds.map(k => `
      <button class="hs-f dk-${k}${DVN.kind === k ? ' on' : ''}" aria-pressed="${DVN.kind === k}"
        onclick="setDeviationFilter('${k}')"><i aria-hidden="true"></i>${DEVIATION_KIND[k].many} <b>${counts[k]}</b></button>`).join('') : '');
}

function deviationAge(at) {
    const sec = Math.max(0, Math.round(Date.now() / 1000 - at));
    if (sec < 60) return sec + ' с назад';
    if (sec < 3600) return Math.round(sec / 60) + ' мин назад';
    if (sec < 86400) return Math.round(sec / 3600) + ' ч назад';
    return Math.round(sec / 86400) + ' дн назад';
}

/* Кнопка обучения — только там, где есть чему учить: без слепка преграды
   обучать нечему, а кнопка, ведущая в никуда, хуже её отсутствия. */
function deviationActions(item) {
    const out = [];
    /* Запуск ещё ждёт — «Показать, как быть» в полосе решения делает то же
       и вдобавок продолжает запуск; вторая кнопка обучения была бы дублем. */
    if (item.obstacle_file && item.job_id && !(item.kind === 'hold' && stillHeld(item))) {
        out.push(`<button class="sm accent" onclick="teachDeviation('${item.id}')">Научить закрывать это окно</button>`);
    }
    if (item.job_id) {
        out.push(`<a href="#" onclick="deviationToJob('${item.id}');return false">к запуску</a>`);
    }
    if (item.scenario_key) {
        out.push(`<a href="#" onclick="deviationToScenario('${item.id}');return false">к сценарию</a>`);
    }
    if (!item.seen) {
        out.push(`<a href="#" class="dim" onclick="deviationSeen('${item.id}');return false">отметить прочитанным</a>`);
    }
    return out.join('');
}

/* Задача ещё стоит и ждёт ответа? Решать можно только пока держится
   устройство: после HOLD_TIMEOUT или чужого ответа кнопки соврали бы. Правду
   про это знает журнал задач, а не строка отклонения — она написана один раз
   в момент остановки. */
function stillHeld(item) {
    return (S.jobs || []).some(job => job.id === item.job_id && job.status === 'held');
}

/* Какая починка шага возможна у отклонения. step_index >= 0 бывает только у
   записанных сценариев (у них есть рецепт), поэтому без него чинить нечего.
   Для 'hold' «ещё держится ли устройство» тут не проверяем: это знает
   holdActions по журналу задач. */
function deviationRepairMode(item) {
    if (!item || !(Number.isInteger(item.step_index) && item.step_index >= 0)) return null;
    if (item.kind === 'fail') {
        return item.job_id && item.shot && item.scenario_key ? 'fail' : null;
    }
    if (item.kind === 'hold') return item.scenario_key ? 'hold' : null;
    return null;
}

/* repair.js подключается отдельно; без него кнопка должна честно сказать
   об этом, а не молча ничего не сделать. Аргументы — только из данных
   отклонения, а не из строк обработчиков. */
function callRepair(args) {
    if (typeof repairOpen !== 'function') {
        toast('починка шага не загрузилась — обновите страницу', 'bad');
        return;
    }
    repairOpen(args);
}

function deviationRepairFail(id) {
    const item = findDeviation(id);
    if (!item || deviationRepairMode(item) !== 'fail') return;
    callRepair({
        mode: 'fail',
        scenarioKey: item.scenario_key,
        stepIndex: item.step_index,
        dumpUrl: '/api/deviations/' + encodeURIComponent(item.id) + '/dump',
        miss: parseMiss(item),
        title: item.title,
        /* Починили — отклонение разобрано: помечаем прочитанным. */
        onDone: () => deviationSeen(item.id),
    });
}

function deviationRepairHold(id) {
    const item = findDeviation(id);
    if (!item || deviationRepairMode(item) !== 'hold') return;
    const job = (S.jobs || []).find(j => j.id === item.job_id);
    if (!job) {
        toast('этого запуска уже нет в журнале', 'bad');
        return;
    }
    callRepair({
        mode: 'hold',
        scenarioKey: item.scenario_key,
        stepIndex: item.step_index,
        dumpUrl: '/api/devices/' + encodeURIComponent(job.serial) + '/inspect',
        jobId: item.job_id,
        miss: parseMiss(item),
        title: item.title,
        onDone: () => deviationSeen(item.id),
    });
}

/* Главное действие карточки падения — кнопкой, а не ещё одной ссылкой. */
function deviationRepairButton(item) {
    if (deviationRepairMode(item) !== 'fail') return '';
    return `<div class="dvn-repair">
      <button type="button" class="sm accent" data-id="${esc(item.id)}"
        onclick="deviationRepairFail('${item.id}')">
        <svg class="ic" aria-hidden="true"><use href="#i-wrench"/></svg>Починить шаг</button>
    </div>`;
}

function holdActions(item) {
    if (item.kind !== 'hold' || !stillHeld(item)) return '';
    const задача = (S.jobs || []).find(j => j.id === item.job_id);
    /* Та же разметка, что у полосы в журнале задач (jobs.js: heldChoiceHtml):
       одна главная кнопка, остальное мелким «или:». */
    return heldChoiceHtml(задача || {id: item.job_id}, {
        /* repairable — вердикт сервера по рецепту (runner.hold_repairable). */
        repair: deviationRepairMode(item) === 'hold' && задача && задача.repairable
            ? `deviationRepairHold('${esc(item.id)}')` : '',
        open: `deviationToDevice('${esc(item.id)}')`,
    });
}

/* Экран остановленной задачи ещё на телефоне — за ним и идут. */
function deviationToDevice(id) {
    const item = findDeviation(id);
    if (!item) return;
    const job = (S.jobs || []).find(j => j.id === item.job_id);
    if (!job) {
        toast('этого запуска уже нет в журнале', 'bad');
        return;
    }
    openDevice(job.serial);
}

/* ------------------------------------------------------------- скриншот */

/* Адрес картинки строим на клиенте: ещё один запрос за метаданными на каждую
   карточку списка был бы лишним, а имя файла и задача у отклонения уже есть. */
function deviationShotUrl(item) {
    return `/api/jobs/${encodeURIComponent(item.job_id)}/artifacts/${encodeURIComponent(item.shot)}`;
}

/* miss приходит строкой JSON или пустой строкой. Битый слепок не должен
   ронять отрисовку всего списка, поэтому тут никогда не бросаем. */
function parseMiss(item) {
    try {
        const value = JSON.parse(item && item.miss ? item.miss : '');
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch (e) {
        return {};
    }
}

/* Точка промаха нормирована к 0..1. Всё остальное (строки, NaN, за краем
   кадра) маркером рисовать нельзя: он показал бы не туда, а ложная подсказка
   хуже её отсутствия. */
function missPoint(miss) {
    const at = miss && miss.at;
    if (!Array.isArray(at) || at.length !== 2) return null;
    const [x, y] = at;
    const ok = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1;
    return ok(x) && ok(y) ? {x, y} : null;
}

/* Состояние загрузки переключают классы на обёртке: обработчики короткие, а
   данных в них нет. */
const SHOT_IMG_EVENTS = `onload="this.parentNode.classList.add('ok')"
     onerror="this.parentNode.classList.add('gone')"`;

function deviationThumb(item) {
    if (!(item.shot && item.job_id)) return '';
    return `<button type="button" class="dvn-shot" data-id="${esc(item.id)}"
      aria-label="${esc('Открыть снимок экрана: ' + item.title)}"
      onclick="openDeviationShot(this.dataset.id)">
      <img loading="lazy" decoding="async" alt="" src="${esc(deviationShotUrl(item))}"
           ${SHOT_IMG_EVENTS}>
      <span class="dvn-gone">снимок удалён</span>
    </button>`;
}

/* Тело окна собирается из готовых кусков, чтобы его можно было проверить
   без браузера. Картинка не вписывается object-fit: проценты маркера
   должны ложиться ровно на пиксели снимка. */
function deviationShotBody(item, miss) {
    const point = missPoint(miss);
    const marker = point
        ? `<span class="dvn-mark${point.x > 0.6 ? ' flip' : ''}${point.y < 0.1 ? ' below' : ''}" style="left:${point.x * 100}%;top:${point.y * 100}%">
             <i></i><b>ожидали здесь</b></span>`
        : '';
    const rows = [];
    if (item.scenario_name) rows.push(['сценарий', esc(item.scenario_name)]);
    if ((item.devices || []).length) {
        rows.push([item.devices.length > 1 ? 'телефоны' : 'телефон',
            esc(item.devices.join(', '))]);
    }
    if (Number.isInteger(item.step_index) && item.step_index >= 0) {
        rows.push(['шаг', '«' + (item.step_index + 1) + '»']);
    }
    if (Array.isArray(miss.sel) && miss.sel.length) {
        rows.push(['что искали', `<code class="dvn-code">${esc(JSON.stringify(miss.sel[0]))}</code>`]);
    }
    if (Array.isArray(miss.text) && miss.text.length) {
        rows.push(['текст', esc(miss.text.join(', '))]);
    }
    return `<div class="dvn-big">
      <img alt="${esc('Экран телефона в момент проблемы: ' + item.title)}"
           src="${esc(deviationShotUrl(item))}" ${SHOT_IMG_EVENTS}>
      <span class="dvn-gone">снимок удалён</span>
      ${marker}
    </div>
    ${rows.map(([k, v]) => `<div class="kv"><span>${esc(k)}</span><b>${v}</b></div>`).join('')}`;
}

function openDeviationShot(id) {
    const item = findDeviation(id);
    if (!item || !item.shot || !item.job_id) return;
    $('mTitle').textContent = item.title;
    $('mBody').innerHTML = deviationShotBody(item, parseMiss(item));
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="primary" onclick="closeModal()">Закрыть</button>';
    modalSheet('wide');
    openModal();
}

/* Группировка — только отображение: карточки и их состояние в S.deviations
   не меняются, каждая по-прежнему решается независимо (см. holdActions).
   «ждёт» намеренно не сливается в data.deviations (у каждой задачи свой
   ответ), но при повторных прогонах в одну и ту же слабую цель это даёт
   вереницу одинаковых строк подряд — тут их сворачиваем в одну, разворачивая
   по клику. */
function deviationGroupKey(item) {
    return (item.kind === 'hold' && !item.seen)
        ? `${item.title}\u0000${item.scenario_key || ''}`
        : null;
}

function groupDeviations(list) {
    const groups = [];
    const open = new Map();
    for (const item of list) {
        const key = deviationGroupKey(item);
        const bucket = key ? open.get(key) : null;
        if (bucket) {
            bucket.extra.push(item);
            continue;
        }
        const group = {main: item, extra: []};
        groups.push(group);
        if (key) open.set(key, group);
    }
    return groups;
}

/* Раскрытые группы помним сами: список перерисовывается каждые 6 с, и
   без этого группа схлопывалась у человека под курсором. */
const DVN_OPEN = new Set();

function deviationGroupToggle(gid, count) {
    const el = document.getElementById(gid);
    if (!el) return;
    const opened = el.classList.toggle('open');
    if (opened) DVN_OPEN.add(gid); else DVN_OPEN.delete(gid);
    const btn = el.querySelector('.dvn-group-toggle');
    if (btn) setText(btn, opened ? 'свернуть' : `+ ${count} похожих`);
}

function deviationGroupCard(group) {
    const main = deviationCard(group.main);
    if (!group.extra.length) return main;
    const gid = 'dvg-' + esc(group.main.id);
    const more = group.extra.map(deviationCard).join('');
    const opened = DVN_OPEN.has(gid);
    return `<div class="dvn-group${opened ? ' open' : ''}" id="${gid}">
    ${main}
    <button type="button" class="sm dvn-group-toggle"
            onclick="deviationGroupToggle('${gid}', ${group.extra.length})">
      ${opened ? 'свернуть' : `+ ${group.extra.length} похожих`}</button>
    <div class="dvn-group-more">${more}</div>
  </div>`;
}

/* Карточка проблемы в три уровня: что случилось (тип + заголовок),
   подробность одной строкой, справа — где и сколько. Главное действие —
   одна кнопка, остальное мелкими ссылками. Раньше всё шло одним весом:
   бейдж капсом, заголовок, мета через точки — сплошной текст. */
function deviationCard(item) {
    const kind = DEVIATION_KIND[item.kind] || {label: item.kind, hint: ''};
    const devices = item.devices || [];
    const phones = devices.length
        ? `${devices.length} ${declOfNum(devices.length, ['телефон', 'телефона', 'телефонов'])}` : '';
    const thumb = deviationThumb(item);
    const step = Number.isInteger(item.step_index) && item.step_index >= 0 ? `, шаг ${item.step_index + 1}` : '';
    return `<article class="dvn dvn--${esc(item.kind)} ${item.seen ? 'seen' : ''} ${thumb ? 'has-shot' : ''}">
    ${thumb}
    <div class="dvn-main">
      <div class="dvn-kind" title="${esc(kind.hint)}"><i aria-hidden="true"></i>${esc(kind.label)}${item.seen ? '' : ' <span class="dvn-new">новое</span>'}</div>
      <h3 class="dvn-title">${esc(item.title)}</h3>
      ${item.detail ? `<p class="dvn-detail">${esc(item.detail)}</p>` : ''}
      ${deviationRepairButton(item)}
      ${holdActions(item)}
      <div class="dvn-acts">${deviationActions(item)}</div>
    </div>
    <dl class="dvn-facts">
      ${item.scenario_name ? `<div><dt>Сценарий</dt><dd>${esc(item.scenario_name)}${step}</dd></div>` : ''}
      ${phones ? `<div><dt>Где</dt><dd title="${esc(devices.join(', '))}">${phones}</dd></div>` : ''}
      ${item.hits > 1 ? `<div><dt>Повторов</dt><dd>${item.hits}</dd></div>` : ''}
      <div><dt>Когда</dt><dd class="dvn-age" data-at="${esc(item.last_at)}"></dd></div>
    </dl>
    <button class="xdel" title="Убрать из списка" aria-label="Убрать проблему из списка"
            onclick="deviationDelete('${item.id}')">✕</button>
  </article>`;
}

/* Возраст меняется каждый опрос, и будь он в строке HTML, список
   пересоздавался бы целиком вместе с миниатюрами — они мигали бы. Поэтому
   в разметке возраста нет, а вписывается он на месте после setHTML. */
function refreshDeviationAges() {
    document.querySelectorAll('#dvnList .dvn-age[data-at]').forEach(node =>
        setText(node, deviationAge(Number(node.dataset.at))));
}

async function pollDeviations() {
    let data;
    try {
        data = await api(`/api/deviations?limit=${DEVIATIONS_LIMIT}`);
    } catch (e) {
        return;
    }
    /* Кнопки решения зависят от статуса задачи, а не от строки отклонения:
       без свежего журнала они висели бы над задачей, которая давно упала. */
    if (!(S.jobs || []).length) await pollJobs();
    S.deviations = data.deviations;
    /* Число непрочитанных уже на вкладке «Проблемы» — здесь только «всего». */
    setText($('dvnCount'), data.deviations.length ? `всего: ${data.deviations.length}` : '');
    renderDeviations();
    refreshDeviationAges();
    repointModalReturn();
}

function renderDeviations() {
    const all = S.deviations || [];
    renderDeviationKinds(all);
    const list = DVN.kind ? all.filter(d => d.kind === DVN.kind) : all;
    setHTML($('dvnList'), list.length
        ? groupDeviations(list).map(deviationGroupCard).join('')
        /* Пусто здесь значит «всё хорошо» — единственная заглушка без
           кнопки и шагов: звать никуда не надо, отклонения приходят сами. */
        : emptyBig({
            art: 'calm',
            title: 'Проблем нет',
            text: 'Сюда попадут падения и незнакомые экраны.',
        }));
    refreshDeviationAges();
}

/* Список пересоздаётся каждый опрос, а окно скрина может быть открыто:
   миниатюра, с которой оно открылось, к тому времени отсоединена, и
   closeModal не вернул бы на неё фокус. Перенацеливаем на новый элемент с тем
   же id и того же вида (миниатюра или кнопка починки — у них общий id
   отклонения, различает их класс). */
function repointModalReturn() {
    if (typeof modalReturn === 'undefined' || !modalReturn) return;
    if (modalReturn.isConnected || !modalReturn.dataset || !modalReturn.dataset.id) return;
    const id = modalReturn.dataset.id;
    const kind = modalReturn.className;
    const fresh = Array.from(document.querySelectorAll('#dvnList [data-id]'))
        .find(node => node.dataset.id === id && node.className === kind);
    if (fresh) modalReturn = fresh;
}

function findDeviation(id) {
    return (S.deviations || []).find(item => item.id === id);
}

/* Обучение прямо из строки. Слепок преграды лежит в артефактах задачи,
   поэтому отклонение помнит и задачу, и имя файла: за один прогон незнакомых
   экранов бывает несколько, и слепок у каждого свой. */
function teachDeviation(id) {
    const item = findDeviation(id);
    if (!item) return;
    deviationSeen(id);
    teachDetour(item.job_id, item.obstacle_file);
}

function deviationToJob(id) {
    const item = findDeviation(id);
    if (!item) return;
    /* Журнал задач держит последние сотни: задача могла из него вытесниться,
       а отклонение — остаться. Молчать в этом случае нельзя. */
    if (!(S.jobs || []).some(job => job.id === item.job_id)) {
        toast('этого запуска уже нет в журнале', 'bad');
        return;
    }
    showView('jobs');
    pickJob(item.job_id);
}

function deviationToScenario(id) {
    const item = findDeviation(id);
    if (!item) return;
    if (!(S.scenarios || []).some(s => s.key === item.scenario_key)) {
        toast('сценарий больше не найден', 'bad');
        return;
    }
    showView('scen');
    pickScenario(item.scenario_key);
}

function deviationSeen(id) {
    return post(`/api/deviations/${id}/seen`)
        .then(() => {
            pollDeviations();
            pollStatus();
        })
        .catch(e => toast(e.message, 'bad'));
}

function deviationsSeenAll() {
    return post('/api/deviations/seen')
        .then(result => {
            toast(`отмечено прочитанными: ${result.marked}`);
            pollDeviations();
            pollStatus();
        })
        .catch(e => toast(e.message, 'bad'));
}

function deviationDelete(id) {
    return api('/api/deviations/' + id, {method: 'DELETE'})
        .then(() => {
            pollDeviations();
            pollStatus();
        })
        .catch(e => toast(e.message, 'bad'));
}

function deviationsClear() {
    confirmModal('Очистить список проблем?',
        '<p>Снимки в журнале и автозакрытия останутся.</p>',
        'Очистить', () => {
            post('/api/deviations/clear')
                .then(result => {
                    toast(`убрано проблем: ${result.removed}`, 'ok');
                    pollDeviations();
                    pollStatus();
                })
                .catch(e => toast(e.message, 'bad'));
        }, true);
}
