/* Варианты текста: «{привет|здравствуй}» → одно из.

   Порт backend/farm/phrases.py, один в один, включая оба случая, когда
   скобка остаётся обычным текстом: незакрытая и «{одно}» без «|». Иначе
   конструктор обещал бы человеку одно, а телефон отправлял другое —
   backend/tests/test_phrases_js.py сверяет обе реализации на одних входах.

   Выбор варианта живёт на прогоне, не здесь: здесь он нужен только чтобы
   показать пример и посчитать, сколько их. */

const PHR_MAX_DEPTH = 4;
const PHR_COUNT_MAX = 100000;
const PHR_SPECIAL = '{}|\\';

function phrParseSeq(text, i, depth, inner) {
    const parts = [];
    let buf = '';
    while (i < text.length) {
        const ch = text[i];
        if (ch === '\\' && i + 1 < text.length && PHR_SPECIAL.includes(text[i + 1])) {
            buf += text[i + 1];
            i += 2;
            continue;
        }
        if (inner && (ch === '|' || ch === '}')) break;
        if (ch === '{' && depth < PHR_MAX_DEPTH) {
            const got = phrParseGroup(text, i, depth);
            if (got.alts) {
                if (buf) { parts.push(buf); buf = ''; }
                parts.push(got.alts);
                i = got.i;
                continue;
            }
        }
        buf += ch;
        i += 1;
    }
    if (buf) parts.push(buf);
    return {parts, i};
}

function phrParseGroup(text, i, depth) {
    const alts = [];
    let j = i + 1;
    for (;;) {
        const got = phrParseSeq(text, j, depth + 1, true);
        alts.push(got.parts);
        j = got.i;
        if (j >= text.length) return {alts: null, i};
        if (text[j] === '|') { j += 1; continue; }
        j += 1;
        break;
    }
    return alts.length < 2 ? {alts: null, i} : {alts, i: j};
}

function phrParse(text) {
    return phrParseSeq(String(text == null ? '' : text), 0, 0, false).parts;
}

function phrCountOf(parts) {
    let total = 1;
    for (const part of parts) {
        if (typeof part === 'string') continue;
        total *= part.reduce((sum, alt) => sum + phrCountOf(alt), 0);
        if (total >= PHR_COUNT_MAX) return PHR_COUNT_MAX;
    }
    return total;
}

/* Сколько разных текстов может получиться. 1 — вариантов нет. */
function phrCount(text) {
    return phrCountOf(phrParse(text));
}

function phrBuild(parts) {
    return parts.map(part => typeof part === 'string' ? part
        : phrBuild(part[Math.floor(Math.random() * part.length)])).join('');
}

/* Пример того, что уйдёт на телефон. Вариантов нет — текст как есть. */
function phrPick(text) {
    text = String(text == null ? '' : text);
    const parts = phrParse(text);
    return parts.some(p => typeof p !== 'string') ? phrBuild(parts) : text;
}
