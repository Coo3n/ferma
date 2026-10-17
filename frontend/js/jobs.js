'use strict';

/* Журнал задач: список, живой лог, артефакты, отмена и удаление. */

const JOBS_LIMIT = 80;
const BATCH_LIMIT = 1000;
const AUTOSCROLL_SLACK = 40;
/* Журнал не выбран — не ошибка и не пустота: слева есть что выбрать.
   Поэтому шагов и кнопки нет, только объяснение, что здесь будет. */
function jobLogEmptyHtml() {
    return emptyBig({
        art: 'log',
        title: 'Подробности запуска',
        text: 'Выберите запуск слева — здесь будет его журнал.',
    });
}

function isActive(status) {
    return status === 'queued' || status === 'running' || status === 'held'
        || status === 'cancelling';
}

/* CANCELLING — отмена уже принята, но шаг ещё не дошёл до проверки. Кнопку
   отмены прятать надо: второе нажатие ничего не меняет, а выглядит как
   «первое не сработало». */
function isCancelling(status) {
    return status === 'cancelling';
}

/* Решения, которые можно принять над остановленной задачей. Строки — те же,
   что в farm/context.py: их знают шаг, очередь и API, и расхождение здесь
   означало бы 400 на каждое нажатие. */
const JOB_DECISIONS = [
    ['retry', 'повторить шаг', 'Попробовать шаг заново'],
    ['skip', 'пропустить шаг', 'Идти дальше без этого шага'],
    ['drop', 'завершить со сбоем', 'Засчитать как сбой'],
    /* Только для шага вслепую (held_kind === 'blind'): экран нужный, идти дальше. */
    ['go', 'продолжить как есть', 'Пройти шаг как записано'],
];

/* «lost» — сторож долгого цикла: не шаг промахнулся, а экран не тот. Те же
   решения, но подписи про экран, а не про шаг. */
const LOST_WORDS = {
    retry: ['я поправил — продолжить', 'Экран снова свой — работать дальше'],
    skip: ['не обращать внимания', 'Идти дальше как есть'],
    drop: ['завершить', 'Засчитать как сбой'],
};

function jobDecisions(kind) {
    const list = JOB_DECISIONS.filter(([код]) => код !== 'go' || kind === 'blind');
    return kind === 'lost' ? list.map(([код, ...rest]) => [код, ...(LOST_WORDS[код] || rest)]) : list;
}

/* «Дошло, но не совсем»: цель нашлась запасным слоем резолвера (картинка,
   координаты), а не селектором или текстом. Задача не упала и не встала —
   выглядит обычным зелёным PASSED, — но экран в конце мог оказаться не тем,
   и без этого значка узнать об этом можно было только вручную сверив id
   задачи со списком «Отклонения». */
function jobDegradedBadge(job) {
    if (!job.degraded) return '';
    return `<span class="degraded" title="Кнопка нашлась запасным способом — проверьте результат" aria-label="Есть предупреждение">⚠</span>`;
}

/* Отмена одной задачи — прямо в карточке. Раньше она жила только в строке
   артефактов справа (и то без queued), и из списка оставалось лишь
   «Отменить всё». В CANCELLING кнопки нет: второе нажатие ничего не даст. */
function jobCardAction(job) {
    if (isCancelling(job.status)) return '';
    if (isActive(job.status))
        return `<button class="xstop" title="Остановить этот запуск" aria-label="Остановить запуск"
             onclick="event.stopPropagation();cancelJob('${job.id}')">■</button>`;
    return `<button class="xdel" title="Удалить из журнала" aria-label="Удалить из журнала"
             onclick="event.stopPropagation();deleteJob('${job.id}')">✕</button>`;
}

function jobCard(job) {
    const remove = jobCardAction(job);
    return `<div class="job ${S.job === job.id ? 'on' : ''}" data-kbd tabindex="0" role="button"
         aria-label="${esc(job.scenario_name + ' · ' + job.device_name + ' · ' + jobStatusWord(job.status))}"
         onclick="pickJob('${job.id}')">
    <span class="badge b-${job.status}">${jobStatusWord(job.status)}</span>${jobDegradedBadge(job)}
    <span class="nm">${esc(job.scenario_name)} · ${esc(job.device_name)}${window.jobProgressHtml ? jobProgressHtml(job) : ''}</span>
    <span style="color:var(--dim)">${job.duration ? job.duration + ' с' : ''}</span>
    ${remove}
  </div>`;
}

