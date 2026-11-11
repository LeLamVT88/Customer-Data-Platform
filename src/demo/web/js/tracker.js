/**
 * src/demo/web/js/tracker.js — Snowplow tracking layer cho CDP Demo.
 *
 * Toàn bộ logic thu thập event nằm ở đây và do Snowplow Browser Tracker đảm
 * nhiệm. Pipeline Snowplow lo phần còn lại:
 *
 *   JS Tracker ──HTTP──▶ Collector Kafka ──▶ Enrich (Iglu + YAUAA)
 *                                                    │
 *                                                    ▼
 *                                       Kafka good/bad → observer PostgreSQL
 *
 * Mỗi event type của CDP Demo có một Iglu schema riêng trong
 * config/snowplow/iglu-client-embedded/schemas/com.cdp.demo/.
 * Schema được khai báo bằng `trackSelfDescribingEvent` nên Enrich validate
 * được payload; event không khớp schema sẽ bị Enrich ghi vào bad stream.
 *
 * Load thư viện bằng <script> trước module này:
 *   <script src="vendor/snowplow-browser-tracker.min.js"></script>
 */

/** Collector URL. Mặc định trỏ về Snowplow Collector Kafka trong Docker Compose. */
export const COLLECTOR_URL = `http://${location.hostname}:9091`;

/** app_id — định danh ứng dụng trong Snowplow. */
export const APP_ID = 'cdp-demo';

/** tracker namespace. */
export const TRACKER_NAME = 'cdpDemo';

/** Vendor của toàn bộ schema CDP Demo. */
export const VENDOR = 'com.cdp.demo';

/**
 * Schema URI cho một event type.
 * @param {string} name tên event, ví dụ 'product_view'
 * @param {string} version phiên bản schema, mặc định '1-0-0'
 */
export function schemaUri(name, version = '1-0-0') {
  return `iglu:${VENDOR}/${name}/jsonschema/${version}`;
}

/**
 * Danh sách event type hợp lệ. Khớp với schema trong
 * config/snowplow/iglu-client-embedded/schemas/com.cdp.demo/.
 */
export const EVENT_TYPES = Object.freeze([
  'page_view',
  'product_view',
  'add_to_cart',
  'remove_from_cart',
  'begin_checkout',
  'purchase_observed',
  'element_click',
  'scroll_depth',
  'search',
  'error',
  'cart_abandoned',
  'apply_filter',
  'wishlist_add',
  'wishlist_remove',
  'newsletter_signup',
  'identity_authenticated',
]);

/** Entity: định danh phiên do ứng dụng cấp. */
export const SESSION_ENTITY = schemaUri('session');
/** Entity: thuộc tính sản phẩm dùng chung cho nhiều event. */
export const PRODUCT_ENTITY = schemaUri('product');

const sp = () => window.snowplowBrowserTracking;

// ── Identity ────────────────────────────────────────────────────────────────

const USER_COOKIE = 'cdp_demo_uid';
const SESSION_KEY = 'cdp_demo_sid';

let _sessionId = null;
let _customerId = null;

export function getRunId() {
  let id = sessionStorage.getItem('cdp_demo_run');
  if (!id) { id = 'web-' + crypto.randomUUID(); sessionStorage.setItem('cdp_demo_run', id); }
  return id;
}

export function setCustomerId(id) {
  _customerId = id || null;
  if (_initialised) sp().setUserId(_customerId);
}

/** user_id ổn định theo cookie (90 ngày), dùng cho cột atomic user_id. */
export function getUserId() {
  try {
    const match = document.cookie.split('; ').find(r => r.startsWith(USER_COOKIE + '='));
    if (match) return match.split('=')[1];
    const uid = 'u_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    const expires = new Date(Date.now() + 90 * 864e5).toUTCString();
    document.cookie = `${USER_COOKIE}=${uid}; expires=${expires}; path=/; SameSite=Lax`;
    return uid;
  } catch (_) {
    return 'uid_fallback';
  }
}

/** session_id ổn định theo tab, đóng vai entity session. */
export function getSessionId() {
  if (_sessionId) return _sessionId;
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) { _sessionId = saved; return _sessionId; }
  } catch (_) {}
  _sessionId = crypto.randomUUID();
  try { sessionStorage.setItem(SESSION_KEY, _sessionId); } catch (_) {}
  return _sessionId;
}

// ── Tracker bootstrap ───────────────────────────────────────────────────────

let _initialised = false;

/**
 * Khởi tạo Snowplow Browser Tracker.
 * Gọi một lần khi app khởi động. Idempotent.
 */
