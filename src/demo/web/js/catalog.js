/**
 * src/demo/web/js/catalog.js — Product catalog data and utilities.
 * Loaded once; all pages share the same in-memory data.
 *
 * User flows:
 *   Lina (Window Shopper)  → page_view → product_view × N → browse depth signal
 *   Minh (Decisive Buyer)  → product_view → add_to_cart → checkout → purchase
 *   Hoa (Researcher)       → search → product_view × N → specs, no purchase
 *   Quang (Cart Abandoner) → add_to_cart × N → cart → abandon
 *
 * Event tracking is delegated to js/tracker.js (Snowplow Browser Tracker).
 */

import { track, trackProduct, flushEvents, getUserId, getSessionId } from './tracker.js';
import { getRunId } from './tracker.js';
import { api, refreshCustomer, escapeHTML } from './account.js';

const API_BASE = `http://${location.hostname}:8000`;

let _catalog = null;
let _cart = [];
let _recentlyViewed = [];      // [{product_id, brand, price, image_url, category_id}]
let _lastBrowsedCategory = null;

/** Maximum recently-viewed products to keep in localStorage */
const MAX_RECENT = 8;

// ── Catalog loading ─────────────────────────────────────────────────────────

/** Load catalog from API or fallback to local JSON. */
export async function loadCatalog() {
  if (_catalog) return _catalog;
  try {
    const res = await fetch(`${API_BASE}/api/catalog`);
    if (res.ok) { _catalog = await res.json(); return _catalog; }
  } catch (_) {}
  try {
    const res = await fetch('../../config/demo/catalog.products.json');
    if (res.ok) { _catalog = await res.json(); return _catalog; }
    throw new Error(`fallback HTTP ${res.status}`);
  } catch (e) {
    _catalog = [];
    throw new Error(`Cannot load catalog (API down, local file missing): ${e.message}`);
  }
}

export function getProduct(id) {
  return (_catalog || []).find(p => p.product_id === id);
}

export function getProducts(category = null) {
  if (!category) return _catalog || [];
  return (_catalog || []).filter(p => p.category_id.startsWith(category));
}

export function getCategories() {
  if (!_catalog) return [];
  const cats = new Map();
  for (const p of _catalog) {
    const top = p.category_id.split('.')[0];
    if (!cats.has(top)) cats.set(top, top);
  }
  return [...cats.keys()];
}

// ── Recently Viewed ─────────────────────────────────────────────────────────

export function addToRecentlyViewed(product) {
  const existing = _recentlyViewed.findIndex(p => p.product_id === product.product_id);
  if (existing !== -1) _recentlyViewed.splice(existing, 1);
  _recentlyViewed.unshift({
    product_id: product.product_id,
    brand: product.brand,
    price: product.price,
    image_url: product.image_url,
    category_id: product.category_id,
  });
  if (_recentlyViewed.length > MAX_RECENT) _recentlyViewed.pop();
  try {
    localStorage.setItem('cdp_demo_recent', JSON.stringify(_recentlyViewed));
  } catch (_) {}
  _lastBrowsedCategory = product.category_id.split('.')[0];
  try {
    localStorage.setItem('cdp_demo_last_cat', _lastBrowsedCategory);
  } catch (_) {}
}

export function getRecentlyViewed() {
  if (_recentlyViewed.length > 0) return _recentlyViewed;
  try {
    const saved = localStorage.getItem('cdp_demo_recent');
    if (saved) _recentlyViewed = JSON.parse(saved);
  } catch (_) {}
  return _recentlyViewed;
}

export function getLastBrowsedCategory() {
  if (_lastBrowsedCategory) return _lastBrowsedCategory;
  try {
    _lastBrowsedCategory = localStorage.getItem('cdp_demo_last_cat') || null;
  } catch (_) {}
  return _lastBrowsedCategory;
}

/** Products "you might also like" — same category, not recently viewed */
export function getRecommendations(n = 4) {
  const recentIds = new Set(_recentlyViewed.map(p => p.product_id));
  const cat = getLastBrowsedCategory();
  const candidates = (_catalog || []).filter(p => {
    if (recentIds.has(p.product_id)) return false;
    if (cat) return p.category_id.startsWith(cat);
    return true;
  });
  // Shuffle and pick top n
  for (let i = candidates.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
  }
  return candidates.slice(0, n);
}

