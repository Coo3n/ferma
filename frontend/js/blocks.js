/* Блоки конструктора — рамки вокруг шагов, которые меняют ход сценария:

     ↻ Повторять 10 мин          — крутить шаги внутри (ctx.loop)
     🎲 С шансом 15%             — выполнить шаги внутри иногда (ctx.chance)
     🔎 Пока не найдёшь «…»      — крутить шаги, пока цель не появится (ctx.until_found)
     👁 Если на экране «…»       — выполнить шаги, только если цель есть / нет (ctx.seen)

   Сценарий — плоский список шагов, поэтому блок — тоже шаг (заголовок), а
   шаги внутри помнят свой блок: step.parent = id заголовка. Блоки
   вкладываются (повтор → с шансом), не глубже BLOCK_DEPTH_MAX. На сервер
   уходит span — сколько шагов за заголовком входит в блок (recPayload),
   обратно — по span (recBlocksFromSpan).

   Почему ссылка на блок, а не span в шаге: список правят руками — тащат,
   удаляют, дописывают записью. «Следующие N шагов» от каждой правки
   съезжали бы, а ссылка остаётся при шаге: вытащили шаг за рамку — вышел,
   бросили внутрь — вошёл (blockPlace). */

const BLOCK_DEPTH_MAX = 3;
const BLOCK_KINDS = {
    loop: {icon: 'repeat', defaults: () => ({times: 10, pause_min: 1, pause_max: 3, watch: true})},
    chance: {icon: 'dices', defaults: () => ({percent: 15})},
    until: {icon: 'search', defaults: () => ({tries: 20, on_fail: 'skip'})},
    if_seen: {icon: 'eye', defaults: () => ({negate: false, timeout: 3})},
    if_phone: {icon: 'phone', defaults: () => ({check: 'app_installed', negate: false})},
};
const UNTIL_ON_FAIL = ['skip', 'fail', 'ask'];
const UNTIL_FEATS = ['textContains', 'text', 'resourceId', 'descriptionContains'];

/* Поля каждой проверки «если на телефоне» — как steps.PHONE_CHECKS. */
const PHONE_CHECK_FIELDS = {
    app_installed: ['package'], app_older: ['package', 'version'], battery_below: ['percent'],
    offline: [], space_below: ['gb'], no_account: ['platform'],
};

function phoneCheckName(c) {
    return c === 'app_installed' ? t('rec.tel_c_app') : c === 'app_older' ? t('rec.tel_c_older')
        : c === 'battery_below' ? t('rec.tel_c_battery') : c === 'offline' ? t('rec.tel_c_offline')
        : c === 'space_below' ? t('rec.tel_c_space') : t('rec.tel_c_account');
}

function phoneCheckText(a) {
    const app = a.package ? recApp(a.package) : t('rec.tel_prilozhenie');
    const p = PLATFORM_NAMES[a.platform] || a.platform || '';
    switch (a.check) {
        case 'app_installed':
            return a.negate ? t('rec.tel_net_prilozheniya', {app}) : t('rec.tel_est_prilozhenie', {app});
        case 'app_older':
            return a.negate ? t('rec.tel_versiya_ne_nizhe', {app, v: a.version || '?'})
                : t('rec.tel_versiya_nizhe', {app, v: a.version || '?'});
        case 'battery_below':
            return a.negate ? t('rec.tel_zaryad_ne_menshe', {n: a.percent}) : t('rec.tel_zaryad_menshe', {n: a.percent});
        case 'offline':
            return a.negate ? t('rec.tel_est_internet') : t('rec.tel_net_interneta');
        case 'space_below':
            return a.negate ? t('rec.tel_mesta_hvataet', {n: recNum(a.gb)}) : t('rec.tel_malo_mesta', {n: recNum(a.gb)});
        default:
            return a.negate ? t('rec.tel_akkaunt_est', {p}) : t('rec.tel_net_akkaunta', {p});
    }
}

/* Ключи строк — буквально: test_strings ищет t('…') в коде. */
function untilFeatName(k) {
    return k === 'text' ? t('rec.feat_text') : k === 'resourceId' ? t('rec.feat_id')
        : k === 'descriptionContains' ? t('rec.feat_opisanie') : t('rec.feat_text_contains');
}

function untilOnFailName(v) {
    return v === 'fail' ? t('rec.on_fail_stop') : v === 'ask' ? t('rec.on_fail_ask') : t('rec.on_fail_skip');
}

function blockAddedHint(kind) {
    if (kind === 'if_seen') return t('rec.blok_dobavlen_esli');
    if (kind === 'if_phone') return t('rec.blok_dobavlen_telefon');
    return kind === 'chance' ? t('rec.blok_dobavlen_shans')
        : kind === 'until' ? t('rec.blok_dobavlen_poka') : t('rec.blok_dobavlen_povtor');
}

function blockIsHead(step) {
    return !!(step && BLOCK_KINDS[step.kind]);
}

function blockById() {
    return new Map(REC.steps.map(s => [s.id, s]));
}

/* Цепочка блоков над шагом: ближайший первым. */
function blockChain(step, byId) {
    const map = byId || blockById();
    const out = [];
    let p = step && step.parent;
    while (p != null && map.has(p) && out.length <= BLOCK_DEPTH_MAX + 1) {
        out.push(p);
        p = map.get(p).parent;
    }
    return out;
}

function blockDepth(step) {
    return blockChain(step).length;
}

