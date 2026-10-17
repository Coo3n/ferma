'use strict';

/* Починка шага: человек видит экран, на котором click не нашёл цель, тычет в
   нужный элемент — и шаг сценария переписывается.

   Точка входа одна: repairOpen({mode, scenarioKey, stepIndex, dumpUrl, jobId, title}).
     mode 'fail' — экран замороженный (/api/deviations/<id>/dump), правка идёт
                   только в рецепт;
     mode 'hold' — экран живой (/api/devices/<serial>/inspect), правка идёт в
                   рецепт И задача, ждущая на шаге, повторяет его с новой целью.
   Живая сессия рекордера не нужна: файл живёт отдельно от конструктора, а
   шаг строится теми же recBuildClickStep / recCropData, что при записи.

   Чистая логика (repairPlan, repairApply, repairPatchFromStep, repairStale,
   repairParseSel, repairBuildStep) ни к DOM, ни к сети не привязана — её
   гоняет tests/test_repair_js.py. */

/* ------------------------------------------------------------------ чистая логика */

/* Во что рендерится click: ctx.click_target(...) только при texts/crop/point,
   иначе ctx.click/click_any по исходному селектору (farm/recorder/codegen.py,
   _call). Условие зеркалит его; tests/test_repair_js.py сверяет с настоящим
   render_mapped. Патч цели на лету потребляет только click_target. */
function repairRendersClickTarget(step) {
    return !!(step && ((step.texts && step.texts.length) || step.crop
        || (step.point && step.point.length)));
}

const REPAIR_NOT_TARGET = 'Запуск ждёт на шаге, где нажатие записано по описанию элемента: '
    + 'исправьте сценарий вручную или повторите шаг.';

/* Можно ли чинить шаг кликом и что в нём было. Чинятся только click. В режиме
   'hold' ещё и только тот, что рендерится в click_target: иначе задача
   повторит шаг со старым селектором, а не с новой целью. В 'fail' шаг
   заменяется целиком (у нового есть texts/point/crop), так что можно любой.
   full: true — reason уже законченная фраза, без префикса. */
function repairPlan(recipe, stepIndex, mode) {
    const steps = (recipe && recipe.steps) || [];
    if (!Number.isInteger(stepIndex) || stepIndex < 0) {
        return {ok: false, reason: 'ферма не знает, какой шаг сценария упал'};
    }
    if (stepIndex >= steps.length) {
        return {ok: false, reason: `в сценарии нет шага ${stepIndex + 1}: его могли удалить`};
    }
    const step = steps[stepIndex];
    if (!step || step.kind !== 'click' || !step.selector) {
        return {ok: false, kind: step && step.kind,
            reason: `шаг ${stepIndex + 1} — «${(step && step.kind) || '?'}», а чинятся только клики`};
    }
    if (mode === 'hold' && !repairRendersClickTarget(step)) {
        return {ok: false, kind: 'click', full: true, reason: REPAIR_NOT_TARGET};
    }
    return {ok: true, kind: 'click', old: {
        label: step.note || '',
        selector: step.selector.args || '',
        texts: (step.texts || []).slice(),
    }};
}

/* Селекторы как множество нормализованных словарей (порядок ключей и
   цепочки не важен). Не разобравшийся селектор сравнивается строкой. */
function repairSelKey(d) {
    return JSON.stringify(Object.keys(d).sort().map(k => [k, d[k]]));
}

function repairSelKeys(step) {
    return [step.selector.args].concat(step.selector.fallbacks || []).map(a => {
        const d = repairParseSel(a);
        return d ? repairSelKey(d) : 'raw:' + a;
    }).sort();
}

/* Совпадает ли шаг в рецепте с тем, что записано об отклонении. true — шаг
   сменился и молча заменять его нельзя. expected: {kind, selector?, texts?,
   sel?, selCount?}; отсутствующие поля не сравниваются. */
function repairStale(recipe, stepIndex, expected) {
    const step = ((recipe && recipe.steps) || [])[stepIndex];
    if (!step) return true;
    if (!expected) return false;
    if (expected.kind && step.kind !== expected.kind) return true;
    if (expected.selector !== undefined && expected.selector !== null) {
        if (!step.selector || step.selector.args !== expected.selector) return true;
    }
    if (Array.isArray(expected.texts)) {
        const now = step.texts || [];
        if (now.length !== expected.texts.length
            || now.some((t, i) => t !== expected.texts[i])) return true;
    }
    if (Array.isArray(expected.sel) && step.selector) {
        const now = repairSelKeys(step);
        if (now.length !== expected.sel.length
            || now.some((k, i) => k !== expected.sel[i])) return true;
    }
    if (typeof expected.selCount === 'number' && step.selector) {
        if (1 + (step.selector.fallbacks || []).length !== expected.selCount) return true;
    }
    return false;
}