// ── Cart ───────────────────────────────────────────────────────────────────

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

// ── Event tracking ─────────────────────────────────────────────────────────
// Tracking do Snowplow Browser Tracker đảm nhiệm (xem js/tracker.js).
// Các hàm track/trackProduct/flushEvents được re-export để các module khác
// (index.html, dashboard.js) dùng chung một đường đi event.
export { track, trackProduct, flushEvents, getUserId, getSessionId };

// Cart-abandoned flag — fire only once per session
let _cartAbandonedFired = false;

window.addEventListener('beforeunload', () => {
  // Fire cart_abandoned if cart has items and hasn't been fired this session
  if (getCart().length > 0 && !_cartAbandonedFired) {
    _cartAbandonedFired = true;
    // Iglu schema cart_abandoned yêu cầu currency trong từng item.
    const cartItems = getCart().map(i => ({
      product_id: i.product_id,
      quantity: i.quantity,
      price: i.price,
      currency: i.currency || 'USD',
    }));
    track('cart_abandoned', { items: cartItems, total_price: cartTotal().toFixed(2), currency: 'USD' });
  }
  // Đẩy nốt event còn trong buffer của Snowplow.
  flushEvents();
});

// ── Navigation ───────────────────────────────────────────────────────────────

export function navigate(hash) { location.hash = hash; }

export function onRoute(callback) {
  window.addEventListener('hashchange', callback);
  callback();
}

// ── Toast / status bar ──────────────────────────────────────────────────────

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

// ── Update cart badge ────────────────────────────────────────────────────────

export function updateNavCartBadge() {
  const badge = document.getElementById('cart-badge');
  if (!badge) return;
  const count = cartCount();
  badge.textContent = count || '';
  badge.style.display = count > 0 ? 'inline' : 'none';
}

// ── Product card renderer ────────────────────────────────────────────────────

export function renderProductCard(product, options = {}) {
  const { showQuickAdd = false } = options;
  return `
    <div class="product-card" data-id="${product.product_id}">
      <img src="${product.image_url}" alt="${product.brand} ${product.product_id}" loading="lazy" onerror="this.src='https://via.placeholder.com/300x180.png?text=No+Image'">
      <div class="product-card-body">
        <div class="product-card-brand">${product.brand}</div>
        <div class="product-card-name">${product.product_id}</div>
        <div class="product-card-price">$${parseFloat(product.price).toFixed(2)}</div>
        ${showQuickAdd ? `
        <button class="btn btn-primary btn-sm btn-quick-add" data-id="${product.product_id}" style="margin-top:.5rem;width:100%">
          Thêm vào giỏ hàng
        </button>` : ''}
      </div>
    </div>`;
}

// ── Render: Home page ────────────────────────────────────────────────────────