/* Шаги внутри блока (на любой глубине) — подряд за заголовком. */
function blockInside(head) {
    const byId = blockById();
    const at = REC.steps.indexOf(head);
    const out = [];
    for (let i = at + 1; i < REC.steps.length && blockChain(REC.steps[i], byId).includes(head.id); i++) {
        out.push(REC.steps[i]);
    }
    return out;
}

function blockOf(step) {
    return blockIsHead(step) ? [step, ...blockInside(step)] : [step];
}

/* Порядок в списке — источник правды. Идём сверху, держим стек открытых
   блоков: шаг принадлежит блоку из стека — закрываем вложенные до него;
   нет — смотрим на следующий шаг: он внутри открытого блока — значит, этот
   шаг вставлен в середину и тоже внутри; иначе шаг вне блоков.

   Пустой блок остаётся: удалить последний шаг внутри — не значит выбросить
   рамку с её настройками (раньше она пропадала молча, а новый блок ради этого
   создавался с паузой-заготовкой). Пустую рамку не пускает только сохранение
   и запуск — blockEmptyCheck. */
function recBlocksFix() {
    REC.steps.forEach(s => {
        if ('inLoop' in s) {             // черновики до блоков: повтор помечал inLoop
            if (s.parent == null && s.inLoop) s.parent = s.inLoop;
            delete s.inLoop;
        }
    });
    {
        const byId = blockById();
        const stack = [];
        REC.steps.forEach((step, i) => {
            if (step.parent != null && stack.includes(step.parent)) {
                while (stack[stack.length - 1] !== step.parent) stack.pop();
            } else {
                const next = REC.steps[i + 1];
                const nextChain = next ? blockChain(next, byId) : [];
                let adopt = null;
                for (let k = stack.length - 1; k >= 0; k--) {
                    if (nextChain.includes(stack[k])) {
                        adopt = stack[k];
                        break;
                    }
                }
                step.parent = adopt;
                if (adopt == null) stack.length = 0;
                else while (stack[stack.length - 1] !== adopt) stack.pop();
            }
            if (blockIsHead(step)) stack.push(step.id);
        });
    }
}

/* Перед сохранением и запуском: пустой блок сервер не примет («хотя бы один
   шаг»), а человеку нужно знать, какой именно. Раскрываем его и говорим. */
function blockEmptyCheck() {
    const head = REC.steps.find(s => blockIsHead(s) && !blockInside(s).length);
    if (!head) return true;
    REC.open = head.id;
    recRender();
    toast(t('rec.blok_pustoy', {n: REC.steps.indexOf(head) + 1}), 'bad');
    return false;
}

/* Строка-подсказка внутри пустого блока: сюда пишется запись и бросаются шаги. */
function blockEmptyRow(head) {
    if (!blockIsHead(head) || blockInside(head).length) return '';
    const depth = blockDepth(head) + 1;
    return `<div class="rs rs-empty rs-depth-${depth} rs-in-${head.kind} rs-block-end"
        ondragover="event.preventDefault();this.classList.add('over-down')"
        ondragleave="this.classList.remove('over-down')"
        ondrop="recDrop(event, ${head.id})">${esc(t('rec.blok_pustoy_hint'))}
      <button class="sm ghost" onclick="recBlockRecordInto(${head.id})">${esc(t('rec.zapisat_syuda'))}</button></div>`;
}

/* «Записать сюда»: запись дописывает шаги внутрь пустого блока. */
function recBlockRecordInto(id) {
    REC.insertAfter = id;
    recRender();
    if (!REC.on && window.recStart) recStart();
}

/* Перестановка (стрелки, перетаскивание) может загнать блок с вложенными в
   ещё один блок — глубже BLOCK_DEPTH_MAX. Сервер такой сценарий не примет,
   а узнал бы человек об этом только при сохранении. Поэтому перестановку,
   после которой стало слишком глубоко, откатываем сразу и говорим почему. */
function blockSnap() {
    return REC.steps.map(s => [s, s.parent ?? null]);
}

function blockUndoIfTooDeep(snap) {
    const byId = blockById();
    const ok = REC.steps.every(s => blockChain(s, byId).length + (blockIsHead(s) ? 1 : 0) <= BLOCK_DEPTH_MAX);
    if (ok) return false;
    REC.steps = snap.map(([s, parent]) => {
        s.parent = parent;
        return s;
    });
    toast(t('rec.slishkom_gluboko', {n: BLOCK_DEPTH_MAX}), 'bad');
    return true;
}

/* Рецепт с сервера: span → ссылки на блоки. */
function recBlocksFromSpan() {
    const open = [];   // [id, индекс последнего шага блока]
    REC.steps.forEach((step, i) => {
        while (open.length && i > open[open.length - 1][1]) open.pop();
        step.parent = open.length ? open[open.length - 1][0] : null;
        if (blockIsHead(step)) {
            open.push([step.id, i + (Number(step.args.span) || 0)]);
            delete step.args.span;
        }
    });
}

