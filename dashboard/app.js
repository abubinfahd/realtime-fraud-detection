/**
 * Real-Time Fraud Detection System — Mission Control Client
 *
 * Features:
 * - Resilient WebSocket with exponential backoff & jitter reconnection.
 * - Initial state hydration via FastAPI REST endpoints (/api/v1/alerts/recent, /api/v1/metrics).
 * - Real-time explainability card rendering (LightGBM, Isolation Forest, Rule Overrides, Velocity context).
 * - Live transaction ticker stream with status badges.
 * - Web Audio API synthesized alert pings (zero asset dependencies).
 * - Interactive filtering (All / Flagged / Rejected) and local attack simulation.
 */

(function () {
  'use strict';

  // --- Configuration & State ---
  const STATE = {
    connected: false,
    reconnectAttempts: 0,
    maxReconnectDelay: 15000,
    audioEnabled: true,
    filter: 'all',
    totalProcessed: 0,
    totalAlerts: 0,
    flaggedCount: 0,
    rejectedCount: 0,
    latencies: [],
    recentAlerts: [],
    maxCards: 50,
    maxTickerItems: 30,
    lastTpsTimestamp: Date.now(),
    eventsInWindow: 0,
    currentTps: 0.0,
  };

  // --- DOM Elements ---
  const els = {
    wsStatusBadge: document.getElementById('ws-status-badge'),
    wsStatusIndicator: document.getElementById('ws-status-indicator'),
    wsStatusText: document.getElementById('ws-status-text'),
    kpiTps: document.getElementById('kpi-tps'),
    kpiTotalProcessed: document.getElementById('kpi-total-processed'),
    kpiLatency: document.getElementById('kpi-latency'),
    kpiTotalAlerts: document.getElementById('kpi-total-alerts'),
    kpiFlagged: document.getElementById('kpi-flagged'),
    kpiFlaggedPct: document.getElementById('kpi-flagged-pct'),
    kpiRejected: document.getElementById('kpi-rejected'),
    kpiRejectedPct: document.getElementById('kpi-rejected-pct'),
    alertsContainer: document.getElementById('alerts-container'),
    alertsEmptyState: document.getElementById('alerts-empty-state'),
    feedCounter: document.getElementById('feed-counter'),
    tickerContainer: document.getElementById('ticker-container'),
    toggleSoundBtn: document.getElementById('toggle-sound-btn'),
    soundIconOn: document.getElementById('sound-icon-on'),
    soundLabel: document.getElementById('sound-label'),
    triggerSimBtn: document.getElementById('trigger-sim-btn'),
    clearFeedBtn: document.getElementById('clear-feed-btn'),
    filterAll: document.getElementById('filter-all'),
    filterFlagged: document.getElementById('filter-flagged'),
    filterRejected: document.getElementById('filter-rejected'),
  };

  // --- Web Audio API Chime Generator ---
  let audioCtx = null;
  function playAlertChime(isSevere = false) {
    if (!STATE.audioEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = isSevere ? 'sawtooth' : 'sine';
      osc.frequency.setValueAtTime(isSevere ? 587.33 : 880.0, audioCtx.currentTime); // D5 or A5
      if (isSevere) {
        osc.frequency.exponentialRampToValueAtTime(329.63, audioCtx.currentTime + 0.25); // Pitch drop
      }

      gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + (isSevere ? 0.35 : 0.2));

      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + (isSevere ? 0.35 : 0.2));
    } catch {
      // Audio not permitted without interaction or unsupported
    }
  }

  // --- Audio Toggle Handler ---
  els.toggleSoundBtn.addEventListener('click', () => {
    STATE.audioEnabled = !STATE.audioEnabled;
    if (STATE.audioEnabled) {
      els.soundLabel.textContent = 'Audio: ON';
      els.soundIconOn.classList.remove('text-slate-500');
      els.soundIconOn.classList.add('text-emerald-400');
      playAlertChime(false);
    } else {
      els.soundLabel.textContent = 'Audio: MUTED';
      els.soundIconOn.classList.remove('text-emerald-400');
      els.soundIconOn.classList.add('text-slate-500');
    }
  });

  // --- Formatting Helpers ---
  function formatMoney(amount) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(amount || 0);
  }

  function formatTimestamp(tsString) {
    try {
      const d = tsString ? new Date(tsString) : new Date();
      return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
        '.' + String(d.getMilliseconds()).padStart(3, '0');
    } catch {
      return 'just now';
    }
  }

  function truncate(str, len = 8) {
    if (!str) return '';
    return str.length > len ? str.substring(0, len) + '…' : str;
  }

  // --- KPI Telemetry Updates ---
  function updateKpis() {
    els.kpiTotalAlerts.textContent = STATE.totalAlerts.toLocaleString();
    els.kpiFlagged.textContent = STATE.flaggedCount.toLocaleString();
    els.kpiRejected.textContent = STATE.rejectedCount.toLocaleString();
    els.kpiTotalProcessed.textContent = STATE.totalProcessed.toLocaleString();

    // Ratios
    const total = STATE.totalAlerts || 1;
    const flaggedPct = ((STATE.flaggedCount / total) * 100).toFixed(0);
    const rejectedPct = ((STATE.rejectedCount / total) * 100).toFixed(0);
    els.kpiFlaggedPct.textContent = `(${flaggedPct}%)`;
    els.kpiRejectedPct.textContent = `(${rejectedPct}%)`;

    // Latency
    if (STATE.latencies.length > 0) {
      const sorted = [...STATE.latencies].sort((a, b) => a - b);
      const p95Idx = Math.floor(sorted.length * 0.95);
      const p95 = sorted[p95Idx] || sorted[sorted.length - 1];
      els.kpiLatency.textContent = p95.toFixed(2);
    }

    // TPS calculation based on rolling time window
    const now = Date.now();
    const elapsedSec = (now - STATE.lastTpsTimestamp) / 1000;
    if (elapsedSec >= 2.0) {
      STATE.currentTps = (STATE.eventsInWindow / elapsedSec).toFixed(1);
      els.kpiTps.textContent = STATE.currentTps;
      STATE.eventsInWindow = 0;
      STATE.lastTpsTimestamp = now;
    }
  }

  // --- WebSocket Status Badge Manager ---
  function setWsStatus(status, text, colorClass, dotColorClass) {
    els.wsStatusText.textContent = text;
    els.wsStatusText.className = `text-xs font-mono font-semibold tracking-wide ${colorClass}`;
    els.wsStatusIndicator.className = `w-2.5 h-2.5 rounded-full ${dotColorClass} live-pulse`;
  }

  // --- Render High-Risk Threat Card ---
  function renderAlertCard(alert, isSimulated = false) {
    if (els.alertsEmptyState) {
      els.alertsEmptyState.style.display = 'none';
    }

    const isRejected = (alert.status || '').toUpperCase() === 'REJECTED';
    const statusColor = isRejected ? 'rose' : 'amber';
    const statusBg = isRejected ? 'bg-rose-500/10 border-rose-500/30' : 'bg-amber-500/10 border-amber-500/30';
    const statusBadge = isRejected ? 'bg-rose-500 text-white' : 'bg-amber-500 text-slate-950 font-bold';
    const statusIcon = isRejected ? '⛔' : '⚠️';

    const signals = alert.signals || {};
    const velocity = alert.velocity_context || {};
    const lgbmProb = ((signals.lgbm_fraud_prob || 0) * 100).toFixed(1);
    const isoScore = ((signals.anomaly_score || 0) * 100).toFixed(1);
    const ruleViolations = signals.rule_violations || [];
    const riskScore = (alert.risk_score !== undefined ? alert.risk_score : 0.85).toFixed(4);

    const card = document.createElement('div');
    card.className = `alert-card animate-card-in glass-card rounded-xl p-4 border ${statusBg} hover:border-${statusColor}-500/50 transition shadow-lg`;
    card.setAttribute('data-status', (alert.status || '').toLowerCase());

    let rulesHtml = '';
    if (ruleViolations.length > 0) {
      rulesHtml = `
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          ${ruleViolations.map(r => `
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-950/80 text-rose-300 border border-rose-800/60">
              <span>🚨</span> ${escapeHtml(r)}
            </span>
          `).join('')}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="flex items-start justify-between gap-3">

        <div class="flex items-center gap-2.5">
          <span class="px-2.5 py-1 rounded-md text-xs font-mono font-bold tracking-wider uppercase ${statusBadge} shadow-sm">
            ${statusIcon} ${escapeHtml(alert.status || 'ALERT')}
          </span>
          <span class="text-sm font-mono font-bold text-white tracking-tight">${formatMoney(alert.amount)}</span>
          <span class="text-xs text-slate-400 font-mono">USD</span>
          ${isSimulated ? '<span class="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700/50">DEMO SIM</span>' : ''}
        </div>

        <div class="flex items-center gap-2 text-xs font-mono text-slate-400">
          <span>${formatTimestamp(alert.timestamp)}</span>
          <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px]">${alert.inference_latency_ms ? alert.inference_latency_ms.toFixed(1) + 'ms' : '< 1ms'}</span>
        </div>

      </div>

      <!-- Merchant & Account Info -->
      <div class="mt-2 text-xs text-slate-300 flex flex-wrap items-center gap-y-1 gap-x-4">
        <div><span class="text-slate-500">Merchant:</span> <strong class="text-slate-200">${escapeHtml(alert.merchant_name || 'Online Merchant')}</strong> <span class="text-slate-500 font-mono text-[11px]">(${escapeHtml(alert.merchant_category || 'general')})</span></div>
        <div><span class="text-slate-500">User:</span> <code class="text-indigo-300 font-mono text-[11px]" title="${escapeHtml(alert.user_id)}">${truncate(alert.user_id, 10)}</code></div>
        <div><span class="text-slate-500">TxID:</span> <code class="text-slate-400 font-mono text-[11px]">${truncate(alert.transaction_id, 12)}</code></div>
      </div>

      <!-- Explainability Signal Pills -->
      <div class="mt-3 pt-2.5 border-t border-slate-800/80 flex flex-wrap items-center gap-2 text-[11px]">
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-slate-300 font-mono font-medium">
          Risk Score: <strong class="${isRejected ? 'text-rose-400' : 'text-amber-400'}">${riskScore}</strong>
        </span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-slate-300 font-mono">
          LightGBM: <strong class="text-blue-400">${lgbmProb}%</strong>
        </span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-slate-300 font-mono">
          Anomaly Score: <strong class="text-purple-400">${isoScore}%</strong>
        </span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-slate-400 font-mono">
          Velocity: ${velocity.tx_count_1m !== undefined ? velocity.tx_count_1m : 0} in 60s
        </span>
      </div>

      ${rulesHtml}
    `;

    // Apply active filter
    if (STATE.filter !== 'all' && (alert.status || '').toLowerCase() !== STATE.filter) {
      card.style.display = 'none';
    }

    // Insert at the top of the container
    els.alertsContainer.insertBefore(card, els.alertsContainer.firstChild);

    // Limit cards count to prevent DOM lag
    const allCards = els.alertsContainer.querySelectorAll('.alert-card');
    if (allCards.length > STATE.maxCards) {
      allCards[allCards.length - 1].remove();
    }

    // Update counter badge
    els.feedCounter.textContent = `${allCards.length} alerts`;
  }

  // --- Add Mini Row to Live Transaction Ticker ---
  function addTickerItem(status, txId, amount, rule = '') {
    const isApproved = status.toUpperCase() === 'APPROVED';
    const isRejected = status.toUpperCase() === 'REJECTED';
    const badgeColor = isApproved ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' :
                      isRejected ? 'text-rose-400 bg-rose-500/10 border-rose-500/20' :
                      'text-amber-400 bg-amber-500/10 border-amber-500/20';

    const row = document.createElement('div');
    row.className = 'flex items-center justify-between p-2 rounded-lg bg-slate-900/60 border border-slate-800/80 animate-card-in';
    row.innerHTML = `
      <div class="flex items-center gap-2">
        <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border ${badgeColor}">${escapeHtml(status)}</span>
        <span class="text-slate-300 font-mono">${truncate(txId, 10)}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-white font-mono font-semibold">${formatMoney(amount)}</span>
        <span class="text-[10px] text-slate-500">${new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
      </div>
    `;

    els.tickerContainer.insertBefore(row, els.tickerContainer.firstChild);
    const items = els.tickerContainer.children;
    if (items.length > STATE.maxTickerItems) {
      items[items.length - 1].remove();
    }
  }

  function escapeHtml(str) {
    if (str === undefined || str === null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // --- Filter Event Listeners ---
  function setFilter(newFilter) {
    STATE.filter = newFilter;
    [els.filterAll, els.filterFlagged, els.filterRejected].forEach(btn => {
      btn.className = 'px-2.5 py-1 text-xs rounded-md bg-slate-800 text-slate-400 hover:text-white font-medium transition';
    });

    if (newFilter === 'all') {
      els.filterAll.className = 'px-2.5 py-1 text-xs rounded-md bg-blue-600 text-white font-medium transition';
    } else if (newFilter === 'flagged') {
      els.filterFlagged.className = 'px-2.5 py-1 text-xs rounded-md bg-amber-600 text-white font-medium transition';
    } else if (newFilter === 'rejected') {
      els.filterRejected.className = 'px-2.5 py-1 text-xs rounded-md bg-rose-600 text-white font-medium transition';
    }

    const cards = els.alertsContainer.querySelectorAll('.alert-card');
    cards.forEach(card => {
      const cardStatus = card.getAttribute('data-status');
      if (newFilter === 'all' || cardStatus === newFilter) {
        card.style.display = 'block';
      } else {
        card.style.display = 'none';
      }
    });
  }

  els.filterAll.addEventListener('click', () => setFilter('all'));
  els.filterFlagged.addEventListener('click', () => setFilter('flagged'));
  els.filterRejected.addEventListener('click', () => setFilter('rejected'));

  // --- Clear Feed Handler ---
  els.clearFeedBtn.addEventListener('click', () => {
    els.alertsContainer.innerHTML = '';
    if (els.alertsEmptyState) {
      els.alertsEmptyState.style.display = 'flex';
      els.alertsContainer.appendChild(els.alertsEmptyState);
    }
    els.feedCounter.textContent = '0 alerts';
  });

  // --- Initial REST State Hydration ---
  async function hydrateInitialState() {
    try {
      // 1. Fetch recent alerts for instant hydration
      const res = await fetch('/api/v1/alerts/recent?limit=10');
      if (res.ok) {
        const alerts = await res.json();
        if (Array.isArray(alerts) && alerts.length > 0) {
          alerts.reverse().forEach(alert => {
            renderAlertCard(alert, false);
            STATE.totalAlerts++;
            if ((alert.status || '').toUpperCase() === 'REJECTED') STATE.rejectedCount++;
            else STATE.flaggedCount++;
            if (alert.inference_latency_ms) STATE.latencies.push(alert.inference_latency_ms);
          });
        }
      }
    } catch (e) {
      console.warn('Initial alerts hydration fetch skipped:', e);
    }

    try {
      // 2. Fetch metrics
      const mRes = await fetch('/api/v1/metrics');
      if (mRes.ok) {
        const metrics = await mRes.json();
        if (metrics.total_processed) {
          STATE.totalProcessed = metrics.total_processed;
        }
        if (metrics.average_latency_ms) {
          STATE.latencies.push(metrics.average_latency_ms);
        }
      }
    } catch (e) {
      console.warn('Metrics hydration fetch skipped:', e);
    }

    updateKpis();
  }

  // --- WebSocket Connection Engine ---
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8000';
    const wsUrl = `${protocol}//${host}/ws/live-stream`;

    setWsStatus('connecting', 'CONNECTING...', 'text-amber-400', 'bg-amber-400');
    let socket = null;

    try {
      socket = new WebSocket(wsUrl);
    } catch (err) {
      console.error('WebSocket instantiation error:', err);
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      STATE.connected = true;
      STATE.reconnectAttempts = 0;
      setWsStatus('connected', 'CONNECTED', 'text-emerald-400', 'bg-emerald-400');
      console.log('Real-time fraud alert WebSocket connected:', wsUrl);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleStreamPayload(payload);
      } catch (err) {
        console.error('Failed to parse incoming WebSocket message:', err, event.data);
      }
    };

    socket.onerror = (err) => {
      console.warn('WebSocket encountered error:', err);
    };

    socket.onclose = () => {
      STATE.connected = false;
      setWsStatus('disconnected', `RECONNECTING (${STATE.reconnectAttempts + 1})`, 'text-rose-400', 'bg-rose-500');
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    STATE.reconnectAttempts++;
    const delay = Math.min(STATE.maxReconnectDelay, 1000 * Math.pow(1.5, STATE.reconnectAttempts)) + (Math.random() * 500);
    setTimeout(connectWebSocket, delay);
  }

  // --- Inbound Stream Event Handler ---
  function handleStreamPayload(payload) {
    STATE.totalProcessed++;
    STATE.eventsInWindow++;

    // Check if it's an alert or heartbeat/general event
    const eventType = payload.event_type || 'FRAUD_ALERT';
    const status = (payload.status || 'APPROVED').toUpperCase();

    if (payload.inference_latency_ms) {
      STATE.latencies.push(payload.inference_latency_ms);
      if (STATE.latencies.length > 500) STATE.latencies.shift();
    }

    // Always log to ticker
    addTickerItem(status, payload.transaction_id || 'tx_demo', payload.amount || 0);

    // If it's a threat alert (FLAGGED or REJECTED)
    if (status === 'FLAGGED' || status === 'REJECTED') {
      STATE.totalAlerts++;
      if (status === 'REJECTED') {
        STATE.rejectedCount++;
        playAlertChime(true);
      } else {
        STATE.flaggedCount++;
        playAlertChime(false);
      }
      renderAlertCard(payload, false);
    }

    updateKpis();
  }

  // --- Simulate Attack Event Generator (Manual Demo Trigger) ---
  const DEMO_ATTACK_PATTERNS = [
    {
      status: 'REJECTED',
      amount: 4850.00,
      merchant_name: 'Geneva Luxury Timepieces',
      merchant_category: 'jewelry',
      risk_score: 0.9420,
      signals: {
        lgbm_fraud_prob: 0.892,
        anomaly_score: 0.812,
        rule_violations: ['RULE_03: Impossible travel velocity (108,000 km/h)']
      },
      velocity_context: { tx_count_1m: 2, tx_count_10m: 3, tx_sum_10m: 4950.00, amount_to_avg_ratio: 12.5 }
    },
    {
      status: 'REJECTED',
      amount: 4.50,
      merchant_name: 'Online MicroPay Digital',
      merchant_category: 'digital_goods',
      risk_score: 0.9850,
      signals: {
        lgbm_fraud_prob: 0.945,
        anomaly_score: 0.912,
        rule_violations: ['RULE_01: Automated bot velocity burst (14 tx in 20s)']
      },
      velocity_context: { tx_count_1m: 14, tx_count_10m: 18, tx_sum_10m: 65.00, amount_to_avg_ratio: 0.8 }
    },
    {
      status: 'FLAGGED',
      amount: 1420.00,
      merchant_name: 'Midnight Offshore Exchange',
      merchant_category: 'crypto_financial',
      risk_score: 0.6840,
      signals: {
        lgbm_fraud_prob: 0.620,
        anomaly_score: 0.580,
        rule_violations: ['RULE_05: Nocturnal ATO pattern (3:42 AM + new device ID)']
      },
      velocity_context: { tx_count_1m: 1, tx_count_10m: 2, tx_sum_10m: 1420.00, amount_to_avg_ratio: 5.2 }
    },
    {
      status: 'FLAGGED',
      amount: 28500.00,
      merchant_name: 'Wholesale Electronics Direct',
      merchant_category: 'electronics',
      risk_score: 0.7210,
      signals: {
        lgbm_fraud_prob: 0.410,
        anomaly_score: 0.880,
        rule_violations: ['RULE_02: High-value single transaction >= $25,000.00']
      },
      velocity_context: { tx_count_1m: 1, tx_count_10m: 1, tx_sum_10m: 28500.00, amount_to_avg_ratio: 8.4 }
    }
  ];

  let demoPatternIdx = 0;
  els.triggerSimBtn.addEventListener('click', () => {
    const pattern = DEMO_ATTACK_PATTERNS[demoPatternIdx % DEMO_ATTACK_PATTERNS.length];
    demoPatternIdx++;

    const simulatedEvent = {
      event_type: 'FRAUD_ALERT',
      transaction_id: 'tx_sim_' + Math.random().toString(36).substring(2, 10),
      user_id: 'usr_' + Math.random().toString(36).substring(2, 12),
      amount: pattern.amount,
      currency: 'USD',
      status: pattern.status,
      risk_score: pattern.risk_score,
      merchant_name: pattern.merchant_name,
      merchant_category: pattern.merchant_category,
      signals: pattern.signals,
      velocity_context: pattern.velocity_context,
      timestamp: new Date().toISOString(),
      inference_latency_ms: +(Math.random() * 1.5 + 0.6).toFixed(2),
    };

    handleStreamPayload(simulatedEvent);
  });

  // --- Bootstrap on Load ---
  window.addEventListener('DOMContentLoaded', () => {
    // Inject seed ticker items
    addTickerItem('APPROVED', 'tx_init_01', 45.20);
    addTickerItem('APPROVED', 'tx_init_02', 129.00);
    addTickerItem('APPROVED', 'tx_init_03', 18.50);

    // Initial hydration and WebSocket connection
    hydrateInitialState();
    connectWebSocket();

    // Periodic TPS refresh timer
    setInterval(updateKpis, 1000);
  });

})();
