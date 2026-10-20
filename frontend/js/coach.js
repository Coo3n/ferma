'use strict';

/* Подсказки по экрану: экран темнеет, нужная часть подсвечена, рядом —
   карточка «что это и зачем». Сами появляются при первом открытии каждого
   экрана за сессию (ферма, пульт, конструктор, запуски, окно запуска…).
   «?» в шапке показывает тур текущего экрана заново.

   Шаг, чьего элемента сейчас нет на экране (нет выбранных телефонов, пустой
   список), молча пропускается — подсвечивать пустоту хуже, чем промолчать.
   Тексты — литералами t('…') внутри функций: так их видит тест строк. */

const COACH_SEEN_KEY = 'farm.coach.seen';   // localStorage: экраны, где тур уже был — навсегда
const COACH_AUTO_KEY = 'farm.coach.auto';   // sessionStorage: сам тур за сессию уже показан
const COACH_OFF_KEY = 'farm.onb.off';       // общий с onboarding.js «больше не показывать»
const COACH = {key: '', steps: [], i: 0, opener: null, raf: 0, lastScreen: ''};

const COACH_TOURS = {
    fleet: () => [
        {sel: '#fleetStats', title: t('coach.fleet_kpi_t'), text: t('coach.fleet_kpi')},
        {sel: '#devSearch', title: t('coach.fleet_search_t'), text: t('coach.fleet_search')},
        {sel: '#fleet .tile', title: t('coach.fleet_tile_t'), text: t('coach.fleet_tile')},
        {sel: '#selAllLabel', up: 'button', title: t('coach.fleet_select_t'), text: t('coach.fleet_select')},
        {sel: '#runbar', title: t('coach.fleet_bar_t'), text: t('coach.fleet_bar')},
    ],
    pult: () => [
        {sel: '#mirror .stage', title: t('coach.pult_screen_t'), text: t('coach.pult_screen')},
        {sel: '.pult-keys', title: t('coach.pult_keys_t'), text: t('coach.pult_keys')},
        {sel: '#pultApps', title: t('coach.pult_apps_t'), text: t('coach.pult_apps')},
        {sel: '#pult #padText', title: t('coach.pult_text_t'), text: t('coach.pult_text')},
        {sel: '.pult-files', title: t('coach.pult_files_t'), text: t('coach.pult_files')},
        {sel: '#btnRecBegin', title: t('coach.pult_rec_t'), text: t('coach.pult_rec')},
    ],
    builder: () => [
        {sel: '#btnRecStart', title: t('coach.build_rec_t'), text: t('coach.build_rec')},
        {sel: ['#recSteps', '#recScheme'], title: t('coach.build_steps_t'), text: t('coach.build_steps')},
        {sel: '#recSteps .rs', title: t('coach.build_one_t'), text: t('coach.build_one')},
        {sel: 'button[onclick="recLibOpen()"]', title: t('coach.build_add_t'), text: t('coach.build_add')},
        {sel: '#btnRecRun', title: t('coach.build_check_t'), text: t('coach.build_check')},
        {sel: '#btnRecSave', title: t('coach.build_save_t'), text: t('coach.build_save')},
    ],
    scen: () => [
        {sel: '#scList', title: t('coach.scen_list_t'), text: t('coach.scen_list')},
        {sel: '#btnScenRecord', title: t('coach.scen_new_t'), text: t('coach.scen_new')},
        {sel: '#scSteps', title: t('coach.scen_steps_t'), text: t('coach.scen_steps')},
    ],
    jobs: () => [
        {sel: '#view-jobs .runs-seg', title: t('coach.jobs_tabs_t'), text: t('coach.jobs_tabs')},
        {sel: '#jobList .rgroup', title: t('coach.jobs_group_t'), text: t('coach.jobs_group')},
        {sel: '#jobList', part: true, title: t('coach.jobs_list_t'), text: t('coach.jobs_list')},
        {sel: '#btnCancelAll', title: t('coach.jobs_stop_t'), text: t('coach.jobs_stop')},
    ],
    deviations: () => [
        {sel: '#dvnKinds', title: t('coach.dvn_kinds_t'), text: t('coach.dvn_kinds')},
        {sel: '#dvnList', title: t('coach.dvn_list_t'), text: t('coach.dvn_list')},
    ],
    accounts: () => [
        {sel: 'button[onclick="accAdd()"]', title: t('coach.acc_add_t'), text: t('coach.acc_add')},
        {sel: 'button[onclick="accImport()"]', title: t('coach.acc_import_t'), text: t('coach.acc_import')},
        {sel: '#btnAccAutobind', title: t('coach.acc_bind_t'), text: t('coach.acc_bind')},
        {sel: '#accList', part: true, title: t('coach.acc_list_t'), text: t('coach.acc_list')},
    ],
    run: () => [
        {sel: '#rdScen', title: t('coach.run_scen_t'), text: t('coach.run_scen')},
        {sel: '#rdWho', title: t('coach.run_who_t'), text: t('coach.run_who')},
        {sel: '#rdTrialRow', title: t('coach.run_trial_t'), text: t('coach.run_trial')},
        {sel: '#rdCheck', title: t('coach.run_check_t'), text: t('coach.run_check')},
        {sel: '#rdGo', title: t('coach.run_go_t'), text: t('coach.run_go')},
    ],
};