/* Аргументы заголовка для сервера: span + настройки своего вида. */
function blockPayloadArgs(step) {
    const a = step.args;
    const out = {span: blockInside(step).length};
    if (step.kind === 'loop') {
        if (a.minutes != null) out.minutes = Number(a.minutes);
        else out.times = Number(a.times) || 1;
        if (a.pause_min != null && a.pause_max != null) {
            out.pause_min = Number(a.pause_min);
            out.pause_max = Math.max(Number(a.pause_min), Number(a.pause_max));
        }
        if (a.watch) out.watch = true;
    } else if (step.kind === 'chance') {
        out.percent = Math.min(100, Math.max(1, Number(a.percent) || 1));
    } else if (step.kind === 'until') {
        out.tries = Math.max(1, Math.round(Number(a.tries) || 20));
        out.on_fail = UNTIL_ON_FAIL.includes(a.on_fail) ? a.on_fail : 'skip';
    } else if (step.kind === 'if_seen') {
        out.negate = !!a.negate;
        out.timeout = Math.min(60, Math.max(0, Number(a.timeout ?? 3)));
    } else if (step.kind === 'if_phone') {
        out.check = a.check;
        out.negate = !!a.negate;
        for (const f of PHONE_CHECK_FIELDS[a.check] || []) {
            out[f] = f === 'percent' || f === 'gb' ? Number(a[f]) : String(a[f] ?? '');
        }
    }
    return out;
}

function blockLoopMeasure(a) {
    if (a.minutes != null) return t('rec.povtor_minut', {n: recNum(a.minutes)});
    return t('rec.povtor_raz', {n: a.times, slovo: declOfNum(Number(a.times), t('rec.raz_formy').split('|'))});
}

/* Цель блока в подписи — само слово в кавычках («Подписаться»), без «по
   тексту / по внутреннему имени»: заголовок читают, а не разбирают. */
function blockTargetName(args) {
    const m = String(args || '').match(/=\s*"([^"]*)"/);
    if (!m) return recFeatText(args);
    let v = m[1];
    if (/^resourceId/.test(args)) v = v.split('/').pop().replace(/_/g, ' ');
    if (/^resourceIdMatches/.test(args)) v = v.replace(/^\.\*\//, '').replace(/\$$/, '').replace(/\\(.)/g, '$1').replace(/_/g, ' ');
    return `«${v}»`;
}

function blockTarget(step) {
    const first = (step.any || [])[0];
    return first ? blockTargetName(first) : t('rec.ne_zadano_v_zagolovke');
}

function blockLabel(step) {
    if (step.kind === 'if_phone') return phoneCheckText(step.args);
    if (step.kind === 'loop') return t('rec.povtoryat', {mera: blockLoopMeasure(step.args)});
    if (step.kind === 'chance') return t('rec.s_shansom', {p: recNum(step.args.percent)});
    if (step.kind === 'if_seen') {
        return step.args.negate ? t('rec.esli_net', {chto: blockTarget(step)})
            : t('rec.esli_est', {chto: blockTarget(step)});
    }
    return t('rec.poka_ne_naydesh', {chto: blockTarget(step)});
}

/* Предпросмотр строки — зеркалит codegen (_loop / _chance / _until). */
function blockCode(step) {
    const a = blockPayloadArgs(step);
    if (step.kind === 'chance') return `if ctx.chance(${recNum(a.percent)}):`;
    if (step.kind === 'if_phone') {
        const parts = [JSON.stringify(a.check)];
        for (const f of ['package', 'version', 'platform']) if (a[f] != null) parts.push(`${f}=${JSON.stringify(a[f])}`);
        for (const f of ['percent', 'gb']) if (a[f] != null) parts.push(`${f}=${recNum(a[f])}`);
        return `if ${a.negate ? 'not ' : ''}ctx.phone_is(${parts.join(', ')}):`;
    }
    if (step.kind === 'if_seen') {
        const цель = (step.any || []).map(x => `dict(${x})`).join(', ');
        return `if ${a.negate ? 'not ' : ''}ctx.seen([${цель}], timeout=${recNum(a.timeout)}):`;
    }
    if (step.kind === 'until') {
        const цель = (step.any || []).map(x => `dict(${x})`).join(', ');
        const fail = a.on_fail !== 'skip' ? `, on_fail=${JSON.stringify(a.on_fail)}` : '';
        return `for _ in ctx.until_found([${цель}], tries=${a.tries}${fail}):`;
    }
    const parts = [a.times != null ? `times=${a.times}` : `minutes=${recNum(a.minutes)}`];
    if (a.pause_min != null) parts.push(`pause=(${recNum(a.pause_min)}, ${recNum(a.pause_max)})`);
    if (a.watch) parts.push('watch=True');
    return `for _ in ctx.loop(${parts.join(', ')}):`;
}

/* Классы строки списка: заголовок блока, глубина, вид ближайшего блока и
   «последняя строка блока» — по ним CSS рисует рамки прямо в списке. */
function blockRowClass(step) {
    const byId = blockById();
    const chain = blockChain(step, byId);
    const cls = [];
    if (chain.length) {
        cls.push(`rs-depth-${chain.length}`, `rs-in-${byId.get(chain[0]).kind}`);
        const next = REC.steps[REC.steps.indexOf(step) + 1];
        if (!next || !blockChain(next, byId).includes(chain[0])) cls.push('rs-block-end');
    }
    if (blockIsHead(step)) cls.push('rs-block', `rs-block-${step.kind}`);
    return cls.join(' ');
}

/* ---------------------------------------------------------------- редакторы */

/* Раскрытый шаг. У заголовка — настройки блока. У обычного шага — тихие
   ссылки «в блок»: возможность находится там, где о ней думают, — глядя на
   шаг, который хочется крутить или делать иногда. */
