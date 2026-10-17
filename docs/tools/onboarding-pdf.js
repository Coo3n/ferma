/* docs/onboarding.pdf из docs/tools/onboarding.html — печать Chromium'ом.
       node docs/tools/onboarding-pdf.js [путь-к-playwright]           */
const path = require('path');
const { chromium } = require(process.argv[2] || 'playwright');

(async () => {
  const b = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const p = await b.newPage();
  await p.goto('file://' + path.join(__dirname, 'onboarding.html'));
  await p.waitForTimeout(800);
  await p.pdf({ path: path.join(__dirname, '..', 'onboarding.pdf'), format: 'A4', printBackground: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="width:100%;font-size:8px;color:#888;text-align:center">Android Farm · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '14mm', bottom: '16mm', left: '14mm', right: '14mm' } });
  await b.close();
  console.log('docs/onboarding.pdf');
})();