async function pollJobs() {
    let list;
    try {
        /* Запуск на 100 телефонов не влезает в общий лимит — его задачи
           берём целиком отдельным запросом, иначе полоса «на N тел.» врёт. */
        list = await api(S.runBatch
            ? `/api/jobs?limit=${BATCH_LIMIT}&batch=${encodeURIComponent(S.runBatch)}`
            : `/api/jobs?limit=${JOBS_LIMIT}`);
    } catch (e) {
        return;
    }
    S.jobs = list;
    if (window.syncInteractive) syncInteractive();
    const shown = S.runBatch ? list.filter(j => j.batch === S.runBatch) : list;
    /* Пустой журнал: справа нечего «выбирать слева», а кнопки чистки и
       отмены работать не с чем — объясняем, а не молчим. */
    $('view-jobs').classList.toggle('no-jobs', !list.length);
    disableWithReason($('btnClearJobs'), !list.some(j => !isActive(j.status)), 'Завершённых запусков нет');
    disableWithReason($('btnCancelAll'), !list.some(j => isActive(j.status)), 'Сейчас ничего не идёт');
    renderBatchBar(shown);
    setHTML($('jobList'), shown.length
        ? (S.runBatch ? shown.map(jobCard).join('') : runGroupsHtml(shown))
        : emptyBig({
            art: 'job',
            title: 'Запусков пока не было',
            text: 'Запустите сценарий на телефонах — здесь будет журнал.',
            action: {label: 'К сценариям', icon: 'right', onClick: "showView('scen')"},
        }));
    /* Правая колонка на первом открытии раздела: resetJobView() зовут
       только при удалении и отмене, а объяснить, что здесь будет, надо и
       до первого клика по задаче. */
    if (S.job) refreshJobLog();
    else if (!$('jobLogEmpty').innerHTML) $('jobLogEmpty').innerHTML = jobLogEmptyHtml();
}

/* Список запусков сгруппирован по нажатию «Запустить», как прогоны в CI:
   «vk_auth на 40 · 30 готово · 2 сбоя» одной строкой с прогрессом, а сорок
   задач внутри — по клику. Сплошной список из сорока одинаковых строк не
   отвечал на вопрос «как прошёл запуск». Одиночные задачи — как есть. */
const RUNS_OPEN = new Set();

function runGroupsHtml(jobs) {
    const groups = [];
    const byBatch = new Map();
    for (const j of jobs) {
        if (j.batch && byBatch.has(j.batch)) {
            byBatch.get(j.batch).jobs.push(j);
            continue;
        }
        const g = {batch: j.batch, jobs: [j]};
        groups.push(g);
        if (j.batch) byBatch.set(j.batch, g);
    }
    return groups.map(g => g.jobs.length < 2 ? jobCard(g.jobs[0]) : runGroupHtml(g)).join('');
}

function runGroupHtml(g) {
    const n = g.jobs.length;
    const done = g.jobs.filter(j => j.status === 'passed').length;
    const fail = g.jobs.filter(j => j.status === 'failed').length;
    const held = g.jobs.filter(j => j.status === 'held').length;
    const live = g.jobs.filter(j => isActive(j.status)).length;
    const open = RUNS_OPEN.has(g.batch) || g.jobs.some(j => j.id === S.job);
    const phones = new Set(g.jobs.map(j => j.serial)).size;
    const st = held ? 'held' : live ? 'running' : fail ? 'failed' : 'passed';
    return `<section class="rgroup rg-${st}${open ? ' open' : ''}">
    <button class="rg-head" aria-expanded="${open}" onclick="toggleRunGroup('${esc(g.batch)}')">
      <span class="rg-title"><b>${esc(g.jobs[0].scenario_name)}</b> на ${phones} ${declOfNum(phones, ['телефоне', 'телефонах', 'телефонах'])}</span>
      <span class="rg-counts">
        ${done ? `<span class="ok">${done} готово</span>` : ''}
        ${fail ? `<span class="bad">${fail} ${declOfNum(fail, ['сбой', 'сбоя', 'сбоев'])}</span>` : ''}
        ${held ? `<span class="warn">${held} ждёт</span>` : ''}
        ${live - held > 0 ? `<span class="busy">${live - held} идёт</span>` : ''}
      </span>
      <span class="bb-track" aria-hidden="true"><i class="ok" style="width:${done / n * 100}%"></i><i class="bad" style="width:${fail / n * 100}%"></i></span>
    </button>
    ${open ? `<div class="rg-body">${g.jobs.map(jobCard).join('')}
      <button class="sm ghost rg-only" onclick="showRuns('${esc(g.batch)}')">Только этот запуск</button></div>` : ''}
  </section>`;
}