/* Что ожидаем увидеть в рецепте. С miss отклонения (JSON цели) сравниваем
   тексты и сами селекторы — ловится и сдвиг индекса на другой клик. Без miss
   (слабее) сверяемся с рецептом на момент открытия: ловится только правка,
   случившаяся, пока человек смотрел на скрин, но не сдвиг до открытия. */
function repairExpected(recipe, stepIndex, miss) {
    let parsed = null;
    if (miss) {
        try { parsed = typeof miss === 'string' ? JSON.parse(miss) : miss; } catch (e) { parsed = null; }
    }
    if (parsed && typeof parsed === 'object' && Array.isArray(parsed.text)) {
        const out = {kind: 'click', texts: parsed.text.map(String)};
        const sel = Array.isArray(parsed.sel) ? parsed.sel : [];
        if (sel.length && sel.every(d => d && typeof d === 'object' && !Array.isArray(d))) {
            out.sel = sel.map(repairSelKey).sort();
        } else if (sel.length) {
            out.selCount = sel.length;
        }
        return out;
    }
    const step = ((recipe && recipe.steps) || [])[stepIndex];
    if (!step) return null;
    return {kind: step.kind, selector: step.selector ? step.selector.args : null,
        texts: (step.texts || []).slice()};
}

/* Аргументы селектора рецепта (`resourceId="x", instance=1`) в словарь для
   sel=[{...}] у click_target. Грамматику пишет farm/ui/selectors.py: только
   ключ="строка" и ключ=целое. Не разобралось целиком — null: лучше не слать
   селектор, чем слать неверный. */
function repairParseSel(args) {
    if (typeof args !== 'string' || !args.trim()) return null;
    const re = /\s*(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|-?\d+)\s*(,|$)/y;
    const out = {};
    let pos = 0;
    while (pos < args.length) {
        re.lastIndex = pos;
        const m = re.exec(args);
        if (!m) return null;
        const raw = m[2];
        out[m[1]] = raw[0] === '"' ? raw.slice(1, -1).replace(/\\(.)/g, '$1') : Number(raw);
        pos = re.lastIndex;
        if (m[3] === '' && pos < args.length) return null;
    }
    return Object.keys(out).length ? out : null;
}

/* Патч цели для POST /api/jobs/<id>/decide: то, что принимает
   farm.context.normalize_target. Без img: при той же ширине имя кропа
   переиспользуется, так что старый img бегущей задачи указывает на
   переписанный файл; резолвер идёт по sel/text/at. text: [] нужен, когда у
   нового шага текстов нет: click_target заменяет только присланные ключи, и
   без него остались бы тексты старого шага. */
function repairPatchFromStep(step) {
    const patch = {};
    const chain = [];
    if (step && step.selector) {
        [step.selector.args].concat(step.selector.fallbacks || []).forEach(args => {
            const one = repairParseSel(args);
            if (one) chain.push(one);
        });
    }
    if (chain.length) patch.sel = chain;
    const texts = ((step && step.texts) || []).filter(t => typeof t === 'string' && t);
    const at = step && step.point;
    if (Array.isArray(at) && at.length === 2 && at.every(
        c => typeof c === 'number' && isFinite(c) && c >= 0 && c <= 1)) {
        patch.at = [at[0], at[1]];
    }
    /* text: [] — только при другой непустой части: целиком пустую цель сервер
       отвергает (400 «пустая цель»), а патч без ключей вообще не шлётся */
    if (texts.length) patch.text = texts;
    else if (Object.keys(patch).length) patch.text = [];
    return patch;
}

/* Тело decide: пустой патч уходит без target (бэкенд принимает повтор без цели). */
function repairDecideBody(step) {
    const target = repairPatchFromStep(step);
    return Object.keys(target).length ? {decision: 'retry', target} : {decision: 'retry'};
}