function recBlockEditor(step) {
    if (!blockIsHead(step)) return '';   // «в блок» — в меню «⋯» строки (REC_ROW_MENU)
    const body = step.kind === 'loop' ? blockLoopEditor(step)
        : step.kind === 'chance' ? blockChanceEditor(step)
        : step.kind === 'if_seen' ? blockIfSeenEditor(step)
        : step.kind === 'if_phone' ? blockIfPhoneEditor(step) : blockUntilEditor(step);
    return `<div class="blk-ed">${body}
      <div class="blk-ed-row">
        <span class="sp"></span>
        <button class="sm ghost" onclick="recBlockUnwrap(${step.id})">${esc(t('rec.ubrat_ramku'))}</button>
      </div>
    </div>`;
}

function blockLoopEditor(step) {
    const a = step.args;
    const byTime = a.minutes != null;
    return `<div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.skolko'))}</span>
        <input type="number" class="blk-ed-n" min="1" step="1" aria-label="${esc(t('rec.skolko'))}"
               value="${byTime ? recNum(a.minutes) : a.times}"
               onchange="recBlockSet(${step.id}, 'amount', this.value)">
        <div class="chips" role="group">
          <button class="chip ${byTime ? '' : 'on'}" aria-pressed="${!byTime}"
                  onclick="recBlockSet(${step.id}, 'unit', 'times')">${esc(t('rec.raz'))}</button>
          <button class="chip ${byTime ? 'on' : ''}" aria-pressed="${byTime}"
                  onclick="recBlockSet(${step.id}, 'unit', 'minutes')">${esc(t('rec.minut'))}</button>
        </div>
      </div>
      <div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.pauza_mezhdu_krugami'))}</span>
        <input type="number" min="0" step="0.5" value="${recNum(a.pause_min ?? 0)}" aria-label="${esc(t('rec.ot'))}"
               onchange="recBlockSet(${step.id}, 'pause_min', this.value)">
        <span>–</span>
        <input type="number" min="0" step="0.5" value="${recNum(a.pause_max ?? 0)}" aria-label="${esc(t('rec.do'))}"
               onchange="recBlockSet(${step.id}, 'pause_max', this.value)">
        <span class="dim">${esc(t('rec.sek_sluchayno'))}</span>
      </div>
      <label class="kb" title="${esc(t('rec.storozh_podskazka'))}">
        <input type="checkbox" ${a.watch ? 'checked' : ''} style="accent-color:var(--accent)"
               onchange="recBlockSet(${step.id}, 'watch', this.checked)">
        ${esc(t('rec.storozh'))}</label>`;
}

function blockChanceEditor(step) {
    const p = Number(step.args.percent) || 0;
    const chip = v => `<button class="chip ${p === v ? 'on' : ''}" aria-pressed="${p === v}"
        onclick="recBlockSet(${step.id}, 'percent', ${v})">${v}%</button>`;
    return `<div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.shans'))}</span>
        <input type="number" class="blk-ed-n" min="1" max="100" step="1" value="${recNum(p)}"
               aria-label="${esc(t('rec.shans'))}" onchange="recBlockSet(${step.id}, 'percent', this.value)">
        <span>%</span>
        <div class="chips" role="group">${[5, 10, 25, 50].map(chip).join('')}</div>
      </div>
      <p class="blk-ed-hint">${esc(t('rec.shans_podskazka', {p: recNum(p)}))}</p>`;
}

/* «Что ищем»: признаки цели — общие у «пока не найдёшь» и «если на экране». */
/* «Что ищем» одной строкой: найденное словами («Подписаться», «или» между
   вариантами) и кнопка «Указать на экране». Ввод текстом — запасной путь,
   спрятан под ссылкой, пока цель уже есть: три ряда кнопок на одну цель
   читались как форма из анкеты. */
function blockFeatsEditor(step, after) {
    const any = step.any || [];
    const feats = any.map((args, i) => `${i ? `<span class="dim">${esc(t('rec.ili'))}</span>` : ''}
        <span class="blk-target" title="${esc(recFeatText(args))}">${esc(blockTargetName(args))}
        <button class="feat-x" aria-label="${esc(t('rec.ubrat'))}" onclick="recUntilDrop(${step.id}, ${i})">×</button></span>`).join('');
    const picking = REC.blockPick === step.id;
    const typing = !any.length || REC.blockTyping === step.id;
    return `<div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.chto_ischem'))}</span>
        ${feats || `<span class="warn-text">${esc(t('rec.ne_zadano'))}</span>`}
        <button class="sm ${picking ? 'armed' : ''}" onclick="recBlockPickToggle(${step.id})"
                title="${esc(t('rec.ukazat_na_ekrane_podskazka'))}">${recIcon('crosshair')}${esc(picking ? t('rec.otmena') : t('rec.ukazat_na_ekrane'))}</button>
        ${after && !any.length ? `<button class="sm ghost" onclick="recUntilFromStep(${step.id}, ${after.id})"
            title="${esc(recLabel(after))}">${esc(t('rec.vzyat_iz_shaga', {n: REC.steps.indexOf(after) + 1}))}</button>` : ''}
        ${typing ? '' : `<button class="sm ghost" onclick="REC.blockTyping=${step.id};recRender()">${esc(t('rec.vvesti_tekstom'))}</button>`}
      </div>
      ${typing ? `<div class="blk-ed-row">
        <span class="blk-ed-k dim">${esc(t('rec.ili_tekstom'))}</span>
        <select id="untilKind${step.id}" aria-label="${esc(t('rec.kak_iskat'))}">${UNTIL_FEATS.map(k =>
            `<option value="${k}">${esc(untilFeatName(k))}</option>`).join('')}</select>
        <input type="text" id="untilVal${step.id}" placeholder="${esc(t('rec.naprimer_podpisatsya'))}"
               onkeydown="if(event.key==='Enter')recUntilAdd(${step.id})">
        <button class="sm ghost" onclick="recUntilAdd(${step.id})">${esc(t('rec.dobavit'))}</button>
      </div>` : ''}`;
}

