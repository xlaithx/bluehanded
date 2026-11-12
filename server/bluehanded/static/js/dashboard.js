// Live dashboard: floor map, alerts, nodes and device table, updated over Socket.IO.
(() => {
  const state = {room: null, nodes: [], devices: [], alerts: [], heat: null};
  const canvas = document.getElementById('map');
  const ctx = canvas.getContext('2d');
  const $ = id => document.getElementById(id);
  let detailMac = null, detailChart = null, hitboxes = [];

  // ---------------------------------------------------------------- socket
  const socket = io({transports: ['websocket', 'polling']});
  socket.on('connect', () => { $('conn').textContent = 'live'; $('conn').className = 'pill on'; });
  socket.on('disconnect', () => { $('conn').textContent = 'offline'; $('conn').className = 'pill off'; });
  socket.on('snapshot', s => {
    state.room = s.room; state.nodes = s.nodes; state.devices = s.devices; state.alerts = s.alerts;
    renderAll();
  });
  socket.on('devices', d => { state.devices = d; renderDevices(); drawMap(); refreshDetail(); });
  socket.on('nodes', n => { state.nodes = n; renderNodes(); drawMap(); });
  socket.on('alert', a => {
    state.alerts.unshift(a);
    renderAlerts();
    if ($('sound').checked) BH.beep();
    document.title = '⚠ ALERT · Blue-Handed';
    setTimeout(() => { document.title = 'Blue-Handed'; }, 8000);
  });
  socket.on('alert_update', a => {
    const i = state.alerts.findIndex(x => x.id === a.id);
    if (i >= 0) state.alerts[i] = a; else state.alerts.unshift(a);
    renderAlerts();
  });

  function renderAll() { renderAlerts(); renderNodes(); renderDevices(); drawMap(); }

  // ---------------------------------------------------------------- map
  function geometry() {
    const w = canvas.clientWidth;
    const room = state.room;
    const pad = 36;
    const scale = (w - 2 * pad) / room.width;
    const h = room.height * scale + 2 * pad;
    return {w, h, pad, scale, X: x => pad + x * scale, Y: y => pad + y * scale};
  }

  function drawMap() {
    if (!state.room || canvas.clientWidth < 100) return;  // hidden or not laid out yet
    const g = geometry();
    const dpr = window.devicePixelRatio || 1;
    canvas.style.height = g.h + 'px';
    canvas.width = g.w * dpr; canvas.height = g.h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, g.w, g.h);
    const css = getComputedStyle(document.body);

    // Heatmap layer
    if ($('show-heat').checked && state.heat) {
      const hm = state.heat, max = Math.max(1, ...hm.grid.flat());
      hm.grid.forEach((row, r) => row.forEach((v, c) => {
        if (!v) return;
        ctx.fillStyle = `rgba(220, 38, 38, ${0.08 + 0.6 * v / max})`;
        ctx.fillRect(g.X(c * hm.cell), g.Y(r * hm.cell), hm.cell * g.scale, hm.cell * g.scale);
      }));
    }

    // Room outline and 1 m grid
    ctx.strokeStyle = css.getPropertyValue('--grid'); ctx.lineWidth = 1;
    for (let x = 0; x <= state.room.width; x++) { ctx.beginPath(); ctx.moveTo(g.X(x), g.Y(0)); ctx.lineTo(g.X(x), g.Y(state.room.height)); ctx.stroke(); }
    for (let y = 0; y <= state.room.height; y++) { ctx.beginPath(); ctx.moveTo(g.X(0), g.Y(y)); ctx.lineTo(g.X(state.room.width), g.Y(y)); ctx.stroke(); }
    ctx.strokeStyle = css.getPropertyValue('--fg'); ctx.lineWidth = 2;
    ctx.strokeRect(g.X(0), g.Y(0), state.room.width * g.scale, state.room.height * g.scale);
    ctx.fillStyle = css.getPropertyValue('--muted'); ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText('FRONT (whiteboard)', g.X(state.room.width / 2), g.Y(0) - 12);
    ctx.textAlign = 'left';

    // Nodes
    state.nodes.forEach(n => {
      if (!n.enabled) return;
      ctx.fillStyle = n.online ? '#2563eb' : '#94a3b8';
      ctx.beginPath(); ctx.rect(g.X(n.x) - 7, g.Y(n.y) - 7, 14, 14); ctx.fill();
      ctx.fillStyle = css.getPropertyValue('--fg');
      const right = n.x > state.room.width / 2;
      ctx.textAlign = right ? 'right' : 'left';
      ctx.fillText(n.label || n.id, g.X(n.x) + (right ? -10 : 10), g.Y(n.y) + (n.y > state.room.height / 2 ? 20 : -10));
      ctx.textAlign = 'left';
    });

    // Devices
    hitboxes = [];
    const showAll = $('show-all').checked;
    state.devices.forEach(d => {
      if (!d.position || !d.active) return;
      if (!showAll && !d.suspicious) return;
      const x = g.X(d.position.x), y = g.Y(d.position.y);
      const color = d.whitelisted ? '#16a34a' : d.suspicious ? '#dc2626' : d.is_audio ? '#d97706' : '#64748b';
      ctx.fillStyle = color + '22'; ctx.strokeStyle = color + '66';
      ctx.beginPath(); ctx.arc(x, y, Math.min(d.position.error, 3) * g.scale, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(x, y, d.suspicious ? 9 : 6, 0, 2 * Math.PI); ctx.fill();
      if (d.suspicious) {
        ctx.strokeStyle = color; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 14 + 4 * Math.sin(Date.now() / 200), 0, 2 * Math.PI); ctx.stroke();
      }
      ctx.fillStyle = css.getPropertyValue('--fg');
      const nearRight = x > g.w - 140;
      ctx.textAlign = nearRight ? 'right' : 'left';
      ctx.fillText(d.name || d.mac.slice(-5), x + (nearRight ? -12 : 12), y + 4);
      ctx.textAlign = 'left';
      hitboxes.push({x, y, mac: d.mac});
    });
  }

  canvas.addEventListener('click', e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const hit = hitboxes.find(h => Math.hypot(h.x - mx, h.y - my) < 14);
    if (hit) openDetail(hit.mac);
  });
  window.addEventListener('resize', drawMap);
  ['show-all', 'show-heat'].forEach(id => $(id).addEventListener('change', () => { loadHeat(); drawMap(); }));

  async function loadHeat() {
    if (!$('show-heat').checked) return;
    state.heat = await (await fetch('/api/heatmap?minutes=30')).json();
    drawMap();
  }
  setInterval(loadHeat, 10000);

  // ---------------------------------------------------------------- alerts
  function renderAlerts() {
    const open = state.alerts.filter(a => a.status === 'open');
    $('alert-count').textContent = open.length;
    $('alert-count').className = 'badge' + (open.length ? ' hot' : '');
    const el = $('alerts');
    if (!state.alerts.length) { el.innerHTML = '<p class="empty">No alerts yet.</p>'; return; }
    el.innerHTML = state.alerts.slice(0, 30).map(a => `
      <div class="alert ${a.status} sev-${a.severity}">
        <div class="alert-top">
          <strong>${BH.esc(a.name || a.mac)}</strong>
          <span class="sev">${a.severity === 'high' ? 'Audio device' : 'Device'}</span>
          <span class="t">${BH.time(a.created_at)}</span>
        </div>
        <div class="alert-why">${BH.esc(a.reason)}</div>
        <div class="alert-where">${a.x != null ? `Approx. (${a.x.toFixed(1)} m, ${a.y.toFixed(1)} m)` : ''}
          ${a.nearest_node ? ` · nearest ${BH.esc(a.nearest_node)} ~${(a.nearest_distance || 0).toFixed(1)} m` : ''}
          ${a.rssi != null ? ` · ${a.rssi.toFixed(0)} dBm` : ''}</div>
        ${a.status === 'open' ? `
          <div class="alert-actions">
            <button data-id="${a.id}" data-v="confirmed" class="danger">Confirmed cheating</button>
            <button data-id="${a.id}" data-v="false_alarm">False alarm</button>
            <button data-mac="${BH.esc(a.mac)}" class="link">Details</button>
          </div>` : `
          <div class="alert-status">${a.status === 'confirmed' ? 'Confirmed' : 'False alarm'} by ${BH.esc(a.verified_by)}
            ${a.note ? ` · “${BH.esc(a.note)}”` : ''}</div>`}
      </div>`).join('');
  }

  $('alerts').addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.mac) return openDetail(b.dataset.mac);
    try { await BH.verify(b.dataset.id, b.dataset.v); } catch (err) { alert(err.message); }
  });

  // ---------------------------------------------------------------- nodes
  function renderNodes() {
    const now = Date.now() / 1000;
    $('nodes').innerHTML = state.nodes.map(n => `
      <div class="node ${n.online ? 'on' : 'off'} ${n.enabled ? '' : 'disabled'}">
        <div><i class="dot ${n.online ? 'node' : 'node-off'}"></i><strong>${BH.esc(n.label || n.id)}</strong> <small>${BH.esc(n.id)}</small></div>
        <small>(${n.x} m, ${n.y} m) · ${n.online ? 'online' : 'offline'}
          ${n.last_seen ? ` · ${Math.round(now - n.last_seen)} s ago` : ''}
          ${n.wifi_rssi ? ` · Wi-Fi ${n.wifi_rssi} dBm` : ''}${n.enabled ? '' : ' · not placed'}</small>
      </div>`).join('') || '<p class="empty">No nodes yet. Power on an ESP32 or add nodes in Admin.</p>';
  }

  // ---------------------------------------------------------------- devices
  function bestLink(d) {
    let best = null;
    for (const [node, l] of Object.entries(d.links)) if (!best || l.filtered > best.filtered) best = {node, ...l};
    return best;
  }

  function renderDevices() {
    const list = state.devices.filter(d => d.active);
    $('device-count').textContent = list.length;
    document.querySelector('#devices tbody').innerHTML = list.map(d => {
      const b = bestLink(d);
      const status = d.whitelisted ? '<span class="tag white">Whitelisted</span>'
        : d.suspicious ? '<span class="tag sus">Suspicious</span>'
        : d.is_audio ? '<span class="tag audio">Audio</span>' : '<span class="tag">Seen</span>';
      return `<tr class="${d.suspicious ? 'sus' : ''}">
        <td>${status}</td><td><code>${BH.esc(d.mac)}</code></td>
        <td>${BH.esc(d.name || d.whitelist_label || '')}</td>
        <td>${b ? `${b.filtered} dBm <small>(raw ${b.raw})</small>` : ''}</td>
        <td>${b ? `${BH.esc(b.node)} ~${b.distance} m` : ''}</td>
        <td>${d.position ? `(${d.position.x.toFixed(1)}, ${d.position.y.toFixed(1)}) ±${d.position.error.toFixed(1)} m` : ''}</td>
        <td>${d.persistence}</td>
        <td><button class="link" data-mac="${BH.esc(d.mac)}">Details</button></td></tr>`;
    }).join('');
  }
  document.querySelector('#devices').addEventListener('click', e => {
    const b = e.target.closest('button[data-mac]');
    if (b) openDetail(b.dataset.mac);
  });

  // ---------------------------------------------------------------- detail dialog
  async function openDetail(mac) {
    detailMac = mac;
    $('detail-link').href = `/device/${encodeURIComponent(mac)}`;
    $('detail').showModal();
    await refreshDetail(true);
  }
  $('detail').addEventListener('close', () => { detailMac = null; });

  let lastHistory = 0;
  async function refreshDetail(force) {
    if (!detailMac) return;
    const d = state.devices.find(x => x.mac === detailMac);
    $('detail-title').textContent = d ? (d.name || d.mac) : detailMac;
    if (d) {
      $('detail-body').innerHTML = `
        <dl class="kv">
          <dt>MAC</dt><dd><code>${BH.esc(d.mac)}</code> (${BH.esc(d.addr_type || '?')})</dd>
          <dt>Name</dt><dd>${BH.esc(d.name || '(not advertised)')}</dd>
          <dt>Profile</dt><dd>${d.is_audio ? 'Audio device: ' + BH.esc(d.audio_reason) : 'Not recognised as audio'}</dd>
          <dt>Position</dt><dd>${d.position ? `(${d.position.x.toFixed(2)} m, ${d.position.y.toFixed(2)} m) ±${d.position.error.toFixed(1)} m, ${d.position.method}` : 'unknown'}</dd>
          <dt>Why</dt><dd>${BH.esc(d.reasons.join('; ') || '-')}</dd>
          <dt>First seen</dt><dd>${BH.time(d.first_seen)}</dd>
        </dl>
        <table class="mini"><tr><th>Node</th><th>Raw</th><th>Filtered</th><th>Distance</th><th>Band</th></tr>
        ${Object.entries(d.links).map(([n, l]) => `<tr><td>${BH.esc(n)}</td><td>${l.raw}</td><td>${l.filtered}</td><td>${l.distance} m</td><td>${l.band}</td></tr>`).join('')}</table>`;
    }
    if (force || Date.now() - lastHistory > 2000) {
      lastHistory = Date.now();
      const h = await (await fetch(`/api/device/${encodeURIComponent(detailMac)}/history`)).json();
      detailChart = BH.rssiChart($('rssi-chart'), h, force ? (detailChart && detailChart.destroy(), null) : detailChart);
    }
  }

  // Keep the pulsing ring animated.
  setInterval(() => { if (state.devices.some(d => d.suspicious)) drawMap(); }, 100);
})();