/* Имя файла кропа для шага: как у рекордера, если оно не занято чужим шагом. */
function repairCropName(recipe, stepIndex) {
    const busy = (recipe.steps || []).map((s, i) => i === stepIndex ? null : s && s.crop);
    const base = String(stepIndex + 1).padStart(2, '0') + '_click.png';
    return busy.indexOf(base) < 0 ? base : 'repair_' + base;
}

/* Шаг для рецепта из шага, собранного recBuildClickStep. Точно так же, как это
   делает recPayload: кроме селектора/подписи/текстов/точки/кропа ничего не
   меняется. От старого шага переносятся param и pos — они про место шага в
   сценарии (параметр, позиция на «Схеме»), а не про цель клика. */
function repairBuildStep(built, oldStep, cropName) {
    const out = {
        kind: 'click',
        args: {},
        selector: Object.assign({}, built.selector, {fallbacks: recFallbacks(built)}),
        param: (oldStep && oldStep.param) || null,
        note: built.note || '',
    };
    if (built.texts && built.texts.length) out.texts = built.texts.slice();
    if (built.point) out.point = built.point.slice();
    if (cropName) out.crop = cropName;
    if (oldStep && oldStep.pos) out.pos = oldStep.pos;
    return out;
}

/* Новый рецепт с заменённым шагом; вход не трогается. cropData — base64 нового
   кропа или пусто. Кроп старого шага выкидывается из assets, если новый шаг
   на него не ссылается: /save с overwrite стирает папку ассетов и пишет заново
   только присланное, так что осиротевший файл всё равно пропал бы. */
function repairApply(recipe, stepIndex, newStep, cropData) {
    const next = JSON.parse(JSON.stringify(recipe));
    const old = next.steps[stepIndex];
    newStep = Object.assign({}, newStep);
    next.steps[stepIndex] = newStep;
    const assets = next.assets || {};
    if (old && old.crop && old.crop !== newStep.crop) delete assets[old.crop];
    if (newStep.crop && cropData) assets[newStep.crop] = cropData;
    if (newStep.crop && !assets[newStep.crop]) delete newStep.crop;
    next.assets = assets;
    return next;
}

/* Тело POST /api/recorder/save — те же ключи, что у recPayload + key/overwrite. */
function repairSaveBody(recipe, key, fallbackWidth) {
    const body = {
        key: key,
        overwrite: true,
        meta: recipe.meta || {},
        params: recipe.params || {},
        steps: recipe.steps,
    };
    if (recipe.assets && Object.keys(recipe.assets).length) {
        body.assets = recipe.assets;
        body.screen_width = recipe.screen_width || fallbackWidth || null;
    }
    return body;
}

/* ------------------------------------------------------------------ DOM */

const RP = {};   // состояние открытого сеанса починки

function repairNodes(dump) {
    /* Те же узлы, что рекордер рисует рамками; в порядке чтения — по нему
       ходит клавиатура. */
    const all = (dump && dump.nodes) || [];
    /* Как мышь (repairPointer): берём узел-цель, а не сам узел, и без дублей —
       иначе кнопка и её вложенная подпись дают два разных шага. */
    const seen = new Set();
    return all
        .filter(n => n.clickable || n.text || n.resourceId || n.description)
        .map(n => (n.target !== undefined && all[n.target]) || n)
        .filter(n => !seen.has(n) && seen.add(n))
        .sort((a, b) => (a.bounds[1] - b.bounds[1]) || (a.bounds[0] - b.bounds[0]));
}

function repairUsable(target) {
    const sel = target && (target.selectors || [])[0];
    return !!sel && sel.call === 'click' && !sel.oversized;
}

/* Сеанс: RP.state 'idle' (ещё не показан) → 'live' (модалка наша) → 'closed'.
   Закрытие ловим обёрткой над глобальным closeModal (его зовут Escape в
   core.js, клик мимо в index.html и кнопки; все берут глобал по имени), плюс
   проверкой класса on на случай, когда закрыли мимо closeModal. Закрытый
   сеанс больше ничего не рисует: модалка может уже принадлежать другому. */
let repairCloseHooked = false;

function repairHookClose() {
    if (repairCloseHooked) return;
    repairCloseHooked = true;
    const orig = window.closeModal;
    window.closeModal = function () {
        if (RP.state === 'live') RP.state = 'closed';
        RP.token = (RP.token || 0) + 1;   // грузящееся и летящее больше не наше
        return orig.apply(this, arguments);
    };
}

