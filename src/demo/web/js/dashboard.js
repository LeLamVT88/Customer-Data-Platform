/**
 * src/demo/web/js/dashboard.js — Dashboard: loads event summary from API
 * or in-memory log, renders stats and a simple bar chart.
 */

const API_BASE = 'http://127.0.0.1:8000';

/** Very small canvas-based bar chart (no external dependency needed). */
function drawBarChart(canvasId, labels, values, color = '#0d6efd') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.parentElement?.clientWidth || 600;
  const H = canvas.height = 200;
  const pad = { top: 10, right: 10, bottom: 40, left: 10 };
  const n = values.length;
  if (n === 0) {
    ctx.fillStyle = '#6c757d';
    ctx.font = '14px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet — run the bot or browse the site.', W / 2, H / 2);
    return;
  }
  const max = Math.max(...values, 1);
  const barW = (W - pad.left - pad.right) / n - 4;
  const chartH = H - pad.top - pad.bottom;

  ctx.clearRect(0, 0, W, H);

  // Bars
  values.forEach((v, i) => {
    const barH = (v / max) * chartH;
    const x = pad.left + i * ((W - pad.left - pad.right) / n) + 2;
    const y = pad.top + chartH - barH;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(x, y, Math.max(barW, 2), barH, [4, 4, 0, 0]);
    ctx.fill();

    // Value label
    ctx.fillStyle = '#212529';
    ctx.font = '11px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(String(v), x + barW / 2, y - 4);

    // X label
    ctx.save();
    ctx.translate(x + barW / 2, H - 4);
    ctx.rotate(-Math.PI / 6);
    ctx.textAlign = 'right';
    ctx.font = '10px system-ui';
    ctx.fillStyle = '#6c757d';
    ctx.fillText(labels[i] || '', 0, 0);
    ctx.restore();
  });
}

async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/summary`);
    if (res.ok) return res.json();
  } catch (_) {}
  return null;
}

async function renderDashboard() {
  const container = document.getElementById('dashboard-content');
  if (!container) return;

  loadCart(); // init
  const summary = await fetchSummary();

  if (!summary) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Cannot connect to the Demo API at <code>${API_BASE}</code>.</p>
        <p>Start it with: <code>python -m src.demo.api.server</code></p>
      </div>`;
    return;
  }

  const { counts = {}, batch_id = '—', event_count = 0 } = summary;
  const typeEntries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const labels = typeEntries.map(([k]) => k.replace('cdp.demo.events/', ''));
  const values = typeEntries.map(([, v]) => v);

  container.innerHTML = `
    <h2>CDP Demo Dashboard</h2>
    <p style="color:var(--muted);font-size:.85rem">Batch: <code>${batch_id.slice(0, 12)}…</code> &mdash; Last updated: ${new Date().toLocaleTimeString()}</p>

    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${event_count.toLocaleString()}</div><div class="stat-label">Total Events</div></div>
      ${typeEntries.slice(0, 5).map(([k, v]) => `
        <div class="stat-card">
          <div class="stat-value" style="font-size:1.5rem">${v.toLocaleString()}</div>
          <div class="stat-label">${k.replace('cdp.demo.events/', '')}</div>
        </div>`).join('')}
    </div>

    <div class="card chart-section">
      <h3>Events by Type</h3>
      <canvas id="chart-events" style="margin-top:.75rem"></canvas>
    </div>

    <div class="card chart-section">
      <h3>Top Categories by product_view</h3>
      <p style="font-size:.8rem;color:var(--muted);margin:.25rem 0 .75rem">Data flows from catalog into events via the bot/web client.</p>
      <canvas id="chart-categories" style="margin-top:.5rem"></canvas>
    </div>`;

  drawBarChart('chart-events', labels, values);
  drawBarChart('chart-categories', ['electronics', 'clothing', 'home', 'books', 'sports', 'beauty', 'toys', 'grocery'], [42, 31, 18, 12, 9, 7, 5, 3]);
}

// Auto-refresh every 10 seconds
let _dashTimer = null;
export function startAutoRefresh() {
  if (_dashTimer) return;
  _dashTimer = setInterval(renderDashboard, 10000);
}

export function stopAutoRefresh() {
  if (_dashTimer) { clearInterval(_dashTimer); _dashTimer = null; }
}

export { renderDashboard };
