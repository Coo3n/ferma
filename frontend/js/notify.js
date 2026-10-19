/* «Ферма ждёт вас»: запуск встал и спрашивает человека (HELD). Простой
   телефона стоит денег, а вопрос в закрытой вкладке никто не видит, поэтому
   три сигнала разом: число в заголовке вкладки, короткий звук и системное
   уведомление браузера, если вкладка не на виду.

   Разрешение на уведомления браузер даёт только по клику человека — просим
   один раз, на первом клике по странице, и больше не пристаём. */

const NOTIFY = {held: 0, title: document.title};

function notifyHeld(held) {
    const было = NOTIFY.held;
    NOTIFY.held = held;
    document.title = held ? t('notify.zagolovok_vkladki', {n: held, title: NOTIFY.title}) : NOTIFY.title;
    if (held <= было) return;
    notifyBeep();
    if (document.hidden && window.Notification && Notification.permission === 'granted') {
        try {
            const n = new Notification(t('notify.ferma_zhdet'), {
                body: held === 1 ? t('notify.odin_zhdet') : t('notify.zhdut_resheniya', {n: held}),
                tag: 'farm-held',
                renotify: true,
            });
            n.onclick = () => {
                window.focus();
                showView('deviations');
                n.close();
            };
        } catch (e) {
            /* уведомления недоступны (файл открыт не с сервера) — хватит звука */
        }
    }
}

/* Разряд/перегрев: один сигнал на переход состояния телефона (power.py),
   а не на каждый опрос. Первый опрос только запоминает — без шквала при загрузке. */
const POWER_SEEN = {};

function notifyPower(devices) {
    const first = !Object.keys(POWER_SEEN).length;
    (devices || []).forEach(d => {
        const st = d.online && d.power ? d.power.state : 'ok';
        const was = POWER_SEEN[d.serial];
        POWER_SEEN[d.serial] = st;
        if (first || was === undefined || was === st) return;
        const vars = {name: d.name, n: d.power.level, reason: d.rest || d.power.rest_reason};
        let text = '';
        if (st === 'rest') text = t('power.t_rest', vars);
        else if (st === 'critical') text = t('power.t_critical', vars);
        else if (st === 'low' && was === 'ok') text = t('power.t_low', vars);
        else if (st === 'ok' && was === 'rest') text = t('power.t_back', vars);
        if (!text) return;
        toast(text, st === 'ok' ? 'ok' : 'bad');
        if (st === 'ok' || st === 'low') return;
        notifyBeep();
        if (document.hidden && window.Notification && Notification.permission === 'granted') {
            try { new Notification(t('notify.ferma_zhdet'), {body: text, tag: 'farm-power-' + d.serial}); } catch (e) { /* только звук */ }
        }
    });
}

/* Два коротких тона без файла: ферма работает без интернета, а лишний
   ассет ради одного писка не нужен. */
function notifyBeep() {
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        NOTIFY.audio = NOTIFY.audio || new Ctx();
        const ac = NOTIFY.audio;
        [0, 0.18].forEach((at, i) => {
            const osc = ac.createOscillator();
            const gain = ac.createGain();
            osc.frequency.value = i ? 880 : 660;
            gain.gain.setValueAtTime(0.0001, ac.currentTime + at);
            gain.gain.exponentialRampToValueAtTime(0.15, ac.currentTime + at + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + at + 0.16);
            osc.connect(gain).connect(ac.destination);
            osc.start(ac.currentTime + at);
            osc.stop(ac.currentTime + at + 0.17);
        });
    } catch (e) {
        /* звук не обязателен */
    }
}

document.addEventListener('click', () => {
    /* Звук в браузере тоже разрешается только после клика — будим его здесь. */
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx && !NOTIFY.audio) NOTIFY.audio = new Ctx();
        if (NOTIFY.audio && NOTIFY.audio.state === 'suspended') NOTIFY.audio.resume();
    } catch (e) { /* без звука */ }
    if (window.Notification && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
    }
}, {once: true, capture: true});
