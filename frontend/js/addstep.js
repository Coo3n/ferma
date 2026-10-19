/* «Добавить шаг» — один выбор, разложенный по тому, что человек хочет
   сделать: действие, повторять, если на экране, иногда, другое. Раньше
   блоки жили в трёх местах (выделение, раскрытый шаг, «Логика» в
   библиотеке), и найти «повторять» можно было, только зная, где искать.

   addStepPlan — чистая: по месту вставки решает, какие пункты показать и
   какие выключить (с причиной). Её проверяет backend/tests/test_addstep_js.py.

   c = {sel: сколько шагов выбрано, inLoop: место вставки внутри повтора,
        depth: глубина места вставки, depthMax, phone: открыт ли телефон}

   Выбраны шаги — пункты-блоки берут их внутрь (recSelBlock), а действия и
   «другое» не показываются: им нечего делать с выделением. */
function addStepPlan(c) {
    const wrap = (c.sel || 0) > 0;
    const deep = !wrap && (c.depth || 0) >= c.depthMax ? 'deep' : null;
    const item = (key, off) => ({key, off: off || null});
    /* Блоки — первыми: готовых действий полтора десятка, и «Повторять» /
       «Если на экране» раньше оказывались за прокруткой. */
    const groups = [];
    const repeat = [item('loop', deep), item('until', deep)];
    if (!wrap && c.inLoop) repeat.push(item('break'));
    groups.push({key: 'repeat', items: repeat});
    const seen = [item('if_seen', deep), item('if_not', deep)];
    if (!wrap) seen.push(item('anchor', c.phone ? null : 'phone'));
    groups.push({key: 'seen', items: seen});
    /* Факты о телефоне — не о экране: своя группа, иначе десять карточек
       «если…» сливаются в стену. Телефон для них не нужен — проверка идёт
       на прогоне. */
    groups.push({key: 'phone', items: ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
        'phone_offline', 'phone_space', 'phone_account'].map(k => item(k, deep))});
    groups.push({key: 'chance', items: [item('chance', deep)]});
    if (!wrap) groups.push({key: 'action', items: [item('presets')]});
    if (!wrap) groups.push({key: 'other', items: [item('call'), item('finish')]});
    return {wrap, groups};
}

/* Ключи строк — буквально: test_strings ищет t('…') в коде. */
function addStepGroupName(key) {
    return key === 'action' ? t('rec.dob_deystvie') : key === 'repeat' ? t('rec.dob_povtoryat')
        : key === 'seen' ? t('rec.dob_esli') : key === 'phone' ? t('rec.dob_telefon')
        : key === 'chance' ? t('rec.dob_inogda') : t('rec.dob_drugoe');
}

const ADD_STEP_GROUP_ICON = {action: 'plus', repeat: 'rotate', seen: 'eye', phone: 'phone', chance: 'dice', other: 'layers'};

function addStepItemText(key) {
    switch (key) {
        case 'loop': return {icon: 'rotate', title: t('rec.dob_loop'), desc: t('rec.dob_loop_d')};
        case 'until': return {icon: 'search', title: t('rec.dob_until'), desc: t('rec.dob_until_d')};
        case 'break': return {icon: 'stop', title: t('rec.vyyti_iz_povtora'), desc: t('rec.l_break_d')};
        case 'if_seen': return {icon: 'eye', title: t('rec.l_esli'), desc: t('rec.l_esli_d')};
        case 'if_not': return {icon: 'eye-off', title: t('rec.l_esli_net'), desc: t('rec.l_esli_net_d')};
        case 'anchor': return {icon: 'crosshair', title: t('device.proverka_ekrana'),
            desc: t('device.stsenariy_proverit_chto_doshel')};
        case 'chance': return {icon: 'dice', title: t('rec.dob_chance'), desc: t('rec.dob_chance_d')};
        case 'call': return {icon: 'layers', title: t('rec.l_call'), desc: t('rec.l_call_d')};
        case 'phone_app': return {icon: 'phone', title: t('rec.dob_tel_app'), desc: t('rec.dob_tel_app_d')};
        case 'phone_no_app': return {icon: 'phone', title: t('rec.dob_tel_no_app'), desc: t('rec.dob_tel_no_app_d')};
        case 'phone_older': return {icon: 'refresh', title: t('rec.dob_tel_older'), desc: t('rec.dob_tel_older_d')};
        case 'phone_battery': return {icon: 'battery', title: t('rec.dob_tel_battery'), desc: t('rec.dob_tel_battery_d')};
        case 'phone_offline': return {icon: 'wifi', title: t('rec.dob_tel_offline'), desc: t('rec.dob_tel_offline_d')};
        case 'phone_space': return {icon: 'download', title: t('rec.dob_tel_space'), desc: t('rec.dob_tel_space_d')};
        case 'phone_account': return {icon: 'shield', title: t('rec.dob_tel_account'), desc: t('rec.dob_tel_account_d')};
        default: return {icon: 'check', title: t('rec.l_finish'), desc: t('rec.l_finish_d')};
    }
}

function addStepOffText(off) {
    return off === 'phone' ? t('rec.dob_off_phone') : t('rec.dob_off_gluboko');
}

/* Значок готового действия — по первому шагу: так «Открыть приложение» и
   «Пауза» различаются глазом, не читая. */
const ADD_STEP_PRESET_ICON = {
    launch_app: 'play', stop_app: 'stop', shell: 'terminal', open_url: 'external', unlock: 'unlock',
    key: 'home', sleep: 'pause', screenshot: 'camera', swipe: 'scroll', type: 'keyboard',
};

/* compact — готовые действия: название без пояснения (оно в подсказке).
   Пятнадцать карточек с абзацем текста под каждой читались как статья. */
function addStepCard(onclick, icon, title, desc, off, compact) {
    const note = off ? addStepOffText(off) : desc;
    return `<button type="button" class="addpick-card ${compact ? 'compact' : ''}" onclick="${onclick}"${off ? ' disabled' : ''}
        title="${esc(note)}">
        <span class="addpick-ic">${recIcon(icon)}</span>
        <span class="addpick-tx"><b>${esc(title)}</b>${compact && !off ? '' : `<span>${esc(note)}</span>`}</span>
      </button>`;
}

function addStepHtml(plan, presets) {
    const head = plan.wrap
        ? `<p class="addpick-note">${esc(t('rec.dob_vybrano', {n: REC.sel.size}))}</p>` : '';
    return head + plan.groups.map(group => {
        const cards = group.items.map(it => {
            if (it.key === 'presets') {
                return (presets || []).map((preset, index) => {
                    const first = (preset.steps || [])[0];
                    const icon = (first && ADD_STEP_PRESET_ICON[first.kind]) || 'plus';
                    return addStepCard(`recLibPick(${index})`, icon, preset.title, preset.desc, null, true);
                }).join('');
            }
            const text = addStepItemText(it.key);
            return addStepCard(`recAddPick('${it.key}')`, text.icon, text.title, text.desc, it.off);
        }).join('');
        const hint = group.key === 'action' ? `<p class="addpick-hint">${esc(t('rec.dob_deystvie_d'))}</p>` : '';
        return `<section class="addpick-g">
        <h4>${recIcon(ADD_STEP_GROUP_ICON[group.key])}${esc(addStepGroupName(group.key))}</h4>${hint}
        <div class="addpick-grid">${cards}</div></section>`;
    }).join('');
}
