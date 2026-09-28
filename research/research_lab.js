const form = document.querySelector('#status-form');
const runInput = document.querySelector('#run-id');
const statusOutput = document.querySelector('#status-output');
const experimentsOutput = document.querySelector('#experiments-output');
const reportOutput = document.querySelector('#report-output');

async function readJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Request failed.');
  return payload;
}

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const runId = runInput.value.trim();
  if (!runId) return;
  statusOutput.textContent = 'Loading...';
  experimentsOutput.textContent = '';
  reportOutput.textContent = '';
  try {
    const status = await readJson(`/api/research/status?run_id=${encodeURIComponent(runId)}`);
    statusOutput.textContent = JSON.stringify(status, null, 2);
    const experiments = await readJson(`/api/research/experiments?run_id=${encodeURIComponent(runId)}&limit=8`);
    experimentsOutput.textContent = JSON.stringify(experiments, null, 2);
    const report = await readJson(`/api/research/report?run_id=${encodeURIComponent(runId)}`);
    reportOutput.textContent = report.markdown;
  } catch (error) {
    statusOutput.textContent = error.message;
  }
});