/* «Указать на экране» для цели блока: следующее нажатие по зеркалу не уходит
   на телефон, а выбирает элемент — как запись клика, только получается не
   шаг, а «что ищем». Работает и без записи: экран разбирается заново. Повторное
   нажатие кнопки или Esc — отмена. */
function recBlockPickToggle(id) {
    REC.blockPick = REC.blockPick === id ? null : id;
    document.body.classList.toggle('rec-picking', REC.blockPick != null);
    if (REC.blockPick != null) toast(t('rec.nazhmite_na_ekrane_tsel'));
    recRender();
}

/* Признаки элемента для поиска: текст, подпись, id — без требования
   единственности (блоку важно «есть ли такое на экране», а не «какое из»).
   Меняющийся текст (счётчики, время) не годится: на прогоне он другой. */
function blockNodeFeatures(nodes, hit) {
    const out = [];
    for (const n of [hit, nodes[hit.target]]) {
        if (!n) continue;
        if (n.text && !n.textDynamic) out.push('text=' + JSON.stringify(n.text));
        if (n.description && !n.descriptionDynamic) out.push('description=' + JSON.stringify(n.description));
        if (n.resourceId) out.push('resourceId=' + JSON.stringify(n.resourceId));
    }
    return [...new Set(out)];
}

/* Перехват нажатия по зеркалу (screen.js, act). true — нажатие забрано. */
async function recBlockPickTap(payload) {
    if (REC.blockPick == null || !payload || payload.type !== 'tap') return false;
    const head = recFind(REC.blockPick);
    recBlockPickToggle(REC.blockPick);   // выбор одноразовый
    if (!head) return true;
    let dump = REC.dump;
    try {
        dump = await api(`/api/devices/${S.active}/inspect`);
    } catch (e) {
        if (!dump) {
            toast(t('rec.ekran_ne_razobran'), 'bad');
            return true;
        }
    }
    const hit = recHit(payload.x, payload.y, dump);
    const feats = hit ? blockNodeFeatures(dump.nodes || [], hit) : [];
    if (!feats.length) {
        toast(t('rec.element_ne_raspoznan'), 'bad');
        return true;
    }
    /* Указали на экране — это новая цель целиком, а не добавка к старой. */
    head.any = feats.slice(0, 3);
    REC.open = head.id;
    recRender();
    recSave();
    toast(t('rec.tsel_vybrana', {chto: recFeatText(feats[0])}));
    return true;
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && window.REC && REC.blockPick != null) recBlockPickToggle(REC.blockPick);
});

function blockUntilEditor(step) {
    const a = step.args;
    return `${blockFeatsEditor(step, blockNextClick(step))}
      <div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.ne_bolshe'))}</span>
        <input type="number" class="blk-ed-n" min="1" max="200" value="${a.tries ?? 20}" aria-label="${esc(t('rec.ne_bolshe'))}"
               onchange="recBlockSet(${step.id}, 'tries', this.value)">
        <span>${esc(t('rec.krugov'))}</span>
      </div>
      <div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.esli_ne_nashel'))}</span>
        <select aria-label="${esc(t('rec.esli_ne_nashel'))}" onchange="recBlockSet(${step.id}, 'on_fail', this.value)">${
            UNTIL_ON_FAIL.map(v => `<option value="${v}" ${a.on_fail === v ? 'selected' : ''}>${esc(untilOnFailName(v))}</option>`).join('')}</select>
      </div>`;
}

/* «Если на экране»: есть / нет, сколько ждать. Пара блоков «есть» + «нет»
   с одной целью — это «иначе»; кнопка ставит вторую половину сразу. */
function blockIfSeenEditor(step) {
    const a = step.args;
    const chip = (neg, text) => `<button class="chip ${!!a.negate === neg ? 'on' : ''}" aria-pressed="${!!a.negate === neg}"
        onclick="recBlockSet(${step.id}, 'negate', ${neg})">${esc(text)}</button>`;
    return `<div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.uslovie'))}</span>
        <div class="chips" role="group">${chip(false, t('rec.uslovie_est'))}${chip(true, t('rec.uslovie_net'))}</div>
      </div>
      ${blockFeatsEditor(step, blockFirstClick(step))}
      <div class="blk-ed-row">
        <span class="blk-ed-k">${esc(t('rec.zhdat'))}</span>
        <input type="number" class="blk-ed-n" min="0" max="60" step="1" value="${recNum(a.timeout ?? 3)}"
               aria-label="${esc(t('rec.zhdat'))}" onchange="recBlockSet(${step.id}, 'timeout', this.value)">
        <span>${esc(t('rec.sek'))}</span>
        <span class="sp"></span>
        <button class="sm ghost" onclick="recIfSeenElse(${step.id})"
                title="${esc(t('rec.inache_podskazka'))}">${esc(t('rec.dobavit_inache'))}</button>
      </div>
      <p class="blk-ed-hint">${esc(t('rec.esli_podskazka'))}</p>`;
}