export function renderHomePage(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const recent = getRecentlyViewed();
  const recs = getRecommendations(4);

  container.innerHTML = `
    <div class="card" style="text-align:center;padding:2rem 1rem">
      <h1 style="margin-bottom:.5rem">Chào mừng đến CDP Demo Store</h1>
      <p style="color:var(--muted);margin-bottom:1.5rem">
        Cửa hàng thử nghiệm tổng hợp hành vi người dùng thành các sự kiện có kiểu
        cho pipeline Customer Data Platform.
      </p>
      <div style="display:flex;gap:.75rem;justify-content:center;flex-wrap:wrap">
        <a href="#catalog" class="btn btn-primary">Duyệt danh mục</a>
        <a href="#dashboard" class="btn">Xem Dashboard</a>
      </div>
    </div>

    ${recent.length > 0 ? `
    <div class="card" style="margin-top:1.5rem">
      <h3 class="section-title">📋 Đã xem gần đây</h3>
      <div class="card-grid" id="recent-grid"></div>
    </div>` : ''}

    ${recs.length > 0 ? `
    <div class="card" style="margin-top:1.5rem">
      <h3 class="section-title">💡 Có thể bạn cũng thích</h3>
      <div class="card-grid" id="recs-grid"></div>
    </div>` : ''}

    <div class="card" style="margin-top:1.5rem">
      <h3 class="section-title">🔍 Đăng ký nhận tin</h3>
      <p style="font-size:.85rem;color:var(--muted);margin-bottom:.75rem">
        Nhận thông tin khuyến mãi và cập nhật sản phẩm mới qua email.
      </p>
      <form id="newsletter-form" class="newsletter-form">
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <input type="email" id="newsletter-email" placeholder="email@example.com" required style="flex:1;min-width:200px">
          <button type="submit" class="btn btn-primary">Đăng ký</button>
        </div>
        <p id="newsletter-msg" style="font-size:.8rem;margin-top:.5rem;color:var(--success);display:none">
          Cảm ơn bạn! Đăng ký thành công.
        </p>
      </form>
    </div>

    <div class="card" style="margin-top:1.5rem;background:#f0f4ff;border-color:#c0d0ff">
      <strong style="color:var(--primary)">🤖 Bot Driver Có sẵn</strong>
      <p style="font-size:.8rem;color:var(--muted);margin:.25rem 0 .75rem">
        Chạy <code>python -m src.demo.bot.driver --users 5</code> để mô phỏng người dùng
        và quan sát dashboard cập nhật real-time.
      </p>
      <a href="#dashboard" class="btn btn-primary btn-sm">Mở Dashboard</a>
    </div>

    <div style="margin-top:1.5rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem">
      <div class="card">
        <strong>📦 Duyệt sản phẩm</strong>
        <p style="font-size:.8rem;color:var(--muted);margin-top:.25rem">Khám phá 250 sản phẩm qua 19 danh mục.</p>
      </div>
      <div class="card">
        <strong>🔍 Tìm kiếm</strong>
        <p style="font-size:.8rem;color:var(--muted);margin-top:.25rem">Tìm sản phẩm bằng thanh tìm kiếm.</p>
      </div>
      <div class="card">
        <strong>🛒 Thêm vào giỏ</strong>
        <p style="font-size:.8rem;color:var(--muted);margin-top:.25rem">Thêm sản phẩm và tiến hành thanh toán.</p>
      </div>
      <div class="card">
        <strong>📊 Dashboard</strong>
        <p style="font-size:.8rem;color:var(--muted);margin-top:.25rem">Xem dòng sự kiện vào CDP pipeline.</p>
      </div>
    </div>`;

  // Newsletter handler
  document.getElementById('newsletter-form').addEventListener('submit', e => {
    e.preventDefault();
    const email = document.getElementById('newsletter-email').value.trim();
    if (email) {
      track('newsletter_signup', { email });
      document.getElementById('newsletter-email').value = '';
      document.getElementById('newsletter-msg').style.display = 'block';
      flushEvents();
    }
  });

  // Recently viewed grid
  if (recent.length > 0) {
    const recentGrid = document.getElementById('recent-grid');
    if (recentGrid) {
      recentGrid.innerHTML = recent.map(p => renderProductCard(p)).join('');
      recentGrid.querySelectorAll('.product-card').forEach(card => {
        card.addEventListener('click', () => {
          navigate(`#product?id=${card.dataset.id}&source=recently_viewed`);
        });
      });
    }
  }

  // Recommendations grid
  if (recs.length > 0) {
    const recsGrid = document.getElementById('recs-grid');
    if (recsGrid) {
      recsGrid.innerHTML = recs.map(p => renderProductCard(p)).join('');
      recsGrid.querySelectorAll('.product-card').forEach(card => {
        card.addEventListener('click', () => {
          navigate(`#product?id=${card.dataset.id}&source=recommendation`);
        });
      });
    }
  }
}

// ── Render: Catalog page ────────────────────────────────────────────────────

