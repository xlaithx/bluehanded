// Shared helpers for the dashboard pages.
const BH = {
  csrf: document.querySelector('meta[name="csrf-token"]').content,

  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  },

  time(ts) {
    return ts ? new Date(ts * 1000).toLocaleTimeString() : '';
  },

  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': BH.csrf},
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  },

  async verify(alertId, verdict) {
    const note = prompt(verdict === 'confirmed'
      ? 'Confirmed cheating device. Optional note (seat, student, what was found):'
      : 'False alarm. Optional note (who owns the device):', '');
    if (note === null) return null;
    let whitelist = false;
    if (verdict === 'false_alarm') {
      whitelist = confirm('Add this device to the whitelist so it never alerts again?');
    }
    return BH.post(`/api/alerts/${alertId}/verify`, {verdict, note, whitelist});
  },

  // Short alarm tone with the Web Audio API (no sound files needed).
  beep() {
    try {
      const ctx = BH._ctx || (BH._ctx = new (window.AudioContext || window.webkitAudioContext)());
      [0, 0.25, 0.5].forEach(t => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'square'; o.frequency.value = 880;
        g.gain.setValueAtTime(0.0001, ctx.currentTime + t);
        g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t + 0.18);
        o.connect(g).connect(ctx.destination);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
      });
    } catch (e) { /* audio blocked until the user clicks the page */ }
  },

  palette: ['#2563eb', '#16a34a', '#d97706', '#9333ea', '#dc2626', '#0891b2'],

  // Draw an RSSI chart (raw dotted, Kalman-filtered solid) per node.
  rssiChart(canvas, history, existing) {
    const datasets = [];
    Object.keys(history).sort().forEach((node, i) => {
      const color = BH.palette[i % BH.palette.length];
      const pts = history[node];
      datasets.push({label: `${node} raw`, data: pts.map(p => ({x: p[0] * 1000, y: p[1]})),
        borderColor: color, backgroundColor: color, showLine: false, pointRadius: 2, pointStyle: 'circle'});
      datasets.push({label: `${node} filtered`, data: pts.map(p => ({x: p[0] * 1000, y: p[2]})),
        borderColor: color, borderWidth: 2, pointRadius: 0, tension: 0.2});
    });
    if (existing) { existing.data.datasets = datasets; existing.update('none'); return existing; }
    return new Chart(canvas, {
      type: 'line',
      data: {datasets},
      options: {
        animation: false, responsive: true, parsing: false,
        scales: {
          x: {type: 'linear', ticks: {callback: v => new Date(v).toLocaleTimeString()}},
          y: {title: {display: true, text: 'RSSI (dBm)'}, suggestedMin: -100, suggestedMax: -30},
        },
        plugins: {legend: {labels: {boxWidth: 10}}},
      },
    });
  },
};