function blockIfPhoneEditor(step) {
    const a = step.args;
    const fields = PHONE_CHECK_FIELDS[a.check] || [];
    const row = (label, html) => `<div class="blk-ed-row"><span class="blk-ed-k">${esc(label)}</span>${html}</div>`;
    const chip = neg => `<button class="chip ${!!a.negate === neg ? 'on' : ''}" aria-pressed="${!!a.negate === neg}"
        onclick="recBlockSet(${step.id}, 'negate', ${neg})">${esc(phoneCheckText(Object.assign({}, a, {negate: neg})))}</button>`;
    const pid = 'phoneApp' + step.id;
    if (fields.includes('package')) setTimeout(() => appPickFill(pid), 0);
    const checks = Object.keys(PHONE_CHECK_FIELDS).map(c =>
        `<option value="${c}" ${a.check === c ? 'selected' : ''}>${esc(phoneCheckName(c))}</option>`).join('');
    const platforms = Object.keys(PLATFORM_NAMES).map(p =>
        `<option value="${p}" ${a.platform === p ? 'selected' : ''}>${esc(PLATFORM_NAMES[p])}</option>`).join('');
    return row(t('rec.uslovie'), `<select aria-label="${esc(t('rec.uslovie'))}"
            onchange="recPhoneCheck(${step.id}, this.value)">${checks}</select>`)
        + `<div class="blk-ed-row"><div class="chips" role="group">${chip(false)}${chip(true)}</div></div>`
        + (fields.includes('package') ? row(t('rec.tel_kakoe'),
            appPickHtml(pid, a.package, (v, typing) => recBlockSet(step.id, 'package', v, typing))) : '')
        + (fields.includes('version') ? row(t('rec.tel_versiya'), `<input type="text" class="blk-ed-n" placeholder="8.40"
            aria-label="${esc(t('rec.tel_versiya'))}" value="${esc(a.version || '')}"
            onchange="recBlockSet(${step.id}, 'version', this.value.trim())">`) : '')
        + (fields.includes('percent') ? row(t('rec.tel_zaryad'), `<input type="number" class="blk-ed-n" min="1" max="99"
            aria-label="${esc(t('rec.tel_zaryad'))}" value="${a.percent ?? 20}"
            onchange="recBlockSet(${step.id}, 'percent', this.value)"><span>%</span>`) : '')
        + (fields.includes('gb') ? row(t('rec.tel_mesto'), `<input type="number" class="blk-ed-n" min="0.1" max="256" step="0.5"
            aria-label="${esc(t('rec.tel_mesto'))}" value="${a.gb ?? 1}"
            onchange="recBlockSet(${step.id}, 'gb', this.value)"><span>${esc(t('rec.tel_gb'))}</span>`) : '')
        + (fields.includes('platform') ? row(t('rec.tel_akkaunt'), `<select aria-label="${esc(t('rec.tel_akkaunt'))}"
            onchange="recBlockSet(${step.id}, 'platform', this.value)">${platforms}</select>`) : '')
        + `<div class="blk-ed-row"><span class="sp"></span>
            <button class="sm ghost" onclick="recIfSeenElse(${step.id})"
                    title="${esc(t('rec.inache_podskazka'))}">${esc(t('rec.dobavit_inache'))}</button></div>`;
}

/* Сменили проверку — поля прежней убираем, новой ставим значения по умолчанию. */
function recPhoneCheck(id, check) {
    const step = recFind(id);
    if (!step || !PHONE_CHECK_FIELDS[check]) return;
    const keep = {package: step.args.package || '', version: step.args.version || '',
        percent: step.args.percent ?? 20, gb: step.args.gb ?? 1, platform: step.args.platform || 'vk'};
    step.args = {check, negate: !!step.args.negate};
    for (const f of PHONE_CHECK_FIELDS[check]) step.args[f] = keep[f];
    recRender();
    recSave();
}

/* Первый клик внутри блока — обычно цель: «если есть „Закрыть“ — нажать». */
function blockFirstClick(head) {
    return blockInside(head).find(s => s.kind === 'click' && s.selector) || null;
}

/* «Иначе»: такой же блок с обратным условием сразу за этим. */
function recIfSeenElse(id) {
    const head = recFind(id);
    if (!head || (head.kind !== 'if_seen' && head.kind !== 'if_phone')) return;
    const at = REC.steps.indexOf(head) + blockOf(head).length;
    const other = head.kind === 'if_seen'
        ? {id: REC.nextId++, kind: 'if_seen', parent: head.parent ?? null,
            args: {negate: !head.args.negate, timeout: head.args.timeout ?? 3},
            any: [...(head.any || [])], param: null, note: '', warn: ''}
        : {id: REC.nextId++, kind: 'if_phone', parent: head.parent ?? null,
            args: Object.assign({}, head.args, {negate: !head.args.negate}),
            param: null, note: '', warn: ''};
    const pause = {id: REC.nextId++, kind: 'sleep', args: {seconds: 1}, parent: other.id,
        param: null, note: '', warn: ''};
    REC.steps.splice(at, 0, other, pause);
    REC.open = other.id;
    recRender();
    recSave();
    toast(t('rec.inache_dobavleno'));
}

/* Шаг-клик сразу за блоком «пока не найдёшь» — обычно это и есть цель:
   «листай, пока не появится „Подписаться“, потом нажми его». */
