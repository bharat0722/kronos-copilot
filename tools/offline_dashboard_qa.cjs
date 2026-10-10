// Optional Playwright developer check: synthetic responses only, no external requests.
const fs = require('fs');
const http = require('http');
const path = require('path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = path.resolve(process.argv[3]);
fs.mkdirSync(output, {recursive: true});
const app = path.join(root, 'app');
const server = http.createServer((req, res) => {
  const relative = new URL(req.url, 'http://localhost').pathname;
  const file = path.resolve(root, '.' + relative);
  if (!file.startsWith(app + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end(); return;
  }
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true});
  const checks = [];
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['phone', 390, 844], ['ipad', 834, 1112]]) {
      const context = await browser.newContext({viewport: {width, height}});
      let teamStatus = 'FAILED', requests = 0, authNeeded = true;
      const errors = [], external = [];
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => {
        if (message.type() === 'error' && !/401|404/.test(message.text())) errors.push(message.text());
      });
      await context.route('**/*', async route => {
        const request = route.request();
        const address = new URL(request.url());
        if (address.origin !== url) { external.push(address.origin); await route.abort(); return; }
        const endpoint = address.pathname;
        if (!endpoint.startsWith('/api/')) { await route.continue(); return; }
        if (endpoint === '/api/news' && authNeeded) {
          await route.fulfill({status: 401, contentType: 'application/json', body: JSON.stringify({code: 'AUTH_REQUIRED'})});
          return;
        }
        let body = {};
        if (endpoint === '/api/dashboard') body = fixture.dashboard;
        else if (endpoint === '/api/news') body = fixture.news;
        else if (endpoint === '/api/session') { authNeeded = false; body = {authenticated: true}; }
        else if (endpoint === '/api/agents/result') body = fixture.teams[teamStatus];
        else if (endpoint === '/api/agents/run') {
          requests++; await new Promise(resolve => setTimeout(resolve, 180));
          teamStatus = 'COMPLETE'; body = fixture.teams[teamStatus];
        } else if (endpoint === '/api/fusion') body = fixture.fusions[teamStatus];
        else if (endpoint === '/api/pipeline') body = {...fixture.pipeline, stages: {...fixture.pipeline.stages,
          agents: {status: teamStatus === 'FAILED' ? 'FAILED' : teamStatus === 'COMPLETE' ? 'HEALTHY' : 'DEGRADED',
                   team_status: teamStatus, rows: teamStatus === 'COMPLETE' ? 3 : teamStatus === 'PARTIAL' ? 2 : 0, errors: [], warnings: [], snapshot_id: fixture.news.evidence_snapshot_id},
          news: {status: 'HEALTHY', rows: 0, errors: [], warnings: []}}};
        else if (endpoint === '/api/explanation') body = {available: false};
        else if (endpoint.includes('search')) body = {results: []};
        await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      });
      await page.goto(url + '/app/dashboard.html');
      await page.locator('#lan-access-dialog').waitFor({state: 'visible'});
      await page.locator('#lan-access-code').fill('synthetic-qa-code-only');
      await page.locator('#lan-access-form button[type="submit"]').click();
      await page.waitForFunction(() => document.querySelector('#agent-status').textContent.includes('failed'));
      const failure = await page.locator('#agent-status').innerText();
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#agent-status').textContent.includes('failed'));
      await page.locator('#agent-section').scrollIntoViewIfNeeded();
      const failedDetails = await page.locator('.agent-card').allTextContents();
      const failureDetailsVisible = failedDetails.length === 3 && failedDetails.every(text =>
        text.includes('output truncated') && text.includes('2 attempts') && !text.includes('No analysis yet.'));
      await page.screenshot({path: path.join(output, name + '-failed.png')});
      await page.evaluate(() => { const button = document.querySelector('#agent-run'); button.click(); button.click(); });
      await page.waitForFunction(() => document.querySelector('#agent-status').textContent.includes('analysis for this evidence snapshot'));
      const complete = await page.locator('#agent-status').innerText();
      await page.locator('input[name="forecast-horizon"][value="120"]').check({force: true});
      const result = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        ticker: document.querySelector('#ticker-input').value,
        helper: document.querySelector('#local-note').textContent,
        canvases: document.querySelectorAll('canvas').length,
        nonblank: [...document.querySelectorAll('canvas')].some(canvas => {
          const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data;
          return pixels && pixels.some((value, index) => index % 4 === 3 && value > 0);
        })}));
      await page.screenshot({path: path.join(output, name + '-complete.png')});
      teamStatus = 'PARTIAL';
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#agent-status').textContent.includes('2 of 3'));
      const partial = await page.locator('#agent-status').innerText();
      const risk = await page.locator('.agent-card[data-agent="risk"] [data-role="status"]').innerText();
      const old = fixture.teams.PARTIAL.eligible;
      fixture.teams.PARTIAL.eligible = false;
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#agent-status').textContent.includes('Evidence expired'));
      const staleDisabled = await page.locator('#agent-run').isDisabled();
      const secretAbsent = await page.locator('#lan-access-code').inputValue() === '';
      fixture.teams.PARTIAL.eligible = old;
      checks.push({name, failure, failureDetailsVisible, complete, partial, risk, staleDisabled, secretAbsent, authFlow: true, requests, ...result, errors, external,
        pass: result.scrollWidth <= width && result.nonblank && requests === 1 && !errors.length && !external.length && result.ticker === 'TESTCO' && staleDisabled && risk === 'Failed' && secretAbsent && failureDetailsVisible});
      await context.close();
    }
  } finally { await browser.close(); server.close(); }
  fs.writeFileSync(path.join(output, 'browser_qa.json'), JSON.stringify(checks, null, 2));
  console.log(JSON.stringify(checks));
  process.exitCode = checks.every(check => check.pass) ? 0 : 1;
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