export async function renderCatalogPage(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '<h2>Danh mục sản phẩm</h2>';

  try {
    await loadCatalog();
  } catch (e) {
    container.innerHTML = `
      <h2>Danh mục sản phẩm</h2>
      <div class="empty-state" style="color:var(--danger)">
        <p>Tải danh mục thất bại.</p>
        <p style="font-size:.8rem">${e.message}</p>
        <p style="font-size:.8rem">Hãy chắc chắn Demo API đang chạy: <code>python -m src.demo.api.server</code></p>
      </div>`;
    return;
  }
  if (!_catalog || _catalog.length === 0) {
    container.innerHTML = '<h2>Danh mục sản phẩm</h2><div class="empty-state"><p>Không có sản phẩm.</p></div>';
    return;
  }

  // Search bar
  const searchBar = document.createElement('div');
  searchBar.className = 'catalog-toolbar';
  searchBar.innerHTML = `
    <input type="search" id="catalog-search" placeholder="🔍 Tìm kiếm sản phẩm…"
           autocomplete="off" style="flex:1">
    <select id="sort-select" title="Sắp xếp">
      <option value="">Mặc định</option>
      <option value="price_asc">Giá: Thấp → Cao</option>
      <option value="price_desc">Giá: Cao → Thấp</option>
      <option value="name_asc">Tên: A → Z</option>
    </select>
    <select id="cat-filter">
      <option value="">Tất cả danh mục</option>
      ${getCategories().map(c => `<option value="${c}">${c}</option>`).join('')}
    </select>`;
  container.appendChild(searchBar);

  const grid = document.createElement('div');
  grid.className = 'card-grid';
  container.appendChild(grid);

  let currentFilter = '';
  let currentSort = '';
  let currentQuery = '';

  function renderGrid(filter = '', sort = '', query = '') {
    let products = filter ? getProducts(filter) : (_catalog || []);
    if (query) {
      const q = query.toLowerCase();
      products = products.filter(p =>
        p.product_id.toLowerCase().includes(q) ||
        p.brand.toLowerCase().includes(q) ||
        p.category_id.toLowerCase().includes(q)
      );
    }
    if (sort === 'price_asc') products = [...products].sort((a, b) => parseFloat(a.price) - parseFloat(b.price));
    if (sort === 'price_desc') products = [...products].sort((a, b) => parseFloat(b.price) - parseFloat(a.price));
    if (sort === 'name_asc') products = [...products].sort((a, b) => a.brand.localeCompare(b.brand));

    grid.innerHTML = products.map(p => renderProductCard(p, { showQuickAdd: true })).join('');

    grid.querySelectorAll('.product-card').forEach(card => {
      card.addEventListener('click', e => {
        // Don't navigate if clicking quick-add button
        if (e.target.classList.contains('btn-quick-add')) return;
        navigate(`#product?id=${card.dataset.id}&source=catalog`);
      });
    });

    grid.querySelectorAll('.btn-quick-add').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const product = getProduct(btn.dataset.id);
        if (!product) return;
        addToCart(product, 1);
        trackProduct('add_to_cart', { product_id: product.product_id, quantity: 1, price: product.price, currency: product.currency }, product);
        showStatus(`Đã thêm ${product.product_id} vào giỏ hàng`);
        updateNavCartBadge();
        // Brief highlight
        btn.textContent = '✓ Đã thêm';
        btn.disabled = true;
        setTimeout(() => { btn.textContent = 'Thêm vào giỏ hàng'; btn.disabled = false; }, 1500);
      });
    });

    if (products.length === 0) {
      grid.innerHTML = '<div class="empty-state"><p>Không tìm thấy sản phẩm phù hợp.</p></div>';
    }
  }

  document.getElementById('catalog-search').addEventListener('input', e => {
    currentQuery = e.target.value.trim();
    track('search', { query: currentQuery, results_count: (_catalog || []).filter(p =>
      p.product_id.toLowerCase().includes(currentQuery.toLowerCase()) ||
      p.brand.toLowerCase().includes(currentQuery.toLowerCase())
    ).length, type: 'catalog_search' });
    renderGrid(currentFilter, currentSort, currentQuery);
  });

  document.getElementById('cat-filter').addEventListener('change', e => {
    currentFilter = e.target.value;
    if (currentFilter) track('apply_filter', { filter_type: 'category', filter_value: currentFilter });
    renderGrid(currentFilter, currentSort, currentQuery);
  });

  document.getElementById('sort-select').addEventListener('change', e => {
    currentSort = e.target.value;
    if (currentSort) track('element_click', { selector: '#sort-select', tag: 'select', sort: currentSort });
    renderGrid(currentFilter, currentSort, currentQuery);
  });

  renderGrid();
}

// ── Render: Product detail page ─────────────────────────────────────────────