/* Какие экраны уже показывали — помним навсегда: одно и то же дважды
   человеку не надо, «?» всегда покажет снова. */
function coachSession(value) {
    if (value === undefined) {
        const seen = window.store ? store.get(COACH_SEEN_KEY, []) : [];
        return Array.isArray(seen) ? seen : [];
    }
    if (window.store) store.set(COACH_SEEN_KEY, value);
}

/* Сам тур — не чаще одного за сессию, и не после приветствия: иначе подряд
   идут два «знакомства». Остальные ждут своего часа по «?». */
function coachAutoUsed(mark) {
    try {
        if (mark) sessionStorage.setItem(COACH_AUTO_KEY, '1');
        return !!sessionStorage.getItem(COACH_AUTO_KEY);
    } catch (e) {
        return false;
    }
}

function coachOff() {
    return !!(window.store && store.get(COACH_OFF_KEY, false));
}

/* Какой экран сейчас перед человеком — ключ тура или ''. */
function coachScreen(force) {
    const modal = $('modal');
    if (modal && modal.classList.contains('on')) return $('rdGo') ? 'run' : '';
    if (S.view === 'device') {
        if (!window.REC) return '';
        if (REC.on && !force) return '';   // идёт запись шагов — сами не мешаем, по «?» покажем
        return window.pultOn && pultOn() ? 'pult' : 'builder';
    }
    return COACH_TOURS[S.view] ? S.view : '';
}

function coachVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 16) return false;   // точка-пустышка не в счёт
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    /* Тихие кнопки строки прозрачны до наведения — подсвечивать пустоту нельзя. */
    for (let n = el; n && n !== document.body; n = n.parentElement) {
        if (parseFloat(getComputedStyle(n).opacity) < .3) return false;
    }
    return true;
}

function coachFind(step) {
    const sels = Array.isArray(step.sel) ? step.sel : [step.sel];
    for (const sel of sels) {
        let el = document.querySelector(sel);
        if (el && step.up) el = el.closest(step.up) || el;
        if (coachVisible(el)) return el;
    }
    return null;
}

