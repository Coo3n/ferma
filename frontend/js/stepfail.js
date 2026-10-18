/* «Если не нашёл» — одна настройка шага вместо пары «необязательный» +
   «повторов». Хранится в тех же полях, что читает codegen._flexible:
   retries — сколько раз повторить сверх первой попытки, optional — после
   последней неудачи идти дальше, а не останавливать запуск. Человек же
   думает попытками («пробовать 3 раза»), поэтому tries = retries + 1. */

const ST_FAIL_TRIES = [1, 2, 3, 4, 6];
const ST_FAIL_RETRIES_MAX = 5;   // = потолок retries в steps.py

function stFailGet(step) {
    return {tries: (Number(step.retries) || 0) + 1, skip: !!step.optional};
}

function stFailSet(step, value) {
    if ('tries' in value) {
        const retries = Math.max(0, Math.min(ST_FAIL_RETRIES_MAX, (Number(value.tries) || 1) - 1));
        if (retries) step.retries = retries;
        else delete step.retries;
    }
    if ('skip' in value) {
        if (value.skip) step.optional = true;
        else delete step.optional;
    }
}