function repairSession() {
    if (RP.state === 'live' && !$('modal').classList.contains('on')) {
        RP.state = 'closed';
        RP.token = (RP.token || 0) + 1;
    }
    return RP.state;
}

/* false — сеанс закрыт, ничего не нарисовано. openModal() только при первом
   показе: он запоминает activeElement как место возврата фокуса, и повторный
   вызов изнутри модалки подменил бы opener скрытой кнопкой «Закрыть». Так
   modalReturn остаётся элементом, открывшим починку (если список после
   перерисовки его отсоединил — перенацеливает deviations.js, не мы). */
function repairShell(html, acts, focusId) {
    repairHookClose();
    const st = repairSession();
    if (st === 'closed') return false;
    /* Заголовок короткий: сырой текст отклонения бывает длинным, он есть в списке. */
    const n = RP.opts.stepIndex;
    $('mTitle').textContent = Number.isInteger(n) && n >= 0 ? 'Починка шага ' + (n + 1) : 'Починка шага';
    $('mBody').innerHTML = html;
    $('mActs').innerHTML = acts;
    $('modal').querySelector('.sheet').classList.add('wide');
    if (st !== 'live') {
        openModal();
        RP.state = 'live';
    }
    /* Перерисовка выбросила сфокусированный элемент — фокус упал бы на <body>,
       а ловушка Tab в core.js реагирует только на первый/последний элемент
       модалки: Tab со <body> ушёл бы на страницу под ней. */
    repairFocus(focusId);
    return true;
}

function repairFocus(id) {
    const el = id && $(id);
    if (el && typeof el.focus === 'function') el.focus();
}

function repairMessage(text, retry) {
    if (!repairShell(
        `<div class="rp-msg" role="alert"><svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>`
        + `<p>${esc(text)}</p></div>`,
        '<span class="sp"></span>'
        + (retry ? '<button class="sm" id="rpRetry">Повторить</button>' : '')
        + '<button class="primary" id="rpClose">Закрыть</button>',
        retry ? 'rpRetry' : 'rpClose')) return;
    $('rpClose').onclick = closeModal;
    if (retry) $('rpRetry').onclick = retry;
}

function repairSkeleton() {
    if (!repairShell(
        '<div class="rp-skel" aria-busy="true" aria-label="Загрузка экрана">'
        + '<div class="rp-skel-line"></div><div class="rp-skel-shot"></div></div>',
        '<span class="sp"></span><button class="sm" id="rpCancel">Отмена</button>', 'rpCancel')) return;
    $('rpCancel').onclick = closeModal;
}

async function repairOpen(opts) {
    try {
        RP.opts = opts || {};
        if (repairSession() !== 'live') RP.state = 'idle';
        const o = RP.opts;
        if (o.mode !== 'fail' && o.mode !== 'hold') {
            repairMessage('Этот шаг нельзя починить кликом: неизвестный режим починки.');
            return;
        }
        if (!o.scenarioKey || !o.dumpUrl || (o.mode === 'hold' && !o.jobId)) {
            repairMessage('Этот шаг нельзя починить кликом: не хватает данных о сценарии или экране.');
            return;
        }
        if (!Number.isInteger(o.stepIndex) || o.stepIndex < 0) {
            repairMessage('Этот шаг нельзя починить кликом: ферма не знает, '
                + 'какой шаг сценария упал.');
            return;
        }
        await repairLoad();
    } catch (e) {
        repairMessage('Не удалось открыть починку: ' + ((e && e.message) || e), null);
    }
}

async function repairLoad() {
    const o = RP.opts;
    const token = RP.token = (RP.token || 0) + 1;
    repairSkeleton();
    let recipe, dump;
    try {
        [recipe, dump] = await Promise.all([
            repairRequest('/api/recorder/recipe/' + encodeURIComponent(o.scenarioKey)),
            repairRequest(o.dumpUrl),
        ]);
    } catch (e) {
        if (token !== RP.token) return;
        /* 404: снимок или дерево вычищены (или сценарий удалён) — повтор уже не
           поможет, остаётся только закрыть. */
        repairMessage('Не удалось загрузить экран или сценарий: ' + e.message,
            e.status === 404 ? null : repairLoad);
        return;
    }
    if (token !== RP.token) return;   // закрыли или открыли заново, пока грузилось
    const plan = repairPlan(recipe, o.stepIndex, o.mode);
    if (!plan.ok) {
        repairMessage(plan.full ? plan.reason
            : 'Этот шаг нельзя починить кликом: ' + plan.reason + '.');
        return;
    }
    if (!dump || !dump.screenshot || !Array.isArray(dump.nodes)) {
        repairMessage('Снимок экрана не пришёл — нажмите «Повторить».', repairLoad);
        return;
    }
    Object.assign(RP, {recipe: recipe, dump: dump, plan: plan, built: null, hover: -1,
        busy: false, confirmed: false, expected: repairExpected(recipe, o.stepIndex, o.miss),
        list: repairNodes(dump)});
    repairPicker();
}