function toggleRunGroup(batch) {
    if (RUNS_OPEN.has(batch)) RUNS_OPEN.delete(batch); else RUNS_OPEN.add(batch);
    pollJobs();
}

/* «Запуски» после нажатия «Запустить» — про этот запуск, а не про всю
   историю: «auth на 40: 12 готово · 1 сбой · 27 в работе». */
function showRuns(batch) {
    S.runBatch = batch || '';
    showView('jobs');
    pollJobs();
}

function renderBatchBar(jobs) {
    const bar = $('jobBatch');
    if (!bar) return;
    if (!S.runBatch || !jobs.length) {
        if (S.runBatch && !jobs.length && S.jobs.length) S.runBatch = '';   // запуск ушёл из истории
        bar.hidden = true;
        return;
    }
    const done = jobs.filter(j => j.status === 'passed').length;
    const fail = jobs.filter(j => j.status === 'failed').length;
    const live = jobs.filter(j => isActive(j.status)).length;
    const phones = new Set(jobs.map(j => j.serial)).size;
    bar.hidden = false;
    setHTML(bar, `<span class="bb-title"><b>${esc(jobs[0].scenario_name)}</b> на ${phones} тел.</span>
      <span class="bb-n ok"><b>${done}</b> готово</span>
      ${fail ? `<span class="bb-n bad"><b>${fail}</b> сбой</span>` : ''}
      ${live ? `<span class="bb-n busy"><b>${live}</b> в работе</span>` : ''}
      <span class="bb-track" aria-hidden="true"><i class="ok" style="width:${done / jobs.length * 100}%"></i><i class="bad" style="width:${fail / jobs.length * 100}%"></i></span>
      <span class="sp"></span>
      <button class="sm" onclick="showRuns()">Показать все запуски</button>`);
}

/* «Починить шаг» у упавшей задачи — та же кнопка, что на карточке
   «Проблем»: падение уже лежит там отклонением со скрином и шагом. */
function jobRepairHtml(job) {
    if (job.status !== 'failed' || !window.deviationRepairButton) return '';
    const item = (S.deviations || []).find(d => d.job_id === job.id && d.kind === 'fail');
    if (!item) {
        /* Отклонения грузятся только на «Проблемах» — подтягиваем один раз
           на задачу, а не на каждом опросе журнала. */
        if (S.repairAskedFor !== job.id && window.pollDeviations) {
            S.repairAskedFor = job.id;
            pollDeviations().then(refreshJobLog);
        }
        return '';
    }
    return deviationRepairButton(item);
}

function pickJob(id) {
    S.job = id;
    pollJobs();
    refreshJobLog();
}

function cancelLink(job, label) {
    return `<a href="#" onclick="cancelJob('${job.id}');return false"
             style="color:var(--bad)">${label}</a>`;
}

/* Почему задача ещё жива после нажатия: шаг прервётся на ближайшей проверке
   отмены, а не посреди ожидания элемента. */
function cancellingNote() {
    return `<span style="color:var(--warn)">останавливаю — жду конца шага…</span>`;
}

/* Снимок экрана в момент остановки: ферма его уже сняла (hold_N.jpg,
   последний по счёту — самый свежий), просто раньше нигде не показывала
   рядом с решением. Без него человек не мог решить retry/skip/drop, не
   сходив на устройство и не вернувшись — лишний круг на каждую остановку. */
function jobHeldShotName(job) {
    const shots = (job.artifacts || []).filter(name => /^hold_\d+\.jpg$/.test(name));
    if (!shots.length) return '';
    return shots.sort((a, b) => Number(a.match(/\d+/)[0]) - Number(b.match(/\d+/)[0])).pop();
}