export async function renderProductPage(containerId) {
  await loadCatalog();
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const id = params.get('id');
  const product = id ? getProduct(id) : null;
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!product) {
    container.innerHTML = '<div class="empty-state"><p>Không tìm thấy sản phẩm.</p><a href="#catalog" class="btn btn-primary"> Quay lại danh mục</a></div>';
    return;
  }

  trackProduct('product_view', {
    product_id: product.product_id, category_id: product.category_id,
    source: params.get('source') || 'direct',
  }, product);
  addToRecentlyViewed(product);

  container.innerHTML = `
    <div class="card" style="max-width:600px;margin:0 auto">
      <a href="#catalog" class="btn btn-sm" style="margin-bottom:1rem">← Quay lại</a>
      <img src="${product.image_url}" alt="${product.brand}" style="width:100%;max-height:360px;object-fit:contain;border-radius:var(--radius)" onerror="this.src='https://via.placeholder.com/600x360.png?text=No+Image'">
      <h2 style="margin:.75rem 0 .25rem">${product.brand} ${product.product_id}</h2>
      <p style="color:var(--muted);font-size:.85rem">${escapeHTML(product.category_id)}</p>
      <p style="font-size:1.5rem;font-weight:700;color:var(--primary);margin:.75rem 0">
        $${parseFloat(product.price).toFixed(2)} ${product.currency}
      </p>
      <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.75rem">
        <label for="qty-select" style="font-size:.875rem;font-weight:600">Số lượng:</label>
        <select id="qty-select" style="width:auto">
          ${[1,2,3,4,5].map(n => `<option value="${n}">${n}</option>`).join('')}
        </select>
      </div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap">
        <button id="btn-add-cart" class="btn btn-primary">Thêm vào giỏ hàng</button>
        <button id="btn-wishlist" class="btn btn-outline" title="Thêm vào wishlist">
          🤍 Wishlist
        </button>
      </div>
      <p id="wishlist-msg" style="font-size:.8rem;color:var(--success);margin-top:.5rem;display:none">
        Đã thêm vào wishlist!
      </p>
    </div>`;

  let wishlisted = false;

  document.getElementById('btn-add-cart').addEventListener('click', () => {
    const qty = parseInt(document.getElementById('qty-select').value);
    addToCart(product, qty);
    trackProduct('add_to_cart', {
      product_id: product.product_id,
      quantity: qty,
      price: product.price,
      currency: product.currency,
      category_id: product.category_id,
    }, product);
    showStatus(`Đã thêm ${product.product_id} ×${qty} vào giỏ hàng`);
    updateNavCartBadge();
  });

  document.getElementById('btn-wishlist').addEventListener('click', () => {
    wishlisted = !wishlisted;
    const btn = document.getElementById('btn-wishlist');
    const msg = document.getElementById('wishlist-msg');
    if (wishlisted) {
      btn.textContent = '💛 Đã Wishlist';
      msg.textContent = 'Đã thêm vào wishlist!';
      trackProduct('wishlist_add', { product_id: product.product_id, price: product.price, currency: product.currency }, product);
    } else {
      btn.textContent = '🤍 Wishlist';
      msg.textContent = 'Đã xóa khỏi wishlist.';
      trackProduct('wishlist_remove', { product_id: product.product_id }, product);
    }
    msg.style.display = 'block';
    setTimeout(() => { msg.style.display = 'none'; }, 3000);
  });
}

