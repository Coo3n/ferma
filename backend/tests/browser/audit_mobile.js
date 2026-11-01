// Playwright browser_run_code_unsafe filename; static frontend at 127.0.0.1:8782.
// No live backend: app polling is disabled, all API requests are intercepted.
async (browserPage) => {
    const context = await browserPage.context().browser().newContext();
    // Only this disposable context: the welcome tour must not steal table focus.
    await context.addInitScript(() => localStorage.setItem('farm.onb.off', 'true'));
    const page = await context.newPage();
    try {
    await page.route('**/js/app.js', r => r.fulfill({body: '', contentType: 'application/javascript'}));
    await page.route('**/api/**', r => r.fulfill({json: []}));
    const failures = [], results = [];
    const check = (ok, message) => { if (!ok) failures.push(message); };
    for (const width of [414, 1280, 1728]) {
        await page.setViewportSize({width, height: 896});
        await page.goto('http://127.0.0.1:8782/#accounts');
        await page.evaluate(() => document.fonts.ready);
        await page.evaluate(() => {
            // app.js normally reveals the page after startup; polling is disabled here.
            document.documentElement.classList.remove('boot', 'nofx');
            S.devices = [{online: true, name: 'Тестовый телефон', serial: 'fixture',
                battery: 10, temperature: 45, rom_used: 95, ram_free: 5, cpu: 90}];
            ACC.loaded = true;
            ACC.items = [{id: 'fixture', platform: 'vk', login: 'test_login', serial: 'fixture',
                has_password: true, status: 'active', proxy: '', note: ''}];
            renderAccounts();
        });
        await page.evaluate(async () => {
            await Promise.all(document.querySelector('#view-accounts').getAnimations({subtree: true})
                .map(a => a.finished.catch(() => {})));
        });
        const accounts = await page.evaluate(() => {
            const box = $('accList');
            return {doc: document.documentElement.scrollWidth, width: innerWidth,
                keyboard: box.tabIndex === 0 && !!box.getAttribute('aria-label')};
        });
        check(accounts.doc <= width, `accounts ${width}: document width ${accounts.doc}`);
        check(accounts.keyboard, `accounts ${width}: missing keyboard access`);
        await page.locator('#accList input[data-f="note"]').focus();
        check(await page.waitForFunction(() => {
            const e = document.querySelector('#accList input[data-f="note"]');
            const a = e.getBoundingClientRect(), b = e.closest('#accList').getBoundingClientRect();
            return a.left >= b.left && a.right <= b.right;
        }, null, {timeout: 2000}).then(() => true, () => false),
        `accounts ${width}: note cannot be reached by keyboard focus`);
        await page.evaluate(() => healthOpen());
        await page.locator('#modal').getByRole('heading').waitFor();
        // Finish CSS entry animation before geometry checks.
        await page.evaluate(async () => {
            await Promise.all(document.querySelector('#modal').getAnimations({subtree: true})
                .map(a => a.finished.catch(() => {})));
        });
        const health = await page.evaluate(() => {
            const table = document.querySelector('#mBody table');
            const region = table.closest('[role="region"]');
            return {region: !!region, keyboard: region?.tabIndex === 0,
                bounded: !!region && region.getBoundingClientRect().right <= innerWidth,
                warnings: [...table.querySelectorAll('td.bad')].length === 4 &&
                    [...table.querySelectorAll('td.bad')].every(c => /[а-яё]/i.test(c.textContent)),
                cpu: table.rows[1].cells[5].textContent};
        });
        check(health.region && health.keyboard && health.bounded,
            `health ${width}: missing bounded, named keyboard scroll region`);
        check(health.warnings, `health ${width}: warning values rely only on color`);
        check(health.cpu === '90%', `health ${width}: CPU value missing`);
        if (health.region) {
            await page.locator('#mBody [role="region"]').focus();
            await page.keyboard.press('End');
            await page.locator('#mBody [role="region"]').evaluate(e => { e.scrollLeft = e.scrollWidth; });
            check(await page.locator('#mBody tbody td:last-child').evaluate(e => {
                const a = e.getBoundingClientRect(), b = e.closest('[role="region"]').getBoundingClientRect();
                return a.right <= b.right + 1 && a.left >= b.left;
            }), `health ${width}: CPU column unreachable`);
        }
        results.push({width, accounts, health});
    }
    if (failures.length) throw new Error(failures.join('\n'));
    return results;
    } finally {
        await context.close();
    }
}