function jobHeldShotHtml(job, repair) {
    const name = jobHeldShotName(job);
    if (!name) return '';
    const url = `/api/jobs/${job.id}/artifacts/${encodeURIComponent(name)}`;
    const img = `<img loading="lazy" decoding="async" alt="" src="${esc(url)}"
           onload="this.parentNode.classList.add('ok')"
           onerror="this.parentNode.classList.add('gone')">`;
    /* Миниатюра — самое заметное в полосе, и по ней кликают первой. Если шаг
       можно починить кликом, она ведёт туда же, куда главная кнопка. */
    if (repair) {
        return `<button type="button" class="held-shot" onclick="${repair}"
          title="Указать на снимке, куда нажать" aria-label="Указать на снимке, куда нажать">${img}</button>`;
    }
    return `<a class="held-shot" href="${url}" target="_blank"
      aria-label="Открыть снимок экрана в момент остановки">${img}</a>`;
}

/* Что человеку делать с остановленной задачей — одна разметка на три места
   (журнал задач, рабочее место устройства, «Отклонения»).

   Раньше это были пять равных кнопок подряд, а самый прямой путь — «ткнуть
   на скрине, куда надо было нажать» — жил только в «Отклонениях», и о нём
   просто не знали. Теперь один главный шаг с подписью, что будет, остальное
   — мелкими «или:» ниже, а «уронить задачу» отодвинуто и красное.

   Главный шаг выбирается по тому, что вообще возможно:
     указать на скрине — шаг записанного сценария, кликом его и чинят;
     продолжить как есть — шаг вслепую: вопрос «экран тот?», а не «куда жать»;
     открыть устройство — поправить руками, когда чинить кликом нечего;
     повторить шаг — то же, но устройство уже открыто.

   opts.repair — onclick для починки (или '' — нельзя), opts.open — onclick
   «открыть устройство» (или '' — уже на нём). */
function heldChoiceHtml(job, opts) {
    const o = opts || {};
    const blind = job.held_kind === 'blind';
    const lost = job.held_kind === 'lost';
    const decide = код => `decideJob('${esc(job.id)}','${код}')`;
    const решения = jobDecisions(job.held_kind);
    const главное = lost && job.held_obstacle ? {onclick: `teachDetour('${esc(job.id)}','${esc(job.held_obstacle)}')`,
        icon: 'crosshair', label: 'Показать, как быть',
        hint: 'Покажите кликами на телефоне, что делать на этом экране. Ферма запомнит и продолжит сама.'}
        : lost ? {onclick: decide('retry'), icon: 'check', label: 'Я поправил — продолжить',
            hint: 'Поправьте экран мышью на телефоне и продолжите.'}
        : blind ? {onclick: decide('go'), icon: 'check', label: 'Экран нужный — продолжить',
        hint: 'Шаг пройден вслепую. Экран на снимке верный — продолжайте.'}
        : o.repair ? {onclick: o.repair, icon: 'crosshair', label: 'Указать на снимке, куда нажать',
            hint: 'Кликните нужный элемент — шаг исправится и повторится.'}
        : o.open ? {onclick: o.open, icon: 'external', label: 'Открыть телефон',
            hint: 'Поправьте экран и нажмите «повторить шаг».'}
        : {onclick: decide('retry'), icon: 'refresh', label: 'Повторить шаг',
            hint: 'Поправьте экран мышью и повторите шаг.'};
    const мелкие = решения
        .filter(([код]) => код !== 'drop' && !(blind && код === 'go')
            && !(!blind && !lost && !o.repair && !o.open && код === 'retry')
            && !(lost && !job.held_obstacle && код === 'retry'))
        .map(([код, подпись, зачем]) =>
            `<button class="sm ghost" title="${esc(зачем)}" onclick="${decide(код)}">${esc(подпись)}</button>`);
    if (o.open && главное.onclick !== o.open) {
        мелкие.push(`<button class="sm ghost" title="Поправить экран руками" onclick="${o.open}">открыть телефон</button>`);
    }
    const уронить = решения.find(([код]) => код === 'drop');
    return `<div class="held-choice">
      <button class="sm accent held-main" onclick="${главное.onclick}">
        <svg class="ic" aria-hidden="true"><use href="#i-${главное.icon}"/></svg>${esc(главное.label)}</button>
      <p class="held-hint">${esc(главное.hint)}</p>
      <div class="held-acts"><span class="held-or">или:</span>${мелкие.join('')}
        ${уронить ? `<button class="sm ghost held-drop" title="${esc(уронить[2])}"
          onclick="${decide('drop')}">${esc(уронить[1])}</button>` : ''}</div>
    </div>`;
}

