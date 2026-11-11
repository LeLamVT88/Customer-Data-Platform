"""Demo business source. PostgreSQL is authoritative for customers and orders."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")
COOKIE = "cdp_demo_auth"
DSN = os.getenv("CDP_BUSINESS_DSN", "postgresql://cdp:cdp-local-business@127.0.0.1:15433/business")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row, connect_timeout=5)


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


# Missing users still perform one password verification, without hashing twice.
_DUMMY_PASSWORD_HASH = password_hash("unused-password", "0" * 32)


def password_matches(password: str, encoded: str) -> bool:
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(password_hash(password, salt), encoded)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    run_id: str = Field(default="manual", min_length=1, max_length=100)


class Login(Credentials):
    anonymous_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="manual", min_length=1, max_length=100)


class LineItem(BaseModel):
    product_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=99)


class OrderRequest(BaseModel):
    items: list[LineItem] = Field(min_length=1, max_length=100)
    run_id: str = Field(default="manual", min_length=1, max_length=100)


class StatusRequest(BaseModel):
    status: str = Field(pattern="^(PAID|CANCELLED|REFUNDED)$")


def current_customer(conn, request: Request):
    token = request.cookies.get(COOKIE, "")
    customer = conn.execute(
        "SELECT c.customer_id, c.email, c.name FROM auth_sessions s JOIN customers c USING(customer_id) "
        "WHERE s.token_hash=%s AND s.expires_at>now()",
        (hashlib.sha256(token.encode()).hexdigest(),),
    ).fetchone()
    if not customer:
        raise HTTPException(401, "Bạn cần đăng nhập.")
    return customer


@router.post("/auth/register", status_code=201)
def register(body: Registration):
    try:
        with connect() as conn:
            customer = conn.execute(
                "INSERT INTO customers(customer_id,email,name,password_hash,run_id) VALUES(%s,%s,%s,%s,%s) "
                "RETURNING customer_id,email,name",
                (uuid.uuid4(), body.email.strip().lower(), body.name.strip(), password_hash(body.password), body.run_id),
            ).fetchone()
        return customer
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Email đã được đăng ký.")


@router.post("/auth/login")
def login(body: Login, response: Response):
    with connect() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE email=%s", (body.email.strip().lower(),)).fetchone()
        # Equal-cost hash when an email is absent.
        encoded = customer["password_hash"] if customer else _DUMMY_PASSWORD_HASH
        if not password_matches(body.password, encoded) or not customer:
            raise HTTPException(401, "Email hoặc mật khẩu không đúng.")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO auth_sessions VALUES(%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), customer["customer_id"],
                      datetime.now(timezone.utc) + timedelta(hours=24)))
        link = conn.execute(
            "INSERT INTO identity_links(link_id,anonymous_id,session_id,customer_id,run_id,evidence) "
            "VALUES(%s,%s,%s,%s,%s,'authenticated_login') RETURNING link_id,linked_at",
            (uuid.uuid4(), body.anonymous_id, body.session_id, customer["customer_id"], body.run_id),
        ).fetchone()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=86400, path="/")
    return {"customer_id": customer["customer_id"], "email": customer["email"], "name": customer["name"], **link}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, "")
    with connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(COOKIE, path="/")
    return {"status": "ok"}


@router.get("/auth/me")
def me(request: Request):
    with connect() as conn:
        return current_customer(conn, request)


def order_responses(conn, orders):
    """Load items for all orders in one query, preserving the API response shape."""
    if not orders:
        return []
    items_by_order = {order["order_id"]: [] for order in orders}
    items = conn.execute(
        "SELECT order_id,product_id,quantity,unit_price::text AS price,currency FROM order_items "
        "WHERE order_id=ANY(%s) ORDER BY order_id,product_id", (list(items_by_order),),
    )
    for item in items:
        items_by_order[item.pop("order_id")].append(item)
    return [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in order.items()
         if k not in ("request_hash", "idempotency_key")}
        | {"items": items_by_order[order["order_id"]]}
        for order in orders
    ]


def order_response(conn, order):
    return order_responses(conn, [order])[0]


@router.post("/orders", status_code=201)
def create_order(body: OrderRequest, request: Request):
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 128:
        raise HTTPException(400, "Cần Idempotency-Key dài 1–128 ký tự.")
    quantities = Counter()
    for item in body.items:
        quantities[item.product_id] += item.quantity
    if any(q > 99 for q in quantities.values()):
        raise HTTPException(422, "Mỗi sản phẩm tối đa 99 đơn vị.")
    fingerprint = hashlib.sha256(json.dumps({"items": sorted(quantities.items()), "run_id": body.run_id},
                                            sort_keys=True).encode()).hexdigest()
    with connect() as conn:
        customer = current_customer(conn, request)
        # Serializes concurrent retries before checking the unique customer/key pair.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{customer['customer_id']}:{key}",))
        old = conn.execute("SELECT * FROM orders WHERE customer_id=%s AND idempotency_key=%s",
                           (customer["customer_id"], key)).fetchone()
        if old:
            if old["request_hash"] != fingerprint:
                raise HTTPException(409, "Idempotency-Key đã dùng cho nội dung khác.")
            return order_response(conn, old)
        products = conn.execute("SELECT * FROM products WHERE product_id=ANY(%s) AND active FOR SHARE",
                                (list(quantities),)).fetchall()
        if len(products) != len(quantities):
            raise HTTPException(422, "Có sản phẩm không tồn tại hoặc đã ngừng bán.")
        currencies = {p["currency"] for p in products}
        if len(currencies) != 1:
            raise HTTPException(422, "Giỏ hàng phải cùng đơn vị tiền tệ.")
        total = sum((p["price"] * quantities[p["product_id"]] for p in products), Decimal("0.00"))
        order = conn.execute(
            "INSERT INTO orders(order_id,customer_id,idempotency_key,request_hash,status,total_price,currency,run_id) "
            "VALUES(%s,%s,%s,%s,'CREATED',%s,%s,%s) RETURNING *",
            (uuid.uuid4(), customer["customer_id"], key, fingerprint, total, currencies.pop(), body.run_id),
        ).fetchone()
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO order_items(order_id,product_id,quantity,unit_price,currency) VALUES(%s,%s,%s,%s,%s)",
                [(order["order_id"], p["product_id"], quantities[p["product_id"]], p["price"], p["currency"])
                 for p in products],
            )
        return order_response(conn, order)


@router.get("/orders")
def list_orders(request: Request):
    with connect() as conn:
        customer = current_customer(conn, request)
        orders = conn.execute("SELECT * FROM orders WHERE customer_id=%s ORDER BY created_at DESC LIMIT 100",
                              (customer["customer_id"],)).fetchall()
        return order_responses(conn, orders)


@router.patch("/orders/{order_id}/status")
def update_status(order_id: uuid.UUID, body: StatusRequest, request: Request):
    with connect() as conn:
        customer = current_customer(conn, request)
        order = conn.execute("SELECT * FROM orders WHERE order_id=%s AND customer_id=%s FOR UPDATE",
                             (order_id, customer["customer_id"])).fetchone()
        if not order:
            raise HTTPException(404, "Không tìm thấy đơn hàng.")
        if order["status"] == body.status:
            return order_response(conn, order)
        transitions = {"CREATED": {"PAID", "CANCELLED"}, "PAID": {"REFUNDED"}}
        if body.status not in transitions.get(order["status"], set()):
            raise HTTPException(409, f"Không thể đổi {order['status']} thành {body.status}.")
        order = conn.execute("UPDATE orders SET status=%s,updated_at=now() WHERE order_id=%s RETURNING *",
                             (body.status, order_id)).fetchone()
        return order_response(conn, order)


def seed_catalog(catalog):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO products(product_id,category_id,brand,price,currency,image_url) VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(product_id) DO NOTHING",
                [(p["product_id"], p["category_id"], p["brand"], p["price"], p["currency"], p.get("image_url")) for p in catalog],
            )


def catalog_from_db():
    with connect() as conn:
        return conn.execute("SELECT product_id,category_id,brand,price::text,currency,image_url "
                            "FROM products WHERE active ORDER BY product_id").fetchall()