function repairPicker() {
    const o = RP.opts, hold = o.mode === 'hold';
    const n = o.stepIndex + 1;
    const banner = hold
        ? `Запуск ждёт на шаге ${n}. Кликните, куда нажать, — запуск продолжится.`
        : `Шаг ${n}: кликните, куда надо было нажать.`;
    const boxes = RP.list.map((node, i) => {
        const [x1, y1, x2, y2] = node.bounds;
        return `<div class="rp-box" data-i="${i}" style="left:${x1 * 100}%;top:${y1 * 100}%;`
            + `width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%"></div>`;
    }).join('');
    if (!repairShell(`
        <p class="rp-banner">${esc(banner)}</p>
        <p class="rp-hint">Tab — к экрану, стрелки — выбор, Enter — выбрать.</p>
        <div class="rp-stage" id="rpStage" tabindex="0" role="application"
             aria-label="Экран телефона. Стрелки — выбор, Enter — выбрать.">
            <img class="rp-shot" id="rpShot" alt="" draggable="false" src="${esc(RP.dump.screenshot)}">
            <div class="rp-layer" id="rpLayer">${boxes}</div>
        </div>
        <p class="rp-hover" id="rpHover" aria-live="polite"></p>
        <div class="rp-diff" id="rpDiff"></div>
        <p class="rp-status" id="rpStatus" role="status"></p>`,
        '<span class="sp"></span>'
        + '<button class="sm" id="rpCancel">Отмена</button>'
        + `<button class="primary" id="rpSave">${hold ? 'Сохранить и повторить' : 'Сохранить шаг'}</button>`, 'rpStage')) return;
    $('rpCancel').onclick = closeModal;
    $('rpSave').onclick = repairSubmit;
    const stage = $('rpStage');
    stage.addEventListener('click', ev => repairPointer(ev, true));
    stage.addEventListener('mousemove', ev => repairPointer(ev, false));
    stage.addEventListener('mouseleave', () => repairHover(-1));
    stage.addEventListener('keydown', repairKey);
    repairRefresh();
}

/* Точка события в долях экрана: снимок вписан в рамку, поэтому считаем по
   реальному прямоугольнику картинки, а не по размеру дампа. */