/* Починка шага прямо из задачи: те же данные, что у отклонения «ждёт»
   (сценарий, номер шага, живой экран), лежат и в самой задаче. Промах (miss)
   берём у отклонения этой задачи, если оно уже пришло: с ним repair.js
   ловит сдвиг шагов в сценарии. */
function jobCanRepair(job) {
    /* repairable считает сервер по рецепту (runner.hold_repairable): только он
       знает, во что рендерится шаг. */
    return !!(job && job.repairable && job.held_kind !== 'blind' && job.scenario_key
        && Number.isInteger(job.step_index) && job.step_index >= 0);
}

function jobRepairHold(id) {
    const job = (S.jobs || []).find(j => j.id === id);
    if (!jobCanRepair(job)) return;
    if (typeof repairOpen !== 'function') {
        toast('починка шага не загрузилась — обновите страницу', 'bad');
        return;
    }
    const dvn = (S.deviations || []).find(d => d.job_id === id && d.kind === 'hold');
    repairOpen({
        mode: 'hold',
        scenarioKey: job.scenario_key,
        stepIndex: job.step_index,
        dumpUrl: '/api/devices/' + encodeURIComponent(job.serial) + '/inspect',
        jobId: job.id,
        miss: dvn && dvn.miss ? dvn.miss : '',
        title: job.held_reason,
        onDone: () => { if (dvn && window.deviationSeen) deviationSeen(dvn.id); },
    });
}

/* Остановленная задача держит устройство и экран: пока она ждёт, решение —
   единственное, что от человека нужно. Поэтому кнопки стоят прямо под
   журналом, а не в отдельной модалке. opts.onDevice — полоса стоит на
   рабочем месте этого же устройства: «открыть устройство» там лишнее. */
function decisionBar(job, opts) {
    if (job.status !== 'held') return '';
    const onDevice = !!(opts && opts.onDevice);
    const repair = jobCanRepair(job) ? `jobRepairHold('${esc(job.id)}')` : '';
    return `<div class="held-bar">
    <div class="held-body">
      ${jobHeldShotHtml(job, repair)}
      <div class="held-text">
        <div class="held-why"><svg class="ic"><use href="#i-alert"/></svg>
          <span>${esc(job.held_reason || 'запуск ждёт решения')}</span></div>
        ${heldChoiceHtml(job, {repair, open: onDevice ? '' : `openDevice('${esc(job.serial)}')`})}
      </div>
    </div>
  </div>`;
}

/* Ссылка на обучение. Показывается только там, где есть чему учить: слепок
   преграды снимается лишь при падении. */
function teachLink(job) {
    if (job.status !== 'failed'
        || !(job.artifacts || []).includes('obstacle.json')) return '';
    return `<a href="#" onclick="teachDetour('${job.id}');return false"
             style="color:var(--warn)">научить обходить</a>`;
}

function renderArtifacts(job) {
    const box = $('jobArts');
    const running = job.status === 'queued' || job.status === 'running'
        || job.status === 'held';
    const отменяется = isCancelling(job.status);

    if (job.artifacts && job.artifacts.length) {
        box.style.display = 'flex';
        box.innerHTML = job.artifacts.map(name =>
                `<a href="/api/jobs/${job.id}/artifacts/${encodeURIComponent(name)}"
          target="_blank">${esc(name)}</a>`).join('')
            + teachLink(job)
            + (running ? cancelLink(job, 'остановить') : '')
            + (отменяется ? cancellingNote() : '');
        return;
    }

    box.style.display = (running || отменяется) ? 'flex' : 'none';
    box.innerHTML = running ? cancelLink(job, 'остановить запуск')
        : отменяется ? cancellingNote() : '';
}

/* Живой экран задачи не пересоздаётся на каждый опрос (раз в POLL_JOBS_MS) —
   иначе собственное расписание кадра из thumbArm сбрасывалось бы чаще, чем
   успевал бы прийти новый. Пересобираем только когда сменилась сама задача
   или она перестала/начала быть активной. */
let jobLiveFor = null;

function jobLiveHtml(job) {
    return `<div class="job-live">
    <img class="job-live-img" alt="Экран телефона сейчас">
    <div class="job-live-info">
      <span>обновляется сам</span>
      <a href="#" onclick="openDevice('${esc(job.serial)}');return false">открыть телефон →</a>
    </div>
  </div>`;
}