function coachStart(key, manual, auto) {
    const make = COACH_TOURS[key];
    if (!make || COACH.key) return false;
    const steps = make().filter(step => coachFind(step));
    if (!steps.length) return false;
    const seen = coachSession();
    if (!seen.includes(key)) coachSession([...seen, key]);
    if (auto) coachAutoUsed(true);
    COACH.key = key;
    COACH.steps = steps;
    COACH.i = 0;
    COACH.manual = !!manual;
    COACH.opener = document.activeElement;
    const root = document.createElement('div');
    root.className = 'coach';
    root.id = 'coach';
    root.innerHTML = `<div class="coach-hole" aria-hidden="true"></div>
      <div class="coach-card" role="dialog" aria-modal="true" aria-labelledby="coachTitle"
           aria-describedby="coachText" tabindex="-1">
        <div class="coach-top"><span class="coach-n" id="coachN"></span>${manual
            ? `<button class="coach-link" onclick="coachToWelcome()">${esc(t('coach.vse_o_ferme'))}</button>` : ''}</div>
        <h3 id="coachTitle"></h3>
        <p id="coachText"></p>
        <div class="coach-acts">
          <button class="sm ghost" onclick="coachClose()">${esc(t('coach.propustit'))}</button>
          <span class="sp"></span>
          <button class="sm" id="coachBack" onclick="coachGo(-1)">${esc(t('coach.nazad'))}</button>
          <button class="sm primary" id="coachNext" onclick="coachGo(1)"></button>
        </div>
      </div>`;
    document.body.appendChild(root);
    requestAnimationFrame(() => root.classList.add('on'));
    coachShow();
    return true;
}

function coachShow() {
    const step = COACH.steps[COACH.i];
    const el = step && coachFind(step);
    if (!el) {
        /* Элемент пропал (список перерисовали) — к следующему, а не в пустоту. */
        if (COACH.i < COACH.steps.length - 1) { COACH.i++; return coachShow(); }
        return coachClose();
    }
    COACH.el = el;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: reduce ? 'auto' : 'smooth'});
    const last = COACH.i === COACH.steps.length - 1;
    setText($('coachN'), t('coach.schet', {n: COACH.i + 1, total: COACH.steps.length}));
    setText($('coachTitle'), step.title);
    setText($('coachText'), step.text);
    $('coachBack').hidden = COACH.i === 0;
    setText($('coachNext'), last ? t('coach.ponyatno') : t('coach.dalee'));
    coachPlace();
    setTimeout(coachPlace, reduce ? 0 : 320);   // после плавной прокрутки
    $('coachNext').focus({preventScroll: true});
}

const COACH_PAD = 6, COACH_GAP = 14, COACH_EDGE = 12;

/* Вырез вокруг элемента и карточка рядом: снизу, если влезает, иначе
   сверху, иначе сбоку; всегда в пределах окна. */
