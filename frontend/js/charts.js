// Real-time charts: CPU + RAM, 1Hz updates, 30-minute sliding window.

import { getToken } from './api.js';

const WINDOW_SECONDS = 30 * 60;
let ws = null;
let charts = {};
let currentTarget = null;

function newChart(ctx, label, color) {
  return new Chart(ctx, {
    type: 'line',
    data: { datasets: [{
      label, data: [], borderColor: color, backgroundColor: color + '33',
      borderWidth: 1.5, tension: 0.25, pointRadius: 0, fill: true,
    }]},
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      parsing: false, normalized: true,
      scales: {
        x: { type: 'time', time: { unit: 'minute' },
             ticks: { color: '#64748b', maxTicksLimit: 6 },
             grid:  { color: '#1e293b' } },
        y: { min: 0, max: 1,
             ticks: { color: '#64748b',
                      callback: v => (v * 100).toFixed(0) + '%' },
             grid:  { color: '#1e293b' } },
      },
      plugins: { legend: { labels: { color: '#94a3b8' } } },
    },
  });
}

export function mountCharts(cpuCanvas, memCanvas) {
  disposeCharts();
  charts.cpu = newChart(cpuCanvas.getContext('2d'), 'CPU',    '#0ea5e9');
  charts.mem = newChart(memCanvas.getContext('2d'), 'Memoria','#a78bfa');
}

export function disposeCharts() {
  for (const k of Object.keys(charts)) { charts[k]?.destroy(); delete charts[k]; }
}

function pushPoint(chart, t, y) {
  const ds = chart.data.datasets[0].data;
  ds.push({ x: t * 1000, y });
  const cutoff = (t - WINDOW_SECONDS) * 1000;
  while (ds.length && ds[0].x < cutoff) ds.shift();
  chart.update('none');
}

export function subscribe(credId, target) {
  currentTarget = target;
  if (ws && ws.readyState <= 1) ws.close();

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/api/ws/stats?token=${getToken()}`);

  ws.addEventListener('open', () => {
    ws.send(JSON.stringify({ type: 'subscribe', cred_id: credId, target }));
  });
  ws.addEventListener('message', (ev) => {
    const data = JSON.parse(ev.data);
    if (data.error) return;
    if (charts.cpu) pushPoint(charts.cpu, data.t, data.cpu ?? 0);
    if (charts.mem) pushPoint(charts.mem, data.t, data.mem ?? 0);
    document.dispatchEvent(new CustomEvent('pmx:stats', { detail: data }));
  });
  ws.addEventListener('close', () => { /* will be reopened on next subscribe */ });
}

export function unsubscribe() {
  currentTarget = null;
  if (ws) { ws.close(); ws = null; }
}
