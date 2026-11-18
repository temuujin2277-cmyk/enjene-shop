import os
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, abort)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///shop.db"
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")


# ---------- Models ----------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Integer, nullable=False)  # төгрөгөөр
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(500), default="")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.Text, nullable=False)
    total = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    product_name = db.Column(db.String(120))
    price = db.Column(db.Integer)
    qty = db.Column(db.Integer)


# ---------- Helpers ----------
@app.template_filter("mnt")
def mnt(value):
    return f"{value:,}₮".replace(",", "'")


def get_cart():
    """Сагс: {product_id(str): qty}. Бүтээгдэхүүний мэдээллийг DB-ээс авна."""
    cart = session.get("cart", {})
    lines, total = [], 0
    for pid, qty in cart.items():
        p = db.session.get(Product, int(pid))
        if p:
            sub = p.price * qty
            lines.append({"product": p, "qty": qty, "subtotal": sub})
            total += sub
    return lines, total


@app.context_processor
def inject_cart_count():
    return {"cart_count": sum(session.get("cart", {}).values())}


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return wrapper


# ---------- Shop ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    return render_template("index.html", products=query.order_by(Product.id.desc()).all(), q=q)


@app.route("/product/<int:pid>")
def product(pid):
    p = db.session.get(Product, pid) or abort(404)
    return render_template("product.html", p=p)


@app.post("/cart/add/<int:pid>")
def cart_add(pid):
    p = db.session.get(Product, pid) or abort(404)
    qty = max(1, int(request.form.get("qty", 1)))
    cart = session.get("cart", {})
    new_qty = cart.get(str(pid), 0) + qty
    if new_qty > p.stock:
        flash(f"Үлдэгдэл хүрэлцэхгүй байна (үлдэгдэл: {p.stock}).", "error")
        return redirect(request.referrer or url_for("index"))
    cart[str(pid)] = new_qty
    session["cart"] = cart
    flash(f"«{p.name}» сагсанд нэмэгдлээ.", "ok")
    return redirect(request.referrer or url_for("index"))


@app.route("/cart")
def cart():
    lines, total = get_cart()
    return render_template("cart.html", lines=lines, total=total)


@app.post("/cart/remove/<int:pid>")
def cart_remove(pid):
    cart = session.get("cart", {})
    cart.pop(str(pid), None)
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines, total = get_cart()
    if not lines:
        return redirect(url_for("cart"))
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        address = request.form["address"].strip()
        if not (name and phone and address):
            flash("Бүх талбарыг бөглөнө үү.", "error")
            return render_template("checkout.html", lines=lines, total=total)
        # Үлдэгдэл дахин шалгана
        for l in lines:
            if l["qty"] > l["product"].stock:
                flash(f"«{l['product'].name}» үлдэгдэл хүрэлцэхгүй.", "error")
                return redirect(url_for("cart"))
        order = Order(customer_name=name, phone=phone, address=address, total=total)
        for l in lines:
            order.items.append(OrderItem(product_name=l["product"].name,
                                         price=l["product"].price, qty=l["qty"]))
            l["product"].stock -= l["qty"]
        db.session.add(order)
        db.session.commit()
        session.pop("cart", None)
        return render_template("success.html", order=order)
    return render_template("checkout.html", lines=lines, total=total)


# ---------- Admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        flash("Нууц үг буруу.", "error")
    return render_template("login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    products = Product.query.order_by(Product.id.desc()).all()
    orders = Order.query.order_by(Order.id.desc()).limit(50).all()
    return render_template("admin.html", products=products, orders=orders)


@app.route("/admin/product/new", methods=["GET", "POST"])
@app.route("/admin/product/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_product(pid=None):
    p = db.session.get(Product, pid) if pid else None
    if request.method == "POST":
        if p is None:
            p = Product()
            db.session.add(p)
        p.name = request.form["name"].strip()
        p.description = request.form.get("description", "")
        p.price = int(request.form["price"])
        p.stock = int(request.form["stock"])
        p.image_url = request.form.get("image_url", "").strip()
        db.session.commit()
        flash("Хадгалагдлаа.", "ok")
        return redirect(url_for("admin"))
    return render_template("product_form.html", p=p)


@app.post("/admin/product/<int:pid>/delete")
@admin_required
def admin_delete(pid):
    p = db.session.get(Product, pid) or abort(404)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("admin"))


def seed():
    if Product.query.count() == 0:
        db.session.add_all([
            Product(name="Кашмир ороолт", description="100% монгол кашмир, зөөлөн дулаан.",
                    price=85000, stock=10, image_url="https://picsum.photos/seed/a/400/300"),
            Product(name="Гар утасны гэр", description="Бат бөх, нимгэн.",
                    price=15000, stock=25, image_url="https://picsum.photos/seed/b/400/300"),
            Product(name="Чихэвч", description="Утасгүй, 20 цагийн цэнэг.",
                    price=45000, stock=15, image_url="https://picsum.photos/seed/c/400/300"),
        ])
        db.session.commit()


with app.app_context():
    db.create_all()
    seed()

if __name__ == "__main__":
    app.run(debug=True)