function coachPlace() {
    const root = $('coach');
    if (!root || !COACH.el) return;
    if (!COACH.el.isConnected || !coachVisible(COACH.el)) {
        /* Список перерисовали или элемент исчез — ищем заново, иначе рамка висит в пустоте. */
        const again = coachFind(COACH.steps[COACH.i]);
        if (!again) return coachGo(1);
        COACH.el = again;
    }
    const r = COACH.el.getBoundingClientRect();
    const vw = innerWidth, vh = innerHeight;
    const hole = root.querySelector('.coach-hole');
    const x = Math.max(COACH_EDGE / 2, r.left - COACH_PAD), y = Math.max(COACH_EDGE / 2, r.top - COACH_PAD);
    const w = Math.min(vw - x - COACH_EDGE / 2, r.right + COACH_PAD - x);
    let h = Math.min(vh - y - COACH_EDGE / 2, r.bottom + COACH_PAD - y);
    /* Список на весь экран: рамка — только на верх (первые строки), иначе
       карточка ляжет поверх подсвеченного и читать нечего. */
    if (COACH.steps[COACH.i].part && r.height > vh * .5) h = Math.min(h, Math.round(vh * .4));
    Object.assign(hole.style, {left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px'});

    const card = root.querySelector('.coach-card');
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let side, left, top;
    if (y + h + COACH_GAP + ch <= vh - COACH_EDGE) {
        side = 'below'; top = y + h + COACH_GAP;
    } else if (y - COACH_GAP - ch >= COACH_EDGE) {
        side = 'above'; top = y - COACH_GAP - ch;
    } else if (x + w + COACH_GAP + cw <= vw - COACH_EDGE) {
        side = 'right'; left = x + w + COACH_GAP;
    } else if (x - COACH_GAP - cw >= COACH_EDGE) {
        side = 'left'; left = x - COACH_GAP - cw;
    } else {
        side = 'inside'; top = vh - ch - COACH_EDGE * 2;   // элемент на весь экран
    }
    if (side === 'below' || side === 'above' || side === 'inside') {
        left = r.left + r.width / 2 - cw / 2;
    } else {
        top = r.top + r.height / 2 - ch / 2;
    }
    left = Math.max(COACH_EDGE, Math.min(vw - cw - COACH_EDGE, left));
    top = Math.max(COACH_EDGE, Math.min(vh - ch - COACH_EDGE, top));
    card.dataset.side = side;
    card.style.left = left + 'px';
    card.style.top = top + 'px';
    /* Стрелка смотрит на середину элемента, даже если карточку прижало к краю. */
    const ax = Math.max(18, Math.min(cw - 18, r.left + r.width / 2 - left));
    const ay = Math.max(18, Math.min(ch - 18, r.top + r.height / 2 - top));
    card.style.setProperty('--ax', ax + 'px');
    card.style.setProperty('--ay', ay + 'px');
}

function coachGo(dir) {
    const next = COACH.i + dir;
    if (next < 0) return;
    if (next >= COACH.steps.length) return coachClose();
    COACH.i = next;
    coachShow();
}

function coachClose() {
    const root = $('coach');
    if (root) root.remove();
    COACH.key = '';
    COACH.el = null;
    COACH.steps = [];
    if (COACH.opener && COACH.opener.focus && COACH.opener.isConnected) COACH.opener.focus({preventScroll: true});
    COACH.opener = null;
}

/* «?» в шапке: тур текущего экрана; где своего нет — общий тур. */
function coachHelp() {
    if (COACH.key) coachClose();
    if (!coachStart(coachScreen(true), true) && window.onbOpen) onbOpen();
}

/* Из карточки тура — к общему знакомству со всей фермой. */
function coachToWelcome() {
    coachClose();
    if (window.onbOpen) onbOpen();
}

function coachReflow() {
    if (!COACH.key) return;
    cancelAnimationFrame(COACH.raf);
    COACH.raf = requestAnimationFrame(coachPlace);
}

window.addEventListener('resize', coachReflow);
document.addEventListener('scroll', coachReflow, true);

/* Пока идёт тур, клавиатура — его: стрелки, Esc, Tab по кнопкам карточки.
   Ловим в capture, чтобы горячие клавиши приложения не сработали под ним. */
document.addEventListener('keydown', ev => {
    if (!COACH.key) return;
    const card = document.querySelector('.coach-card');
    if (ev.key === 'Tab') {
        const items = [...card.querySelectorAll('button:not([hidden])')];
        const i = items.indexOf(document.activeElement);
        ev.preventDefault();
        items[(i + (ev.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    } else if (ev.key === 'Escape') {
        coachClose();
    } else if (ev.key === 'ArrowRight') {
        coachGo(1);
    } else if (ev.key === 'ArrowLeft') {
        coachGo(-1);
    } else if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.tagName === 'BUTTON') {
        return;   // нативное нажатие кнопки карточки
    }
    ev.stopImmediatePropagation();
    if (ev.key !== 'Tab') ev.preventDefault();
}, true);

/* Показ сам собой: четыре раза в секунду смотрим, какой экран перед человеком.
   Сменился и тура тут ещё не было — ждём, пока экран дорисуется, и
   показываем. Дёшево: ни одного запроса, только чтение DOM. */
setInterval(() => {
    if (COACH.key) return coachReflow();   // рамка следует за элементом, если экран двигается сам
    if (document.hidden || coachOff() || coachAutoUsed()) return;
    if ($('onb')) return;   // идёт общий тур
    const key = coachScreen();
    if (key !== COACH.lastScreen) {
        COACH.lastScreen = key;
        COACH.since = Date.now();
        return;
    }
    if (!key || Date.now() - COACH.since < 350) return;
    if (coachSession().includes(key)) return;
    coachStart(key, false, true);
}, 250);
