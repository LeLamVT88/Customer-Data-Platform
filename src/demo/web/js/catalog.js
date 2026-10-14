/**
 * src/demo/web/js/catalog.js — Product catalog data and utilities.
 * Loaded once; all pages share the same in-memory data.
 */

const API_BASE = 'http://127.0.0.1:8000';

let _catalog = null;
let _cart = [];

/** Load catalog from API or fallback to local JSON */
export async function loadCatalog() {
  if (_catalog) return _catalog;
  try {
    const res = await fetch(`${API_BASE}/api/catalog`);
    if (res.ok) {
      _catalog = await res.json();
      return _catalog;
    }
  } catch (_) { /* fall through */ }
  // Fallback: load directly from local file (works even if API is down)
  const res = await fetch('../config/demo/catalog.products.json');
  _catalog = await res.json();
  return _catalog;
}

/** Get a product by ID */
export function getProduct(id) {
  return (_catalog || []).find(p => p.product_id === id);
}

/** Get all products, optionally filtered by a category */
export function getProducts(category = null) {
  if (!category) return _catalog || [];
  return (_catalog || []).filter(p => p.category_id.startsWith(category));
}

/** Get unique top-level categories from catalog */
export function getCategories() {
  if (!_catalog) return [];
  const cats = new Map();
  for (const p of _catalog) {
    const top = p.category_id.split('.')[0];
    if (!cats.has(top)) cats.set(top, top);
  }
  return [...cats.keys()];
}

/** Cart helpers (in-memory) */
export function getCart() { return [..._cart]; }

export function addToCart(product, qty = 1) {
  const existing = _cart.find(i => i.product_id === product.product_id);
  if (existing) {
    existing.quantity += qty;
  } else {
    _cart.push({ ...product, quantity: qty });
  }
  saveCart();
}

export function removeFromCart(productId) {
  _cart = _cart.filter(i => i.product_id !== productId);
  saveCart();
}

export function clearCart() {
  _cart = [];
  saveCart();
}

export function cartTotal() {
  return _cart.reduce((sum, item) => sum + parseFloat(item.price) * item.quantity, 0);
}

export function cartCount() {
  return _cart.reduce((sum, item) => sum + item.quantity, 0);
}

function saveCart() {
  try { localStorage.setItem('cdp_demo_cart', JSON.stringify(_cart)); } catch (_) {}
}

export function loadCart() {
  try {
    const saved = localStorage.getItem('cdp_demo_cart');
    if (saved) _cart = JSON.parse(saved);
  } catch (_) { _cart = []; }
}

/** User identity helpers */
function getOrCreateUserId() {
  const COOKIE_NAME = 'cdp_demo_uid';
  try {
    const existing = document.cookie.split('; ').find(r => r.startsWith(COOKIE_NAME + '='));
    if (existing) return existing.split('=')[1];
    const uid = 'u_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    // Store for 90 days
    const exp = new Date(Date.now() + 90 * 864e5).toUTCString();
    document.cookie = `${COOKIE_NAME}=${uid}; expires=${exp}; path=/; SameSite=Lax`;
    return uid;
  } catch (_) {
    return 'uid_' + Math.random().toString(36).slice(2);
  }
}

let _sessionId = null;
export function getSessionId() {
  if (!_sessionId) _sessionId = crypto.randomUUID();
  return _sessionId;
}

export function getUserId() {
  try { return getOrCreateUserId(); } catch (_) { return 'uid_fallback'; }
}

/** Event tracking — collect and flush to API */
const _eventQueue = [];
let _flushTimer = null;
let _batchId = crypto.randomUUID();

const SUPPORTED_EVENT_TYPES = new Set([
  'page_view', 'product_view', 'add_to_cart', 'remove_from_cart',
  'begin_checkout', 'purchase_observed', 'element_click',
  'scroll_depth', 'search', 'error',
]);

export function track(eventType, payload = {}) {
  if (!SUPPORTED_EVENT_TYPES.has(eventType)) return;
  const event = {
    event_type: eventType,
    event_time: new Date().toISOString(),
    session_id: getSessionId(),
    user_id: getUserId(),
    namespace: 'cdp.demo.events',
    source: 'web-demo',
    url: location.href,
    referrer: document.referrer || '',
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    payload,
    // client-side batch_id so events can be grouped before flush
    _client_batch_id: _batchId,
  };
  _eventQueue.push(event);
  scheduleFlush();
}

function scheduleFlush() {
  if (_flushTimer) return;
  _flushTimer = setTimeout(flushEvents, 5000);
}

