'use strict';

/* Черновик конструктора: спрашивать ли о нём сейчас.

   Раньше диалог «Восстановить?» всплывал при каждом входе в конструктор и
   «нет» ничего не запоминало — бесконечно. Теперь:
   - пустой, из одного шага или старше недели черновик тихо удаляется;
   - «Не сейчас» молчит до конца сеанса (перезагрузки страницы);
   - «Удалить» стирает совсем.
   Чистая функция: её проверяет backend/tests/test_draft_js.py. */

const DRAFT_MAX_AGE_MS = 7 * 24 * 3600 * 1000;
const DRAFT_MIN_STEPS = 2;

/* 'drop' — стереть молча, 'skip' — не спрашивать, 'ask' — показать диалог.
   Черновик без savedAt (записан до этой правки) не считаем старым. */
function draftPlan(draft, now, snoozed) {
    const steps = draft && Array.isArray(draft.steps) ? draft.steps.length : 0;
    if (steps < DRAFT_MIN_STEPS) return 'drop';
    if (draft.savedAt && now - draft.savedAt > DRAFT_MAX_AGE_MS) return 'drop';
    return snoozed ? 'skip' : 'ask';
}

/* «только что» / «5 мин назад» / «2 ч назад» / «3 дн назад». */
function draftAgo(savedAt, now) {
    if (!savedAt) return '';
    const min = Math.max(0, Math.round((now - savedAt) / 60000));
    if (min < 1) return t('draft.tolko_chto');
    if (min < 60) return t('draft.min_nazad', {n: min});
    if (min < 48 * 60) return t('draft.ch_nazad', {n: Math.round(min / 60)});
    return t('draft.dn_nazad', {n: Math.round(min / 1440)});
}
