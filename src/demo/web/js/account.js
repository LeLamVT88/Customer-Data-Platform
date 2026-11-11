import { getUserId, getSessionId, getRunId, setCustomerId, track } from './tracker.js';

const API = `http://${location.hostname}:8000`;
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let customer = null;

export async function api(path, method = 'GET', body = null, headers = {}) {
  const response = await fetch(API + path, {
    method, credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...headers },
    ...(body === null ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Dữ liệu không hợp lệ.');
  return data;
}

export async function refreshCustomer() {
  try { customer = await api('/api/auth/me'); } catch (_) { customer = null; }
  setCustomerId(customer?.customer_id);
  const link = document.querySelector('[data-page="account"]');
  if (link) link.textContent = customer ? customer.name : 'Đăng nhập';
  return customer;
}

export async function renderAccount(containerId) {
  const container = document.getElementById(containerId);
  await refreshCustomer();
  if (!customer) {
    container.innerHTML = `
      <h2>Tài khoản</h2>
      <form id="account-form" class="card" style="max-width:480px;margin-top:1rem">
        <div class="form-group"><label for="account-name">Tên (khi đăng ký)</label><input id="account-name" autocomplete="name" maxlength="100"></div>
        <div class="form-group"><label for="account-email">Email</label><input id="account-email" type="email" autocomplete="username" required></div>
        <div class="form-group"><label for="account-password">Mật khẩu</label><input id="account-password" type="password" autocomplete="current-password" minlength="8" required></div>
        <button class="btn btn-primary" type="submit">Đăng nhập</button>
        <button class="btn" id="register" type="button">Đăng ký</button>
        <p id="account-error" role="alert" style="color:var(--danger)"></p>
      </form>`;
    async function submit(register) {
      const form = document.getElementById('account-form');
      if (!form.reportValidity()) return;
      const buttons = form.querySelectorAll('button');
      buttons.forEach(b => b.disabled = true);
      try {
        const credentials = { email: document.getElementById('account-email').value, password: document.getElementById('account-password').value };
        if (register) await api('/api/auth/register', 'POST', { ...credentials, name: document.getElementById('account-name').value || 'Khách demo', run_id: getRunId() });
        const auth = await api('/api/auth/login', 'POST', {
          ...credentials, anonymous_id: getUserId(), session_id: getSessionId(), run_id: getRunId(),
        });
        setCustomerId(auth.customer_id);
        track('identity_authenticated', { customer_id: auth.customer_id, link_id: auth.link_id });
        await refreshCustomer();
        location.hash = localStorage.getItem('cdp_after_login') || '#account';
        localStorage.removeItem('cdp_after_login');
        await renderAccount(containerId);
      } catch (error) {
        document.getElementById('account-error').textContent = error.message;
      } finally { buttons.forEach(b => b.disabled = false); }
    }
    document.getElementById('account-form').addEventListener('submit', e => { e.preventDefault(); submit(false); });
    document.getElementById('register').addEventListener('click', () => submit(true));
    return;
  }
  const orders = await api('/api/orders');
  container.innerHTML = `
    <h2>Xin chào, ${escapeHTML(customer.name)}</h2>
    <p>${escapeHTML(customer.email)}</p><button class="btn" id="logout">Đăng xuất</button>
    <h3 style="margin-top:1rem">Đơn hàng của bạn</h3>
    <p>Các nút thanh toán và hoàn tiền mô phỏng thay đổi trạng thái đơn trong hệ thống demo.</p>
    ${orders.length ? orders.map(order => `
      <div class="card" style="margin-top:1rem">
        <strong>${escapeHTML(order.order_id)}</strong>
        <p>${escapeHTML(order.total_price)} ${escapeHTML(order.currency)} · <b>${escapeHTML(order.status)}</b></p>
        ${order.items.map(i => `<p>${escapeHTML(i.product_id)} × ${i.quantity}</p>`).join('')}
        ${(order.status === 'CREATED' ? ['PAID','CANCELLED'] : order.status === 'PAID' ? ['REFUNDED'] : []).map(status =>
          `<button class="btn order-status" data-order="${order.order_id}" data-status="${status}">${{PAID:'Xác nhận thanh toán',CANCELLED:'Hủy đơn',REFUNDED:'Hoàn tiền'}[status]}</button>`).join('')}
      </div>`).join('') : '<p>Chưa có đơn hàng.</p>'}
    <p id="orders-error" role="alert" style="color:var(--danger)"></p>`;
  document.getElementById('logout').addEventListener('click', async () => {
    await api('/api/auth/logout', 'POST');
    setCustomerId(null);
    await renderAccount(containerId);
  });
  container.querySelectorAll('.order-status').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const order = await api(`/api/orders/${button.dataset.order}/status`, 'PATCH', { status: button.dataset.status });
      if (order.status === 'PAID') track('purchase_observed', {
        cart_id: order.order_id, order_id: order.order_id, items: order.items,
        total_price: order.total_price, currency: order.currency,
      });
      await renderAccount(containerId);
    } catch (error) { document.getElementById('orders-error').textContent = error.message; button.disabled = false; }
  }));
}