export async function flushEvents() {
  if (_flushTimer) { clearTimeout(_flushTimer); _flushTimer = null; }
  if (_eventQueue.length === 0) return;
  const batch = [..._eventQueue];
  _eventQueue.length = 0;
  try {
    const res = await fetch(`${API_BASE}/api/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(batch),
      keepalive: true,
    });
    if (!res.ok) throw new Error(`API ${res.status}`);
    const result = await res.json();
    showStatus(`Flushed ${batch.length} event(s) — batch ${result.batch_id.slice(0, 8)}…`);
    // Start a new batch
    _batchId = crypto.randomUUID();
    return result;
  } catch (e) {
    // Re-queue on failure (best-effort)
    _eventQueue.unshift(...batch);
    showStatus(`Event flush failed: ${e.message} — will retry`, true);
  }
}

/** Flush on page unload */
window.addEventListener('beforeunload', () => {
  if (_eventQueue.length > 0) {
    navigator.sendBeacon(
      `${API_BASE}/api/events`,
      JSON.stringify([..._eventQueue])
    );
  }
});

/** Page navigation via hash routing */
export function navigate(hash) {
  location.hash = hash;
}

export function onRoute(callback) {
  window.addEventListener('hashchange', callback);
  callback();
}

/** Toast / status bar */
export function showStatus(msg, isError = false) {
  const bar = document.getElementById('status-bar') || createStatusBar();
  bar.textContent = msg;
  bar.style.background = isError ? '#dc3545' : '#212529';
  bar.classList.add('show');
  setTimeout(() => bar.classList.remove('show'), 3500);
}

function createStatusBar() {
  const bar = document.createElement('div');
  bar.id = 'status-bar';
  document.body.appendChild(bar);
  return bar;
}

/** Render a product card HTML string */
export function renderProductCard(product) {
  return `
    <div class="product-card" data-id="${product.product_id}">
      <img src="${product.image_url}" alt="${product.brand} ${product.product_id}" loading="lazy" onerror="this.src='https://via.placeholder.com/300x180.png?text=No+Image'">
      <div class="product-card-body">
        <div class="product-card-brand">${product.brand}</div>
        <div class="product-card-name">${product.product_id}</div>
        <div class="product-card-price">$${parseFloat(product.price).toFixed(2)}</div>
      </div>
    </div>`;
}

/** Render a full catalog page */
export async function renderCatalogPage(containerId) {
  await loadCatalog();
  const container = document.getElementById(containerId);
  if (!container) return;

  const categoryFilter = document.createElement('div');
  categoryFilter.className = 'form-group';
  categoryFilter.style.marginBottom = '1rem';
  const cats = getCategories();
  categoryFilter.innerHTML = `
    <label for="cat-filter">Filter by category</label>
    <select id="cat-filter">
      <option value="">All categories</option>
      ${cats.map(c => `<option value="${c}">${c}</option>`).join('')}
    </select>`;
  container.prepend(categoryFilter);

  const grid = document.createElement('div');
  grid.className = 'card-grid';
  container.appendChild(grid);

  function renderGrid(filter = '') {
    const products = filter ? getProducts(filter) : (_catalog || []);
    grid.innerHTML = products.map(renderProductCard).join('');
    grid.querySelectorAll('.product-card').forEach(card => {
      card.addEventListener('click', () => {
        track('product_view', { product_id: card.dataset.id });
        navigate(`#product?id=${card.dataset.id}`);
      });
    });
  }

  document.getElementById('cat-filter').addEventListener('change', e => renderGrid(e.target.value));
  renderGrid();
}

/** Render a product detail page */
export async function renderProductPage(containerId) {
  await loadCatalog();
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const id = params.get('id');
  const product = id ? getProduct(id) : null;
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!product) {
    container.innerHTML = '<div class="empty-state"><p>Product not found.</p><a href="#catalog" class="btn btn-primary">Back to Catalog</a></div>';
    return;
  }

  container.innerHTML = `
    <div class="card" style="max-width:600px;margin:0 auto">
      <a href="#catalog" class="btn btn-sm" style="margin-bottom:1rem">← Back</a>
      <img src="${product.image_url}" alt="${product.brand}" style="width:100%;max-height:360px;object-fit:contain;border-radius:var(--radius)" onerror="this.src='https://via.placeholder.com/600x360.png?text=No+Image'">
      <h2 style="margin:.75rem 0 .25rem">${product.brand} ${product.product_id}</h2>
      <p style="color:var(--muted);font-size:.85rem">${product.category_id} &middot; ${product.category_code}</p>
      <p style="font-size:1.5rem;font-weight:700;color:var(--primary);margin:.75rem 0">
        $${parseFloat(product.price).toFixed(2)} ${product.currency}
      </p>
      <button id="btn-add-cart" class="btn btn-primary">Add to Cart</button>
    </div>`;

  document.getElementById('btn-add-cart').addEventListener('click', () => {
    addToCart(product, 1);
    track('add_to_cart', { product_id: product.product_id, quantity: 1, price: product.price, currency: product.currency });
    showStatus(`Added ${product.product_id} to cart`);
    updateNavCartBadge();
  });
}