// ── Render: Cart page ────────────────────────────────────────────────────────

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
        <p>Giỏ hàng trống.</p>
        <a href="#catalog" class="btn btn-primary">Duyệt danh mục</a>
      </div>`;
    return;
  }

  const total = cartTotal().toFixed(2);
  container.innerHTML = `
    <h2>Giỏ hàng</h2>
    <div class="card" style="margin-top:1rem">
      <table class="cart-table">
        <thead><tr>
          <th>Sản phẩm</th><th>Giá</th><th>Số lượng</th><th>Tổng phụ</th><th></th>
        </tr></thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td><strong>${item.product_id}</strong><br><small>${item.brand}</small></td>
              <td>$${parseFloat(item.price).toFixed(2)}</td>
              <td>
                <select class="qty-cart-select" data-id="${item.product_id}" style="width:auto">
                  ${[1,2,3,4,5].map(n => `<option value="${n}" ${item.quantity === n ? 'selected' : ''}>${n}</option>`).join('')}
                </select>
              </td>
              <td>$${(parseFloat(item.price) * item.quantity).toFixed(2)}</td>
              <td>
                <button class="btn btn-danger btn-sm btn-remove" data-id="${item.product_id}">Xóa</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="cart-total">Tổng cộng: $${total} USD</div>
      <div style="margin-top:1rem;display:flex;gap:.5rem">
        <button id="btn-clear-cart" class="btn btn-danger">Xóa giỏ hàng</button>
        <a href="#checkout" class="btn btn-primary">Tiến hành thanh toán</a>
      </div>
    </div>`;

  container.querySelectorAll('.btn-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      removeFromCart(btn.dataset.id);
      trackProduct('remove_from_cart', { product_id: btn.dataset.id }, getProduct(btn.dataset.id));
      renderCartPage(containerId);
      updateNavCartBadge();
    });
  });

  container.querySelectorAll('.qty-cart-select').forEach(sel => {
    sel.addEventListener('change', e => {
      const productId = sel.dataset.id;
      const newQty = parseInt(e.target.value);
      const item = items.find(i => i.product_id === productId);
      if (item) {
        item.quantity = newQty;
        saveCart();
        trackProduct('add_to_cart', { product_id: productId, quantity: newQty, price: item.price, currency: item.currency, updated: true }, item);
        renderCartPage(containerId);
        updateNavCartBadge();
      }
    });
  });

  document.getElementById('btn-clear-cart').addEventListener('click', () => {
    track('element_click', { selector: '#btn-clear-cart', tag: 'button' });
    clearCart();
    renderCartPage(containerId);
    updateNavCartBadge();
  });
}

// ── Render: Checkout page ───────────────────────────────────────────────────

export async function renderCheckoutPage(containerId) {
  const container = document.getElementById(containerId);
  const items = getCart();
  if (!items.length) {
    container.innerHTML = '<p>Giỏ hàng đang trống.</p><a href="#catalog">Tiếp tục mua sắm</a>';
    return;
  }
  if (!await refreshCustomer()) {
    localStorage.setItem('cdp_after_login', '#checkout');
    container.innerHTML = '<h2>Thanh toán</h2><p>Đăng nhập để tạo đơn hàng.</p><a class="btn btn-primary" href="#account">Đăng nhập / Đăng ký</a>';
    return;
  }
  const cartFingerprint = JSON.stringify(items.map(i => [i.product_id, i.quantity]).sort());
  let pending = JSON.parse(sessionStorage.getItem('cdp_pending_order') || 'null');
  if (!pending || pending.cart !== cartFingerprint) {
    pending = { cart: cartFingerprint, key: crypto.randomUUID() };
    sessionStorage.setItem('cdp_pending_order', JSON.stringify(pending));
  }
  container.innerHTML = `<h2>Xác nhận đơn hàng</h2>
    <div class="card" style="margin-top:1rem">
      ${items.map(i => `<p>${escapeHTML(i.product_id)} × ${i.quantity}</p>`).join('')}
      <p>Tạm tính: $${cartTotal().toFixed(2)} USD. Giá cuối cùng được xác nhận khi tạo đơn.</p>
      <button id="btn-place-order" class="btn btn-primary">Tạo đơn hàng</button>
      <p id="checkout-error" role="alert" style="color:var(--danger)"></p>
    </div>`;
  document.getElementById('btn-place-order').addEventListener('click', async () => {
    const button = document.getElementById('btn-place-order');
    button.disabled = true;
    try {
      const order = await api('/api/orders', 'POST', {
        items: items.map(i => ({ product_id: i.product_id, quantity: i.quantity })), run_id: getRunId(),
      }, { 'Idempotency-Key': pending.key });
      track('begin_checkout', { cart_id: order.order_id, order_id: order.order_id,
        items: order.items, total_price: order.total_price, currency: order.currency });
      clearCart(); updateNavCartBadge(); flushEvents();
      sessionStorage.removeItem('cdp_pending_order');
      container.innerHTML = `<div class="card"><h2>Đã tạo đơn hàng</h2>
        <p>Mã đơn: ${escapeHTML(order.order_id)}</p><p>Trạng thái: ${order.status}</p>
        <p>${escapeHTML(order.total_price)} ${escapeHTML(order.currency)}</p>
        <a class="btn btn-primary" href="#account">Xem đơn và xác nhận thanh toán mô phỏng</a></div>`;
    } catch (error) {
      document.getElementById('checkout-error').textContent = error.message;
      button.disabled = false;
    }
  });
}