function repairPointer(ev, pick) {
    const rect = $('rpShot').getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = (ev.clientX - rect.left) / rect.width;
    const y = (ev.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    const hit = recHit(x, y, RP.dump);
    const node = hit ? RP.dump.nodes[hit.target] : null;
    repairHover(node ? RP.list.indexOf(node) : -1);
    if (pick) repairPick(node, [x, y]);
}

function repairHover(i) {
    RP.hover = i;
    document.querySelectorAll('#rpLayer .rp-box.hov').forEach(b => b.classList.remove('hov'));
    const box = i >= 0 && document.querySelector(`#rpLayer .rp-box[data-i="${i}"]`);
    if (box) box.classList.add('hov');
    const node = i >= 0 ? RP.list[i] : null;
    /* aria-live читает любое изменение текста: пишем, только если сменился. */
    const label = node ? recNodeLabel(node) : '';
    if ($('rpHover').textContent !== label) $('rpHover').textContent = label;
}

/* Клавиатура: Tab ставит фокус на экран, стрелки перебирают элементы в порядке
   чтения, Enter/пробел выбирают подсвеченный. Пикселя мышью здесь нет — только
   узлы дерева. */
function repairKey(ev) {
    const len = RP.list.length;
    if (!len) return;
    let i = RP.hover;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') i = (i + 1) % len;
    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') i = i < 0 ? len - 1 : (i - 1 + len) % len;
    else if (ev.key === 'Enter' || ev.key === ' ') {
        if (i >= 0) repairPick(RP.list[i], null);
        ev.preventDefault();
        return;
    } else return;
    ev.preventDefault();
    repairHover(i);
}

function repairPick(node, point) {
    if (RP.busy) return;
    if (!repairUsable(node)) {
        repairStatus(node
            ? 'Здесь нет надёжного элемента — выберите другой.'
            : 'Здесь нет элемента — выберите другой.', 'warn');
        return;
    }
    RP.built = recBuildClickStep(node, RP.dump, null);
    RP.picked = node;
    RP.confirmed = false;
    repairRefresh();
    repairStatus(RP.built.warn ? 'Внимание: ' + RP.built.warn + '.' : '', 'warn');
}

function repairStatus(text, kind) {
    const el = $('rpStatus');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'rp-status' + (kind ? ' ' + kind : '');
}

function repairSide(title, label, selector, texts) {
    return `<div class="rp-side"><h3>${esc(title)}</h3>
        <div class="rp-lbl">${label ? esc(label) : '—'}</div>
        <code class="rp-sel">${selector ? esc(selector) : '—'}</code>
        <div class="rp-txt">${texts && texts.length ? texts.map(esc).join(' · ') : ''}</div></div>`;
}

function repairRefresh() {
    const old = RP.plan.old, b = RP.built;
    $('rpDiff').innerHTML = repairSide('Было', old.label, old.selector, old.texts)
        + '<svg class="ic rp-arrow" aria-hidden="true"><use href="#i-right"/></svg>'
        + (b ? repairSide('Стало', b.note, b.selector.args, b.texts)
            : '<div class="rp-side rp-empty"><h3>Стало</h3><div class="rp-lbl">'
              + 'Кликните по элементу на экране</div></div>');
    const btn = $('rpSave');
    disableWithReason(btn, !b || RP.busy, 'сначала выберите элемент на экране');
    btn.textContent = RP.confirmed ? 'Всё равно заменить'
        : (RP.opts.mode === 'hold' ? 'Сохранить и повторить' : 'Сохранить шаг');
}

function repairBusy(on, text) {
    RP.busy = on;
    const btn = $('rpSave');
    if (!btn) return;
    disableWithReason($('rpCancel'), on, 'запрос уже отправлен — отменить его нельзя');
    if (on) {
        repairFocus('rpStage');   // уходим с кнопки до её отключения
        btn.disabled = true;
        btn.innerHTML = `<span class="rp-spin" aria-hidden="true"></span>${esc(text || 'Сохраняю…')}`;
    } else {
        repairRefresh();
        repairFocus(btn.disabled ? 'rpStage' : 'rpSave');
    }
}

/* Кроп цели с замороженного/живого скрина: тем же recCropData, что при записи.
   Нет кропа — не ошибка: остальные слои поиска работают без картинки. */
function repairCrop(built) {
    return new Promise(resolve => {
        if (!built.shot || !built.bounds) return resolve('');
        const img = new Image();
        img.onload = () => {
            const [x1, y1, x2, y2] = built.bounds;
            const sw = Math.round((x2 - x1) * img.naturalWidth);
            const sh = Math.round((y2 - y1) * img.naturalHeight);
            if (sw < REC_CROP_MIN_PX || sh < REC_CROP_MIN_PX) return resolve('');
            resolve(recCropData(img, x1 * img.naturalWidth, y1 * img.naturalHeight, sw, sh, 1));
        };
        img.onerror = () => resolve('');
        img.src = built.shot;
    });
}

/* Запрос, у которого ошибка знает статус (core.js api() его не хранит):
   у POST 4xx — сервер точно ничего не записал, всё остальное (сеть, таймаут,
   5xx) — неизвестно; у GET 404 — данных больше нет. */
async function repairRequest(path, options) {
    const res = await (options ? fetch(path, options) : fetch(path));
    const type = (res.headers && res.headers.get('content-type')) || '';
    const body = type.includes('json') ? await res.json().catch(() => ({})) : await res.text();
    if (!res.ok) {
        const err = new Error((body && body.detail) || body || ('HTTP ' + res.status));
        err.status = res.status;
        throw err;
    }
    return body;
}

function repairPost(path, data) {
    return repairRequest(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data === undefined ? {} : data)});
}

/* Отмену запроса в полёте не поддерживаем: пока идёт сохранение, «Отмена»
   выключена. Если диалог всё же закрыли (Escape, клик мимо), сохранение
   дойдёт до конца, чтобы не оставить полузаписанное, но повтор задачи в hold
   не шлём: человек закрыл диалог и результата не видел. Задача остаётся
   ждать, а тост говорит об этом. Закрывать модалку по завершении можно, только
   если сеанс всё ещё наш (alive): она могла достаться другому диалогу. */