function blockNextClick(head) {
    const next = REC.steps[REC.steps.indexOf(head) + blockOf(head).length];
    return next && next.kind === 'click' && next.selector ? next : null;
}

function blockClickFeatures(step) {
    const all = [step.selector.args, ...recFallbacks(step)];
    return [...new Set(all)].slice(0, 3);
}

function recUntilFromStep(id, stepId) {
    const head = recFind(id);
    const after = recFind(stepId);
    if (!head || !after || !after.selector) return;
    head.any = blockClickFeatures(after);
    recRender();
    recSave();
}

function recUntilAdd(id) {
    const head = recFind(id);
    const kind = ($('untilKind' + id) || {}).value;
    const value = String(($('untilVal' + id) || {}).value || '').trim();
    if (!head || !value || !UNTIL_FEATS.includes(kind)) return;
    head.any = [...(head.any || []), `${kind}=${JSON.stringify(value)}`].slice(0, 3);
    REC.blockTyping = null;
    recRender();
    recSave();
}

function recUntilDrop(id, index) {
    const head = recFind(id);
    if (!head) return;
    head.any = (head.any || []).filter((_, i) => i !== index);
    recRender();
    recSave();
}

function recBlockSet(id, field, value, typing) {
    const step = recFind(id);
    if (!blockIsHead(step)) return;
    const a = step.args;
    if (field === 'unit') {
        if (value === 'minutes' && a.minutes == null) {
            a.minutes = 10;
            delete a.times;
        } else if (value === 'times' && a.times == null) {
            a.times = 10;
            delete a.minutes;
        }
    } else if (field === 'amount') {
        const n = Math.max(1, Number(value) || 1);
        if (a.minutes != null) a.minutes = n;
        else a.times = Math.round(n);
    } else if (field === 'watch') {
        a.watch = !!value;
    } else if (field === 'negate') {
        a.negate = !!value;
    } else if (field === 'timeout') {
        a.timeout = Math.min(60, Math.max(0, Number(value) || 0));
    } else if (field === 'on_fail') {
        a.on_fail = UNTIL_ON_FAIL.includes(value) ? value : 'skip';
    } else if (['package', 'version', 'platform'].includes(field)) {
        a[field] = String(value || '');
    } else if (field === 'percent' && step.kind === 'if_phone') {
        a.percent = Math.min(99, Math.max(1, Math.round(Number(value) || 1)));
    } else if (field === 'gb') {
        a.gb = Math.min(256, Math.max(0.1, Number(value) || 1));
    } else if (field === 'percent') {
        a.percent = Math.min(100, Math.max(1, Number(value) || 1));
    } else if (field === 'tries') {
        a.tries = Math.min(200, Math.max(1, Math.round(Number(value) || 1)));
    } else {
        a[field] = Math.max(0, Number(value) || 0);
        if (a.pause_min > (a.pause_max ?? 0)) a.pause_max = a.pause_min;
    }
    /* Набор текста: перерисовка убрала бы поле из-под курсора. */
    if (!typing) recRender();
    recSave();
}

/* ------------------------------------------------------------ обернуть, убрать */

/* Обернуть шаги в блок. Берётся отрезок от первого до последнего из
   выбранных; задетый блок попадает в отрезок целиком; все шаги верхнего
   уровня отрезка обязаны лежать в одном блоке — рамка не может резать
   чужую рамку пополам. */
function recBlockWrap(kind, ids) {
    const idx = ids.map(id => REC.steps.findIndex(s => s.id === id)).filter(i => i >= 0);
    if (!idx.length || !BLOCK_KINDS[kind]) return;
    let from = Math.min(...idx), to = Math.max(...idx);
    for (let i = from; i <= to; i++) {
        const s = REC.steps[i];
        if (blockIsHead(s)) to = Math.max(to, i + blockInside(s).length);
    }
    const range = REC.steps.slice(from, to + 1);
    const byId = blockById();
    const outer = range[0].parent ?? null;
    const top = range.filter(s => !range.some(o => blockChain(s, byId).includes(o.id)));
    if (top.some(s => (s.parent ?? null) !== outer)) {
        toast(t('rec.ramka_rezhet_ramku'), 'bad');
        return;
    }
    const innerDepth = Math.max(0, ...range.map(s => blockChain(s, byId).length
        - blockChain(range[0], byId).length + (blockIsHead(s) ? 1 : 0)));
    if (blockChain(range[0], byId).length + 1 + innerDepth > BLOCK_DEPTH_MAX) {
        toast(t('rec.slishkom_gluboko', {n: BLOCK_DEPTH_MAX}), 'bad');
        return;
    }
    const head = {id: REC.nextId++, kind, args: BLOCK_KINDS[kind].defaults(),
        param: null, note: '', warn: '', parent: outer};
    if (kind === 'until') {
        const after = REC.steps[to + 1];
        head.any = after && after.kind === 'click' && after.selector ? blockClickFeatures(after) : [];
    } else if (kind === 'if_seen') {
        const click = range.find(s => s.kind === 'click' && s.selector);
        head.any = click ? blockClickFeatures(click) : [];
    }
    top.forEach(s => { s.parent = head.id; });
    REC.steps.splice(from, 0, head);
    REC.open = head.id;
    if (REC.sel) REC.sel.clear();
    recRender();
    recSave();
    toast(recFirstHint('block-' + kind, blockAddedHint(kind), t('rec.blok_dobavlen')));
}

