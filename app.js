'use strict';

/* ══════════════════════════════════════════════════════════════════
   CONFIG  — swap placeholder URLs for real ones when ready
══════════════════════════════════════════════════════════════════ */
const CONFIG = {
  // Inbound: this server receives a trigger from IVA
  triggerEndpoint:  '/api/auth/trigger',

  // Poll this to check for a pending auth request (every 2 s)
  stateEndpoint:    '/api/auth/state',

  // Inbound: frontend posts the user's approve/deny to this server
  responseEndpoint: '/api/auth/response',

  // Outbound callback: server forwards result here (configured in server.py)
  outboundCallback: 'https://placeholder.api/iva/auth/callback',  // TODO

  // Web Push endpoints
  vapidPublicKeyEndpoint: '/api/push/vapid-public-key',
  pushSubscribeEndpoint:  '/api/push/subscribe',
  pushUnsubEndpoint:      '/api/push/unsubscribe',

  pollMs: 2000,
};

/* ══════════════════════════════════════════════════════════════════
   STATE
══════════════════════════════════════════════════════════════════ */
let appState = {
  page:        'login',   // 'login' | 'dashboard' | 'home'
  userEmail:   '',
  authPending: false,
  requestId:   null,
  triggeredAt: null,
  pollTimer:   null,
};

/* ══════════════════════════════════════════════════════════════════
   DOM REFS
══════════════════════════════════════════════════════════════════ */
// Pages
const $loginPage     = document.getElementById('login-page');
const $dashboardPage = document.getElementById('dashboard-page');
const $homePage      = document.getElementById('home-page');

// Login
const $loginNotif  = document.getElementById('login-notif');
const $loginForm   = document.getElementById('login-form');
const $emailInput  = document.getElementById('email');
const $passInput   = document.getElementById('password');
const $loginError  = document.getElementById('login-error');
const $loginBtn    = document.getElementById('login-btn');

// Dashboard – auth card
const $authCard     = document.getElementById('auth-request-card');
const $noReqCard    = document.getElementById('no-request-card');
const $arcMessage   = document.getElementById('arc-message');
const $arcTime      = document.getElementById('arc-time');
const $arcId        = document.getElementById('arc-id');
const $approveBtn   = document.getElementById('dash-approve-btn');
const $denyBtn      = document.getElementById('dash-deny-btn');
const $dashGreeting = document.getElementById('dash-user-greeting');
const $dashLogout   = document.getElementById('dash-logout-btn');

// Home
const $homeGreeting  = document.getElementById('home-user-greeting');
const $homeLogout    = document.getElementById('home-logout-btn');
const $successBanner = document.getElementById('success-banner');
const $closeSuccess  = document.getElementById('close-success');

/* ══════════════════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════════════════ */
function showPage(name) {
  [$loginPage, $dashboardPage, $homePage].forEach(p => p.classList.remove('active'));
  const map = { login: $loginPage, dashboard: $dashboardPage, home: $homePage };
  map[name].classList.add('active');
  appState.page = name;
}