function syncJobLive(job) {
    const box = $('jobLive');
    if (!box) return;
    const active = isActive(job.status);
    const ключ = active ? job.id : null;
    if (ключ === jobLiveFor) return;
    const old = box.querySelector('.job-live-img');
    if (old && window.thumbStop) thumbStop(old);
    if (!active) {
        box.innerHTML = '';
        jobLiveFor = null;
        return;
    }
    box.innerHTML = jobLiveHtml(job);
    const img = box.querySelector('.job-live-img');
    if (img && window.thumbArm) thumbArm(img, job.serial);
    jobLiveFor = ключ;
}

async function refreshJobLog() {
    if (!S.job) return;
    const wanted = S.job;
    let job;
    try {
        job = await api('/api/jobs/' + wanted);
    } catch (e) {
        return;
    }
    if (S.job !== wanted) return;   // пока ждали ответ, выбрали другую задачу
    syncJobLive(job);

    const pre = $('jobLog');
    /* Заглушку прячем до замера прокрутки: пока журнал скрыт, его
       scrollHeight равен нулю, и atBottom вышел бы ложным. */
    $('jobLogEmpty').innerHTML = '';
    pre.hidden = false;
    const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < AUTOSCROLL_SLACK;
    pre.textContent = (job.log || []).join('\n') || '(пусто)';
    if (atBottom) pre.scrollTop = pre.scrollHeight;

    const held = $('jobHeld');
    if (held) held.innerHTML = decisionBar(job);
    setHTML($('jobRepair'), jobRepairHtml(job));
    const stepsBox = $('jobSteps');
    if (stepsBox && window.jobStepsHtml) stepsBox.innerHTML = jobStepsHtml(job);
    renderArtifacts(job);
}

function resetJobView() {
    S.job = null;
    if ($('jobLive')) {
        const img = $('jobLive').querySelector('.job-live-img');
        if (img && window.thumbStop) thumbStop(img);
        $('jobLive').innerHTML = '';
    }
    jobLiveFor = null;
    if ($('jobHeld')) $('jobHeld').innerHTML = '';
    $('jobLog').textContent = '';
    $('jobLog').hidden = true;
    $('jobLogEmpty').innerHTML = jobLogEmptyHtml();
    $('jobArts').style.display = 'none';
    $('jobArts').innerHTML = '';
}

/* 409 здесь не ошибка интерфейса, а опоздание: пока человек читал, истёк
   HOLD_TIMEOUT или ответил кто-то другой. Говорим это прямо. */
function decideJob(id, decision) {
    return post(`/api/jobs/${id}/decide`, {decision})
        .then(() => {
            pollJobs();
            if (window.pollDeviations && S.view === 'deviations') pollDeviations();
        })
        .catch(e => toast(e.message, 'bad'));
}

function cancelJob(id) {
    /* Работающая задача отменяется не мгновенно: поток прерывается на
       ближайшей проверке отмены. Обещать «отменено» до этого нельзя — статус
       в списке ещё не тот, и человек решает, что кнопка не сработала. */
    return post(`/api/jobs/${id}/cancel`).then(() => {
        toast('останавливаю — запуск закончит текущий шаг');
        pollJobs();
        if (S.job === id) refreshJobLog();
    });
}

function cancelAll(ev) {
    const live = (S.jobs || []).filter(j => isActive(j.status)).length;
    if (!live) return toast('ничего не идёт');
    if (ev && !armConfirm(ev.currentTarget, `Остановить ${live}?`)) return;
    return post('/api/jobs/cancel_all').then(result => {
        toast(`остановлено запусков: ${result.cancelled}`);
        pollJobs();
    }).catch(e => toast(e.message, 'bad'));
}

function deleteJob(id) {
    return api('/api/jobs/' + id, {method: 'DELETE'})
        .then(() => {
            if (S.job === id) resetJobView();
            pollJobs();
        })
        .catch(e => toast(e.message, 'bad'));
}

function clearJobs() {
    return post('/api/jobs/clear')
        .then(result => {
            toast(`удалено запусков: ${result.removed}`, 'ok');
            resetJobView();
            pollJobs();
        })
        .catch(e => toast(e.message, 'bad'));
}