function recSelBlock(kind) {
    recBlockWrap(kind, REC.steps.filter(s => REC.sel.has(s.id)).map(s => s.id));
}

/* «Убрать рамку»: шаги остаются на месте, уровнем выше. */
function recBlockUnwrap(id) {
    const head = recFind(id);
    if (!head) return;
    REC.steps.forEach(s => { if (s.parent === id) s.parent = head.parent ?? null; });
    REC.steps = REC.steps.filter(s => s.id !== id);
    if (REC.open === id) REC.open = null;
    recRender();
    recSave();
}

/* Куда попал переставленный шаг (или блок целиком). Сразу за заголовком —
   внутри него. Между шагами одного блока — в нём. На нижней границе рамки
   решает направление: пришёл снизу (стрелкой вверх, бросили на строку
   блока) — вошёл в самый глубокий блок над ним, ушёл вниз — вышел. */
function blockPlace(step, enter) {
    const byId = blockById();
    const i = REC.steps.indexOf(step);
    const prev = REC.steps[i - 1];
    const next = REC.steps[i + blockOf(step).length];
    if (prev && blockIsHead(prev)) {
        step.parent = prev.id;
        return;
    }
    const prevC = prev ? (prev.parent ?? null) : null;
    const prevChain = prevC != null ? [prevC, ...blockChain(byId.get(prevC), byId)] : [];
    const nextP = next ? (next.parent ?? null) : null;
    if (nextP != null && prevChain.includes(nextP)) step.parent = enter ? prevC : nextP;
    else step.parent = enter ? prevC : null;
}

/* Дубль заголовка — дубль всего блока со всеми вложенными. */
const blockOrigDup = window.recDup;
window.recDup = function (id) {
    const head = recFind(id);
    if (!blockIsHead(head)) return blockOrigDup.apply(this, arguments);
    const block = blockOf(head);
    const ids = new Map();
    const copies = block.map(s => {
        const c = stCopyOf(s);
        ids.set(s.id, c.id);
        return c;
    });
    copies.forEach((c, k) => { c.parent = k === 0 ? (head.parent ?? null) : ids.get(block[k].parent); });
    const at = REC.steps.indexOf(block[block.length - 1]);
    REC.steps.splice(at + 1, 0, ...copies);
    REC.open = copies[0].id;
    recRender();
    recSave();
};

/* ------------------------------------------------------------------ схема */

const GR_BLOCK_INDENT = 26;   // каждый уровень вложенности — сдвиг вправо
const GR_BLOCK_PAD = 11;   // две соседние рамки + зазор помещаются в промежуток карточек (26px)

/* Рамки блоков на схеме: прямоугольник вокруг заголовка и шагов внутри; у
   повтора и «пока не найдёшь» — стрелка «назад, к началу круга» справа:
   блок читается как петля, а не как ещё одна карточка в столбике. */
function grBlockFrames(layout) {
    const parts = [];
    REC.steps.filter(blockIsHead).forEach(head => {
        const block = blockOf(head);
        const depth = blockDepth(head);
        const boxes = block.map(s => layout.pos.get(s.id)).filter(Boolean);
        if (!boxes.length) return;
        const pad = GR_BLOCK_PAD - depth * 4;   // вложенная рамка заметно внутри внешней, края не сливаются
        const x1 = Math.min(...boxes.map(b => b.x)) - pad;
        const y1 = Math.min(...boxes.map(b => b.y)) - pad;
        const x2 = Math.max(...boxes.map(b => b.x)) + layout.nodeW + pad;
        const y2 = Math.max(...boxes.map(b => b.y)) + GR_NODE_H + pad;
        parts.push(`<rect class="gr-block-box gr-block-${head.kind}" x="${x1}" y="${y1}"
            width="${x2 - x1}" height="${y2 - y1}" rx="12"/>`);
        if (head.kind === 'chance' || head.kind === 'if_seen' || head.kind === 'if_phone' || block.length < 2) return;   // пустому — без петли
        /* Петля «назад, к началу круга» — снаружи рамки, прямыми отрезками со
           скруглёнными углами: от последнего шага вправо, вверх по краю и к
           заголовку блока. Дуга по рамкам пересекала края вложенных блоков, и
           острие садилось на шаг внутри, а не на заголовок. Чем больше
           циклов вложено внутрь, тем дальше вправо уходит внешняя петля —
           петли не слипаются. */
        const last = layout.pos.get(block[block.length - 1].id);
        const top = layout.pos.get(head.id);
        const nested = block.slice(1).filter(s => s.kind === 'loop' || s.kind === 'until').length;
        const ax = x2 + 10 + Math.min(nested, 3) * 10;
        const y0 = last.y + GR_NODE_H / 2, yt = top.y + GR_NODE_H / 2, r = 8;
        const tx = top.x + layout.nodeW + 6;
        parts.push(`<path class="gr-block-back gr-block-${head.kind}"
            d="M${last.x + layout.nodeW},${y0} H${ax - r} Q${ax},${y0} ${ax},${y0 - r} V${yt + r} Q${ax},${yt} ${ax - r},${yt} H${tx}"
            marker-end="url(#grArrow-${head.kind})"/>`);
    });
    if (!parts.length) return '';
    const marker = kind => `<marker id="grArrow-${kind}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7"
        orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" class="gr-block-arrow gr-block-${kind}"/></marker>`;
    return `<defs>${marker('loop')}${marker('until')}</defs>${parts.join('')}`;
}