export function initTracker() {
  if (_initialised) return;
  const snowplow = sp();
  if (!snowplow) {
    throw new Error('Snowplow Browser Tracker chưa được nạp (vendor/snowplow-browser-tracker.min.js).');
  }

  snowplow.newTracker(TRACKER_NAME, COLLECTOR_URL, {
    appId: APP_ID,
    platform: 'web',
    cookieSameSite: 'Lax',
    // Gửi event ngay, không gom lại 5 giây như bản tự viết trước đây.
    eventMethod: 'post',
    // bufferSize = 1 ⇒ mỗi event gửi ngay một request riêng.
    // Nếu để > 1, tracker gom event vào store và chỉ đẩy lên collector
    // khi đủ số lượng ⇒ demo sẽ không thấy dữ liệu "tức thì" trên dashboard.
    bufferSize: 1,
  });

  snowplow.setUserId(_customerId);

  _initialised = true;
}

/**
 * Đẩy buffer lên collector ngay.
 *
 * Tracker với bufferSize=1 đã gửi từng event ngay, nhưng vẫn cần hàm này ở
 * những điểm then chốt (checkout, đổi trang) để đảm bảo không còn event
 * nào nằm trong store khi user rời trang.
 */
export function flushEvents() {
  if (!_initialised) return;
  sp().flushBuffer();
}

/**
 * Gửi một page_view cho route hiện tại.
 *
 * Route của web demo là hash-based (#catalog, #product?id=...), nên "path"
 * được lấy từ hash (bỏ dấu #) để khớp với các path mà bot sinh ra
 * ("/", "/catalog", "/cart", ...).
 *
 * @param {string} path đường dẫn (không có dấu #)
 * @param {string} [title] tiêu đề trang
 */
export function trackPageView(path, title = '') {
  track('page_view', { path, title });
}

/**
 * Gửi event scroll_depth.
 *
 * @param {number} depthPercent phần trăm đã cuộn (0-100)
 */
export function trackScrollDepth(depthPercent) {
  const depth = Math.max(0, Math.min(100, Math.round(depthPercent)));
  track('scroll_depth', { depth_percent: depth });
}

/**
 * Gửi event lỗi phía client.
 *
 * @param {string} message thông điệp lỗi
 * @param {string} [stack] stack trace nếu có
 */
export function trackError(message, stack = '') {
  const payload = { message: String(message || 'Unknown error') };
  if (stack) payload.stack = String(stack);
  track('error', payload);
}

// ── Event helpers ───────────────────────────────────────────────────────────

/** Entity session, gắn vào mọi event để truy vết được session_id. */
function sessionContext() {
  const source = { run_id: getRunId(), anonymous_id: getUserId() };
  if (_customerId) source.customer_id = _customerId;
  return [
    { schema: SESSION_ENTITY, data: { session_id: getSessionId() } },
    { schema: schemaUri('source'), data: source },
  ];
}

/**
 * Gắn entity product khi event có thông tin sản phẩm.
 * @param {object} product đối tượng sản phẩm trong catalog
 */
function productContext(product) {
  if (!product || !product.product_id) return [];
  return [{
    schema: PRODUCT_ENTITY,
    data: {
      product_id: product.product_id,
      category_id: product.category_id,
      brand: product.brand,
      price: product.price,
      currency: product.currency,
    },
  }];
}

/**
 * Gửi một self-describing event theo Iglu schema.
 *
 * @param {string} eventType tên event, phải có trong EVENT_TYPES
 * @param {object} data payload theo schema
 * @param {object[]} [contexts] entity bổ sung
 */
export function track(eventType, data = {}, contexts = []) {
  if (!EVENT_TYPES.includes(eventType)) {
    console.warn(`[snowplow] Bỏ qua event không hợp lệ: ${eventType}`);
    return;
  }
  if (!_initialised) initTracker();

  sp().trackSelfDescribingEvent({
    event: {
      schema: schemaUri(eventType, ['begin_checkout', 'purchase_observed'].includes(eventType) && data.order_id ? '1-0-1' : '1-0-0'),
      data,
    },
    // Entity session luôn có mặt; entity product thêm theo ngữ cảnh.
    context: [...sessionContext(), ...contexts],
  });
}

/**
 * Gửi event kèm entity product.
 * @param {string} eventType tên event
 * @param {object} data payload
 * @param {object} [product] sản phẩm liên quan
 */
export function trackProduct(eventType, data = {}, product = null) {
  track(eventType, data, productContext(product));
}