function formatName(email) {
  return email.split('@')[0].replace(/[._-]/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function setLoginLoading(on) {
  $loginBtn.disabled = on;
  $loginBtn.querySelector('.btn-label').textContent = on ? 'Signing in…' : 'Sign In';
  $loginBtn.querySelector('.btn-spinner').classList.toggle('hidden', !on);
}

/* ══════════════════════════════════════════════════════════════════
   POLLING  — GET /api/auth/state every 2 s
══════════════════════════════════════════════════════════════════ */
function startPolling() {
  if (appState.pollTimer) return;
  appState.pollTimer = setInterval(pollAuthState, CONFIG.pollMs);
  pollAuthState(); // immediate first check
}

function stopPolling() {
  clearInterval(appState.pollTimer);
  appState.pollTimer = null;
}

async function pollAuthState() {
  try {
    const res  = await fetch(CONFIG.stateEndpoint);
    const data = await res.json();

    appState.authPending = data.pending;
    appState.requestId   = data.request_id;
    appState.triggeredAt = data.triggered_at;

    // ── On login page: show/hide slim notification ────────────────
    if (appState.page === 'login') {
      if (data.pending) {
        $loginNotif.classList.remove('hidden');
        $loginPage.classList.add('has-notif');
      } else {
        $loginNotif.classList.add('hidden');
        $loginPage.classList.remove('has-notif');
      }
    }

    // ── On dashboard: refresh auth card ──────────────────────────
    if (appState.page === 'dashboard') {
      renderDashboardAuthCard(data);
    }

  } catch (err) {
    // Server unreachable — silently skip (handles plain file:// mode gracefully)
    console.warn('[poll] Could not reach state endpoint:', err.message);
  }
}

/* ══════════════════════════════════════════════════════════════════
   DASHBOARD AUTH CARD
══════════════════════════════════════════════════════════════════ */
function renderDashboardAuthCard(data) {
  if (data.pending) {
    $authCard.classList.remove('hidden');
    $noReqCard.classList.add('hidden');

    $arcMessage.textContent = data.message || 'IVA is requesting your authentication approval.';
    $arcTime.textContent    = formatTime(data.triggered_at);
    $arcId.textContent      = `#${data.request_id}`;
  } else {
    $authCard.classList.add('hidden');
    $noReqCard.classList.remove('hidden');
  }
}

/* ══════════════════════════════════════════════════════════════════
   LOGIN
══════════════════════════════════════════════════════════════════ */
$loginForm.addEventListener('submit', async e => {
  e.preventDefault();

  const email    = $emailInput.value.trim();
  const password = $passInput.value.trim();

  if (!email || !password) {
    $loginError.classList.remove('hidden');
    return;
  }
  $loginError.classList.add('hidden');
  setLoginLoading(true);

  // Simulate auth (replace with real auth call when ready)
  await new Promise(r => setTimeout(r, 900));

  appState.userEmail = email;
  setLoginLoading(false);

  // Navigate to dashboard
  const name = formatName(email);
  $dashGreeting.textContent = `Welcome, ${name}`;
  $homeGreeting.textContent = `Welcome, ${name}`;

  showPage('dashboard');

  // Force-refresh dashboard auth card immediately after landing
  await pollAuthState();

  // Show notification enable banner if permission not yet granted
  refreshNotifBanner();

  // Wire up the enable button (safe to call multiple times)
  const $enableBtn = document.getElementById('notif-enable-btn');
  if ($enableBtn) {
    $enableBtn.onclick = enableNotifications;
  }
});

/* ══════════════════════════════════════════════════════════════════
   APPROVE
══════════════════════════════════════════════════════════════════ */
$approveBtn.addEventListener('click', async () => {
  $approveBtn.disabled = true;
  $denyBtn.disabled    = true;
  $approveBtn.textContent = 'Approving…';

  try {
    // POST approve to our server → server fires outbound callback to IVA
    const res  = await fetch(CONFIG.responseEndpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ approved: true, request_id: appState.requestId }),
    });
    const data = await res.json();
    console.log('[approve]', data);
  } catch (err) {
    console.warn('[approve] Response endpoint error:', err.message);
  }

  // Navigate to home / products page
  showPage('home');
  $successBanner.classList.remove('hidden');

  // Auto-dismiss success banner after 7 s
  const t = setTimeout(dismissSuccess, 7000);
  $closeSuccess.addEventListener('click', () => { clearTimeout(t); dismissSuccess(); }, { once: true });
});

/* ══════════════════════════════════════════════════════════════════
   DENY
══════════════════════════════════════════════════════════════════ */
$denyBtn.addEventListener('click', async () => {
  $approveBtn.disabled = true;
  $denyBtn.disabled    = true;
  $denyBtn.textContent = 'Denying…';

  try {
    const res  = await fetch(CONFIG.responseEndpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ approved: false, request_id: appState.requestId }),
    });
    const data = await res.json();
    console.log('[deny]', data);
  } catch (err) {
    console.warn('[deny] Response endpoint error:', err.message);
  }

  // Update card to reflect denial without leaving dashboard
  $authCard.classList.add('hidden');
  $noReqCard.classList.remove('hidden');
  $noReqCard.innerHTML = `
    <span class="no-req-icon">🚫</span>
    <p style="font-weight:700;color:var(--danger)">Request Denied</p>
    <p class="no-req-sub">The authentication request from IVA has been denied and the result forwarded.</p>
    <button id="reset-dash" class="btn-primary" style="max-width:200px;margin:16px auto 0">
      Back to Dashboard
    </button>
  `;
  document.getElementById('reset-dash').addEventListener('click', () => {
    $noReqCard.innerHTML = `
      <span class="no-req-icon">🔔</span>
      <p>No pending authentication requests.</p>
      <p class="no-req-sub">Waiting for an incoming request from IVA…</p>
    `;
  });
});