/** Render the cart page */
export function renderCartPage(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const items = getCart();

  if (items.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.3 4.6A1 1 0 006 18h12a1 1 0 00.97-.76L17 13"/>
        </svg>
        <p>Your cart is empty.</p>
        <a href="#catalog" class="btn btn-primary">Browse Catalog</a>
      </div>`;
    return;
  }

  const total = cartTotal().toFixed(2);
  container.innerHTML = `
    <h2>Shopping Cart</h2>
    <div class="card" style="margin-top:1rem">
      <table class="cart-table">
        <thead><tr>
          <th>Product</th><th>Price</th><th>Qty</th><th>Subtotal</th><th></th>
        </tr></thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td><strong>${item.product_id}</strong><br><small>${item.brand}</small></td>
              <td>$${parseFloat(item.price).toFixed(2)}</td>
              <td>${item.quantity}</td>
              <td>$${(parseFloat(item.price) * item.quantity).toFixed(2)}</td>
              <td>
                <button class="btn btn-danger btn-sm btn-remove" data-id="${item.product_id}">Remove</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="cart-total">Total: $${total} USD</div>
      <div style="margin-top:1rem;display:flex;gap:.5rem">
        <button id="btn-clear-cart" class="btn btn-danger">Clear Cart</button>
        <a href="#checkout" class="btn btn-primary">Proceed to Checkout</a>
      </div>
    </div>`;

  container.querySelectorAll('.btn-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      removeFromCart(btn.dataset.id);
      track('remove_from_cart', { product_id: btn.dataset.id });
      renderCartPage(containerId);
      updateNavCartBadge();
    });
  });

  document.getElementById('btn-clear-cart').addEventListener('click', () => {
    track('element_click', { selector: '#btn-clear-cart', tag: 'button' });
    clearCart();
    renderCartPage(containerId);
    updateNavCartBadge();
  });
}

/** Render the checkout page */
export function renderCheckoutPage(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const items = getCart();
  const total = cartTotal().toFixed(2);

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>Nothing to checkout.</p><a href="#catalog" class="btn btn-primary">Go to Catalog</a></div>';
    return;
  }

  container.innerHTML = `
    <h2>Checkout</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem">
      <div class="card">
        <h3 style="margin-bottom:.75rem">Order Summary</h3>
        ${items.map(item => `
          <div style="display:flex;justify-content:space-between;padding:.375rem 0;border-bottom:1px solid var(--border)">
            <span>${item.product_id} &times;${item.quantity}</span>
            <strong>$${(parseFloat(item.price) * item.quantity).toFixed(2)}</strong>
          </div>`).join('')}
        <div style="margin-top:.75rem;font-size:1.1rem;font-weight:700;text-align:right">
          Total: $${total} USD
        </div>
      </div>
      <div class="card">
        <h3 style="margin-bottom:.75rem">Payment</h3>
        <div class="form-group">
          <label>Card Number</label>
          <input type="text" placeholder="4242 4242 4242 4242" maxlength="19" id="card-number">
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
          <div class="form-group">
            <label>Expiry</label>
            <input type="text" placeholder="MM/YY" maxlength="5" id="card-expiry">
          </div>
          <div class="form-group">
            <label>CVV</label>
            <input type="text" placeholder="123" maxlength="4" id="card-cvv">
          </div>
        </div>
        <div class="form-group">
          <label>Name on Card</label>
          <input type="text" placeholder="Demo User" id="card-name">
        </div>
        <button id="btn-place-order" class="btn btn-primary" style="width:100%;margin-top:.5rem">Place Order</button>
        <p id="checkout-error" style="color:var(--danger);font-size:.85rem;margin-top:.5rem;display:none"></p>
      </div>
    </div>`;

  // Card number formatting
  document.getElementById('card-number').addEventListener('input', e => {
    e.target.value = e.target.value.replace(/\D/g, '').replace(/(.{4})/g, '$1 ').trim();
  });

  document.getElementById('btn-place-order').addEventListener('click', async () => {
    const btn = document.getElementById('btn-place-order');
    btn.disabled = true;
    btn.textContent = 'Processing…';

    track('begin_checkout', {
      cart_id: crypto.randomUUID(),
      items: items.map(i => ({ product_id: i.product_id, quantity: i.quantity, price: i.price, currency: i.currency })),
      total_price: total,
      currency: 'USD',
    });

    // Simulate payment processing delay
    await new Promise(r => setTimeout(r, 800));

    const orderId = 'ORD-' + Math.random().toString(36).slice(2, 9).toUpperCase();

    track('purchase_observed', {
      cart_id: orderId,
      items: items.map(i => ({ product_id: i.product_id, quantity: i.quantity, price: i.price, currency: i.currency })),
      total_price: total,
      currency: 'USD',
    });

    // Show confirmation
    container.innerHTML = `
      <div class="card" style="text-align:center;max-width:500px;margin:2rem auto">
        <div style="font-size:3rem;margin-bottom:.5rem">✅</div>
        <h2 style="color:var(--success)">Order Confirmed!</h2>
        <p style="color:var(--muted);margin:.5rem 0">Order ID: <strong>${orderId}</strong></p>
        <p>Total charged: <strong>$${total} USD</strong></p>
        <a href="#dashboard" class="btn btn-primary" style="margin-top:1.5rem">View Dashboard</a>
      </div>`;

    clearCart();
    updateNavCartBadge();
    await flushEvents();
  });
}

/** Update cart badge in nav */
export function updateNavCartBadge() {
  const badge = document.getElementById('cart-badge');
  if (!badge) return;
  const count = cartCount();
  badge.textContent = count || '';
  badge.style.display = count > 0 ? 'inline' : 'none';
}
