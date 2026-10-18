'use strict';

/* «Ждёт вас» — одна очередь всего, что требует человека:

     • запуски, которые стоят и ждут решения (held) — с кадром экрана и
       кнопками решения (decisionBar из jobs.js, те же, что в «Запусках»);
     • запуски, упавшие за последние полчаса — «открыть телефон» /
       «запустить снова».

   Раньше на каждое решение уходило ~4 клика по двум вкладкам: найти пачку в
   «Запусках», раскрыть, открыть запуск, решить. Здесь — счётчик в шапке и
   всё на одном экране. Окно обновляется само, пока открыто. */

const INBOX = {open: false, timer: null, sig: '', seenFailed: new Set()};
const INBOX_FAILED_MS = 30 * 60 * 1000;

function inboxItems() {
    const jobs = S.jobs || [];
    const held = jobs.filter(j => j.status === 'held');
    const since = Date.now() / 1000 - INBOX_FAILED_MS / 1000;
    const failed = jobs.filter(j => j.status === 'failed' && (j.finished_at || 0) >= since
        && !INBOX.seenFailed.has(j.id));
    return {held, failed};
}

/* Счётчик для шапки: ждущие решения + свежие сбои, которые ещё не смотрели. */
function inboxCount() {
    const {held, failed} = inboxItems();
    return held.length + failed.length;
}

function inboxJobTitle(job) {
    return `${job.device_name || job.serial} · ${job.scenario_name || job.scenario_key}`;
}

function inboxHtml() {
    const {held, failed} = inboxItems();
    if (!held.length && !failed.length) {
        return `<p class="dim">${esc(t('inbox.pusto'))}</p>`;
    }
    const heldHtml = held.map(job => `<section class="inbox-item">
        <h4>${esc(inboxJobTitle(job))}</h4>
        ${decisionBar(job)}
      </section>`).join('');
    const failedHtml = failed.map(job => `<section class="inbox-item inbox-failed">
        <h4>${esc(inboxJobTitle(job))}</h4>
        <p>${esc(job.error || t('inbox.upal'))}</p>
        <div class="inbox-acts">
          <button class="sm" onclick="inboxOpenPhone('${esc(job.serial)}')">${esc(t('inbox.otkryt_telefon'))}</button>
          <button class="sm" onclick="inboxRerun('${esc(job.id)}')">${esc(t('inbox.zapustit_snova'))}</button>
          <button class="sm ghost" onclick="inboxSeen('${esc(job.id)}')">${esc(t('inbox.ponyatno'))}</button>
        </div>
      </section>`).join('');
    return (held.length ? `<h3 class="inbox-h">${esc(t('inbox.zhdut_resheniya', {n: held.length}))}</h3>${heldHtml}` : '')
        + (failed.length ? `<h3 class="inbox-h">${esc(t('inbox.upali', {n: failed.length}))}</h3>${failedHtml}` : '');
}

function inboxOpen() {
    INBOX.open = true;
    INBOX.sig = '';
    $('mTitle').textContent = t('inbox.title');
    $('mActs').innerHTML = `<span class="sp"></span><button onclick="closeModal()">${esc(t('inbox.zakryt'))}</button>`;
    inboxRender();
    openModal();
    clearInterval(INBOX.timer);
    INBOX.timer = setInterval(() => {
        if (!$('modal').classList.contains('on') || $('mTitle').textContent !== t('inbox.title')) {
            INBOX.open = false;
            clearInterval(INBOX.timer);
            return;
        }
        inboxRender();
    }, 1500);
}

/* Перерисовка только при изменении: кнопки решения не должны пересоздаваться
   под курсором каждые полторы секунды. */
function inboxRender() {
    const {held, failed} = inboxItems();
    const sig = held.map(j => j.id + j.held_kind + j.held_reason).join() + '|' + failed.map(j => j.id).join();
    if (sig === INBOX.sig) return;
    INBOX.sig = sig;
    $('mBody').innerHTML = `<div class="inbox">${inboxHtml()}</div>`;
}

function inboxOpenPhone(serial) {
    closeModal();
    openDevice(serial);
}

function inboxRerun(id) {
    const job = (S.jobs || []).find(j => j.id === id);
    if (!job) return;
    INBOX.seenFailed.add(id);
    closeModal();
    openRunDialog({scenario: job.scenario_key, serials: [job.serial], params: job.params});
}

function inboxSeen(id) {
    INBOX.seenFailed.add(id);
    inboxRender();
    if (window.pollStatus) pollStatus();
}