/* ══════════════════════════════════════════════════════════════════
   SIGN OUT
══════════════════════════════════════════════════════════════════ */
function signOut() {
  appState.userEmail   = '';
  appState.authPending = false;
  $loginForm.reset();
  $loginError.classList.add('hidden');
  showPage('login');
  pollAuthState(); // refresh notification state on login page
}

$dashLogout.addEventListener('click', signOut);
$homeLogout.addEventListener('click', signOut);

/* ══════════════════════════════════════════════════════════════════
   SUCCESS BANNER
══════════════════════════════════════════════════════════════════ */
function dismissSuccess() {
  $successBanner.style.transition = 'opacity .5s ease';
  $successBanner.style.opacity    = '0';
  setTimeout(() => {
    $successBanner.classList.add('hidden');
    $successBanner.style.opacity    = '';
    $successBanner.style.transition = '';
  }, 500);
}

/* ══════════════════════════════════════════════════════════════════
   ADD-TO-CART  (demo feedback)
══════════════════════════════════════════════════════════════════ */
document.querySelectorAll('.btn-cart').forEach(btn => {
  btn.addEventListener('click', function () {
    const orig = this.textContent;
    this.textContent    = 'Added ✓';
    this.style.background = 'var(--success)';
    setTimeout(() => { this.textContent = orig; this.style.background = ''; }, 1800);
  });
});

/* ══════════════════════════════════════════════════════════════════
   WEB PUSH — permission, subscription, VAPID
══════════════════════════════════════════════════════════════════ */

/** Convert a base64url string to a Uint8Array (needed by pushManager.subscribe) */
function urlB64ToUint8Array(b64url) {
  const pad    = '='.repeat((4 - (b64url.length % 4)) % 4);
  const base64 = (b64url + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw    = atob(base64);
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

/** Fetch the VAPID public key from the server */
async function getVapidPublicKey() {
  const res  = await fetch(CONFIG.vapidPublicKeyEndpoint);
  const data = await res.json();
  return data.publicKey;
}

/** Subscribe this device to Web Push and register it with the server */
async function subscribeToPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.warn('[push] Web Push not supported in this browser.');
    return null;
  }

  const reg = await navigator.serviceWorker.ready;

  // Check if already subscribed
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    const vapidKey = await getVapidPublicKey();
    sub = await reg.pushManager.subscribe({
      userVisibleOnly:      true,
      applicationServerKey: urlB64ToUint8Array(vapidKey),
    });
  }

  // Send subscription to server
  await fetch(CONFIG.pushSubscribeEndpoint, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(sub.toJSON()),
  });

  console.log('[push] Subscribed and registered with server.');
  return sub;
}

/** Request notification permission then subscribe */
async function enableNotifications() {
  const $banner = document.getElementById('notif-enable-banner');
  const $btn    = document.getElementById('notif-enable-btn');

  if ($btn) { $btn.disabled = true; $btn.textContent = 'Enabling…'; }

  const permission = await Notification.requestPermission();

  if (permission === 'granted') {
    await subscribeToPush();
    if ($banner) $banner.classList.add('hidden');
    console.log('[push] Notifications enabled.');
  } else {
    if ($btn) { $btn.disabled = false; $btn.textContent = 'Enable Notifications'; }
    console.warn('[push] Notification permission denied.');
  }
}

/** Show or hide the notification enable banner based on current permission */
async function refreshNotifBanner() {
  const $banner = document.getElementById('notif-enable-banner');
  if (!$banner) return;
  if (!('Notification' in window) || !('PushManager' in window)) {
    $banner.classList.add('hidden');   // browser doesn't support push
    return;
  }

  if (Notification.permission === 'granted') {
    $banner.classList.add('hidden');
    // Make sure we have an active subscription registered
    subscribeToPush().catch(() => {});
  } else if (Notification.permission === 'denied') {
    $banner.classList.add('hidden');   // can't ask again — don't nag
  } else {
    $banner.classList.remove('hidden'); // 'default' → invite the user
  }
}

/* ══════════════════════════════════════════════════════════════════
   BOOT
══════════════════════════════════════════════════════════════════ */
startPolling();