async function repairSubmit() {
    if (RP.busy || !RP.built) return;
    const o = RP.opts, hold = o.mode === 'hold';
    /* Колбэк берём сейчас: RP.opts к концу сохранения может принадлежать уже
       другому диалогу. */
    const done = o.onDone;
    const token = RP.token;
    const alive = () => token === RP.token && RP.state === 'live';
    const finish = () => {
        const live = alive();
        if (token === RP.token) RP.busy = false;
        if (live) closeModal();
    };
    repairBusy(true, 'Сохраняю…');
    repairStatus('');
    let fresh, step, sent = false;
    try {
        /* Свежий рецепт: за время выбора его могли отредактировать. */
        fresh = await api('/api/recorder/recipe/' + encodeURIComponent(o.scenarioKey));
        if (!alive()) return;   // закрыли, пока ничего не отправлено
        const plan = repairPlan(fresh, o.stepIndex, o.mode);
        if (!plan.ok) {
            throw Object.assign(new Error(plan.reason), {plan: true, full: !!plan.full});
        }
        if (!RP.confirmed && repairStale(fresh, o.stepIndex, RP.expected)) {
            RP.confirmed = true;
            repairBusy(false);
            repairStatus('Сценарий изменился: шаг ' + (o.stepIndex + 1)
                + ' уже другой. Если это он — «Всё равно заменить».', 'warn');
            return;
        }
        const width = fresh.screen_width || RP.dump.width || null;
        /* Кроп из другого масштаба испортил бы шаблоны соседних шагов: ширина
           записи одна на рецепт. */
        const sameScale = !fresh.screen_width || !RP.dump.width
            || fresh.screen_width === RP.dump.width;
        const crop = sameScale ? await repairCrop(RP.built) : '';
        if (!alive()) return;
        const name = crop ? repairCropName(fresh, o.stepIndex) : '';
        step = repairBuildStep(RP.built, fresh.steps[o.stepIndex], name);
        const next = repairApply(fresh, o.stepIndex, step, crop);
        sent = true;
        await repairPost('/api/recorder/save', repairSaveBody(next, o.scenarioKey, width));
    } catch (e) {
        const definite = !sent || (e.status >= 400 && e.status < 500);
        /* plan.full — причина уже целое предложение («Задача ждёт на шаге…»). */
        const head = e.plan
            ? (e.full ? e.message : 'Шаг больше нельзя починить: ' + e.message)
            : 'Не удалось сохранить шаг: ' + e.message;
        const msg = head.replace(/\.$/, '') + '. ' + (definite
            ? 'Файл не изменён.'
            : 'Неизвестно, записалось ли изменение — откройте сценарий и проверьте.');
        if (alive()) {
            repairBusy(false);
            repairStatus(msg, 'bad');
        } else if (sent) {
            toast(msg, 'bad');
        }
        return;
    }

    if (hold) {
        if (!alive()) {
            toast('шаг исправлен, но запуск его не повторил: окно закрыли раньше', 'bad');
            repairDone(done);
            return;
        }
        try {
            await repairPost('/api/jobs/' + encodeURIComponent(o.jobId) + '/decide',
                repairDecideBody(step));
        } catch (e) {
            finish();
            if (/не ждёт/.test(e.message)) {
                toast('шаг исправлен в сценарии, но запуск уже не ждёт решения', 'bad');
            } else if (e.status >= 400 && e.status < 500) {
                toast('шаг исправлен в сценарии, но запуск его не повторил: ' + e.message, 'bad');
            } else {
                /* сеть/5xx: запрос мог дойти — исход неизвестен, рецепт же точно записан */
                toast('шаг исправлен; повторил ли его запуск, неизвестно — проверьте в «Запусках»', 'bad');
            }
            repairDone(done);
            return;
        }
    }
    finish();
    toast(hold ? 'шаг исправлен, запуск повторяет его' : 'шаг исправлен в сценарии', 'ok');
    repairDone(done);
}

function repairDone(done) {
    try { if (done) done(); } catch (e) { /* колбэк вызывающего */ }
    try { if (typeof loadScenarios === 'function') loadScenarios(true); } catch (e) { /* список обновится сам */ }
}

window.repairOpen = repairOpen;
