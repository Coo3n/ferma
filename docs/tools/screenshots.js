/* Скриншоты для документации (docs/images/*.png) на подставных данных.

   Телефоны не нужны: ответы API подменяются здесь же — 40 телефонов в
   разных состояниях, запуски, проблемы, аккаунты, расписание. Экраны
   телефонов — нейтральные картинки из docs/images/screens.

   Запуск (сервер фермы должен работать на :8777):
       npm i -D playwright            # один раз, в любой папке
       node docs/tools/screenshots.js [путь-к-playwright]
*/
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.argv[2] || 'playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'images');
const SCREENS = path.join(OUT, 'screens');
const BASE = process.env.BASE || 'http://127.0.0.1:8777/';

function fakeData() {
  const now = Date.now() / 1000;
  const groups = ['VK-10', 'VK-10', 'Inst', 'TikTok', ''];
  const devs = Array.from({ length: 40 }, (_, i) => {
    const off = i === 7 || i === 23;
    const unauth = i === 31;
    return {
      serial: 'R58N' + (1000 + i), state: unauth ? 'unauthorized' : off ? 'offline' : 'device',
      label: 'Phone ' + (i + 1), name: 'Phone ' + (i + 1), group: groups[i % 5],
      tags: i % 6 === 0 ? ['прогрет'] : i % 9 === 0 ? ['новый'] : [],
      model: 'Galaxy A' + (10 + i % 5), brand: 'samsung', android: '13', sdk: '33', width: 1080, height: 2400,
      battery: off ? null : (i === 12 ? 9 : 35 + (i * 7) % 60), temperature: off ? null : (i === 18 ? 44 : 30 + i % 6),
      charging: i % 4 === 0 ? 'usb' : '', busy_job: (i % 3 === 0 && !off && !unauth) ? 'j' + i : null,
      enabled: true, last_seen: now, first_seen: 0, error: '', online: !off && !unauth,
      available: !off && i % 3 !== 0, u2: true, network: i > 35, transport: i > 35 ? 'tcp' : 'usb',
      warnings: i === 12 ? ['заряд 9%'] : i === 18 ? ['перегрев 44°C'] : unauth ? ['нет доступа'] : [],
      accounts: i % 5 === 1 ? [{ platform: 'vk', status: i === 11 ? 'banned' : i === 16 ? 'login' : 'ok' }] : [],
    };
  });
  const jobs = [];
  devs.forEach((d, i) => {
    if (!d.busy_job) return;
    jobs.push({ id: d.busy_job, scenario_key: 'warmup_vk', scenario_name: 'Прогрев VK', serial: d.serial,
      device_name: d.name, status: i === 3 ? 'held' : 'running', held_kind: i === 3 ? 'lost' : '',
      held_obstacle: i === 3 ? 'obstacle_lost_01.json' : '',
      held_reason: i === 3 ? 'экран не меняется, хотя листаю: [Оцените приложение, Позже]' : '',
      held_at: now - 40, created_at: now - 600, started_at: now - 590, duration: 590, artifacts: [],
      params: {}, batch: 'b1', step_index: 1, step_total: 2, step_label: 'Листать ленту' });
  });
  for (let i = 0; i < 12; i++) {
    jobs.push({ id: 'old' + i, scenario_key: 'warmup_inst', scenario_name: 'Прогрев Instagram',
      serial: devs[i].serial, device_name: devs[i].name, status: i % 5 === 0 ? 'failed' : 'passed',
      error: i % 5 === 0 ? 'StepFailed: сбился с пути: впереди com.android.launcher' : '',
      created_at: now - 7200 - i * 60, finished_at: now - 7000, duration: 610, artifacts: [], params: {}, batch: 'b0' });
  }
  const deviations = [
    { id: 'd1', kind: 'hold', title: 'запуск ждёт решения: экран не меняется, хотя листаю: [Оцените приложение, Позже]',
      detail: '«Прогрев VK» на Phone 4 сбился с пути и ждёт. Покажите, как быть на этом экране, — ферма запомнит и продолжит.',
      job_id: 'j3', scenario_key: 'warmup_vk', scenario_name: 'Прогрев VK', obstacle_file: 'obstacle_lost_01.json',
      shot: 'hold_1.jpg', step_index: -1, at: now - 40, last_at: now - 40, hits: 1, seen: false, devices: ['Phone 4'] },
    { id: 'd2', kind: 'lost', title: 'сбился с пути: Включить уведомления, Не сейчас',
      detail: 'Приложение показало окно, которого сценарий не ждал. Покажите, как быть, — дальше ферма справится сама.',
      job_id: 'old1', scenario_key: 'warmup_inst', scenario_name: 'Прогрев Instagram', obstacle_file: 'obstacle_lost_01.json',
      shot: '', step_index: -1, at: now - 5000, last_at: now - 4000, hits: 6, seen: false, devices: ['Phone 2', 'Phone 6', 'Phone 9'] },
    { id: 'd3', kind: 'escape', title: 'незнакомый экран обошли вслепую: Оцените нас, Позже',
      detail: 'Сценарий доехал, но выход подобран перебором.', job_id: 'old2', scenario_key: 'warmup_inst',
      scenario_name: 'Прогрев Instagram', obstacle_file: 'obstacle_escaped_01.json', shot: '', step_index: -1,
      at: now - 9000, last_at: now - 8000, hits: 3, seen: true, devices: ['Phone 3'] },
  ];
  const accounts = Array.from({ length: 16 }, (_, i) => ({ platform: ['vk', 'inst', 'tiktok', 'tg'][i % 4],
    login: `user${i + 1}@mail.example`, phone: '', proxy: i % 3 === 0 ? `10.0.${i}.10:8080` : '', note: '',
    serial: i < 8 ? devs[i * 5 + 1].serial : '', status: i === 2 ? 'banned' : i === 5 ? 'login' : i < 8 ? 'ok' : 'new',
    id: 'acc' + i, updated: now, has_password: true }));
  const schedules = [
    { id: 's1', name: 'Утренний прогрев VK', scenario: 'warmup_vk', params: {}, target: { kind: 'group', value: 'VK-10' },
      days: [0, 1, 2, 3, 4], window: { from: '09:00', to: '12:00' }, runs_per_day: 2, enabled: true,
      scenario_name: 'Прогрев VK', scenario_missing: false, next_at: now + 3600 },
    { id: 's2', name: 'Вечер TikTok', scenario: 'warmup_tiktok', params: {}, target: { kind: 'all', value: null },
      days: [5, 6], window: { from: '19:00', to: '22:00' }, runs_per_day: 1, enabled: false,
      scenario_name: 'Прогрев TikTok', scenario_missing: false, next_at: null }];
  const preflight = serials => ({ counts: { ready: serials.length }, devices: Object.fromEntries(serials.map(s => [s, { status: 'ready' }])) });
  return { devs, jobs, deviations, accounts, schedules, preflight };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const D = fakeData();
  const screen = serial => fs.readFileSync(path.join(SCREENS, `s${Number(serial.slice(-2)) % 8}.jpg`));
  const b = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const json = (r, body) => r.fulfill({ json: body });
  await p.route('**/api/devices', r => json(r, D.devs));
  await p.route(/\/api\/devices\/[A-Z0-9]+\/(thumb|frame|stream)/, r =>
    r.fulfill({ body: screen(r.request().url().split('/')[5]), contentType: 'image/jpeg' }));
  await p.route(/\/api\/devices\/[A-Z0-9]+\/packages/, r => json(r, ['com.vkontakte.android', 'com.instagram.android',
    'org.telegram.messenger', 'com.zhiliaoapp.musically', 'com.android.chrome']));
  await p.route(/\/api\/devices\/[A-Z0-9]+\/record$/, r => json(r, { recording: false }));
  await p.route(/\/api\/devices\/[A-Z0-9]+$/, r => json(r, { ...D.devs[3], current_app: 'com.vkontakte.android' }));
  await p.route(/\/api\/jobs(\?.*)?$/, r => json(r, D.jobs));
  await p.route(/\/api\/jobs\/[a-z0-9]+\/artifacts\//, r => r.fulfill({ body: screen('R58N1004'), contentType: 'image/jpeg' }));
  await p.route(/\/api\/jobs\/[a-z0-9]+$/, r => {
    const j = D.jobs.find(x => x.id === r.request().url().split('/').pop()) || D.jobs[0];
    json(r, { ...j, log: ['→ Прогрев VK', 'открываю VK', 'листаю ленту', j.held_reason ? 'жду решения человека: ' + j.held_reason : 'готово'],
      timeline: [{ i: 0, label: 'Открыть VK', status: 'ok', secs: 3 }, { i: 1, label: 'Листать ленту', status: 'ok', secs: 580 }] });
  });
  await p.route(/\/api\/deviations(\?.*)?$/, r => json(r, { deviations: D.deviations, unseen: 2 }));
  await p.route('**/api/accounts', r => json(r, D.accounts));
  await p.route('**/api/schedules', r => json(r, D.schedules));
  await p.route('**/api/run/preflight', r => json(r, D.preflight(JSON.parse(r.request().postData()).serials)));
  await p.route('**/api/status', r => json(r, { jobs: { held: 1, running: 13 }, deviations_unseen: 2, scrcpy: true }));

  const shot = async (name, fn, wait = 1200) => {
    if (fn) await p.evaluate(fn);
    await p.waitForTimeout(wait);
    await p.screenshot({ path: path.join(OUT, name + '.png') });
    console.log('  ' + name + '.png');
  };
  await p.goto(BASE);
  await p.waitForTimeout(2500);
  await shot('fleet', () => setDensity && setDensity('M'));
  await shot('fleet-selected', () => { ['R58N1001', 'R58N1002', 'R58N1004', 'R58N1005', 'R58N1007'].forEach(s => S.selected.add(s)); renderFleet(); renderRunbar(); });
  await shot('bulk-actions', () => bulkMenu());
  await shot('run-dialog', () => { closeModal(); openRunDialog({ scenario: 'vk_auth' }); }, 1800);
  await shot('pult', () => { closeModal(); S.selected.clear(); renderRunbar(); openDevice('R58N1003'); }, 2000);
  await shot('builder', () => { recBegin(); }, 1500);
  await shot('scenarios', () => { recPause(); REC.builder = false; showView('scen'); }, 1500);
  await shot('runs', () => { showView('jobs'); pickJob('j3'); }, 1800);
  await shot('problems', () => showView('deviations'), 1500);
  await shot('schedule', () => showView('schedule'), 1500);
  await shot('accounts', () => showView('accounts'), 1500);

  // Палитра для docs/design-system.md — с адреса фермы, чтобы токены были настоящими.
  await p.route('**/__tokens.html', r => r.fulfill({ body: fs.readFileSync(path.join(__dirname, 'tokens.html')),
    contentType: 'text/html; charset=utf-8' }));
  await p.setViewportSize({ width: 1156, height: 620 });
  await p.goto(BASE + '__tokens.html');
  await p.waitForTimeout(600);
  await p.screenshot({ path: path.join(OUT, 'design-tokens.png'), fullPage: true });
  console.log('  design-tokens.png');
  await b.close();
})();
