
import os, json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import pandas as pd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'dev-secret-change-me')

MYSQL_URL = os.environ.get('MYSQL_URL')
if MYSQL_URL:
    app.config['SQLALCHEMY_DATABASE_URI'] = MYSQL_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'data.db')  # fallback dev only
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------------- Models ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='usuario')  # admin, bodeguero, usuario
    name = db.Column(db.String(120), nullable=True)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(200), nullable=False, index=True)
    categoria = db.Column(db.String(100), nullable=True)
    comentarios = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)  # imagen del producto (URL)
    image_file = db.Column(db.String(255), nullable=True)  # imagen subida
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # bodega, piso, trastienda
    pasillo = db.Column(db.String(50), nullable=True)
    rack = db.Column(db.String(50), nullable=True)
    cantidad = db.Column(db.Integer, default=0)
    product = db.relationship('Product', backref=db.backref('locations', lazy=True))

class ProductLocationPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('product_location.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    location = db.relationship('ProductLocation', backref=db.backref('photos', lazy=True))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    requested_by = db.Column(db.String(120), nullable=False)  # nombre o email del solicitante
    requested_for_time = db.Column(db.String(50), nullable=True)  # hora deseada (select 8:00-20:30)
    status = db.Column(db.String(20), default='pendiente')  # pendiente, entregado

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    sku = db.Column(db.String(64), nullable=True)  # puede no existir en catálogo
    nombre = db.Column(db.String(200), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    order = db.relationship('Order', backref=db.backref('items', lazy=True))

class OrderItemPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_item.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    item = db.relationship('OrderItem', backref=db.backref('photos', lazy=True))

class Planograma(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    contenido = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Curso(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)

class CursoMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey('curso.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(20), nullable=False)
    curso = db.relationship('Curso', backref=db.backref('media', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def ensure_admin():
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@tienda.com')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(email=admin_email, role='admin', name='Administrador')
        admin.set_password(admin_pass)
        db.session.add(admin); db.session.commit()

with app.app_context():
    db.create_all(); ensure_admin()

# Helpers
def role_required(*roles):
    from functools import wraps
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return decorated
    return wrapper

def save_file(file_storage):
    filename = secure_filename(file_storage.filename or '')
    if not filename: return None
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file_storage.save(path)
    try:
        img = Image.open(path); img.thumbnail((1600,1600)); img.save(path)
    except Exception: pass
    return filename

# Files
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ----------------- Public pages -----------------
@app.route('/')
def home():
    pasillos = db.session.query(ProductLocation.pasillo).distinct().all()
    pasillos = sorted([p[0] for p in pasillos if p[0]])
    planograma = Planograma.query.first()
    return render_template('home.html', pasillos=pasillos, planograma=planograma)

# Login/Logout
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user); return redirect(url_for('home'))
        flash('Credenciales inválidas', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----------------- Inventario -----------------
@app.route('/inventario')
@login_required
def inventario():
    productos = Product.query.order_by(Product.created_at.desc()).all()
    stock_map = {p.id: sum(loc.cantidad for loc in p.locations) for p in productos}
    return render_template('inventario.html', productos=productos, stock_map=stock_map)

@app.route('/producto/nuevo', methods=['GET','POST'])
@login_required
@role_required('admin','bodeguero')
def producto_nuevo():
    if request.method == 'POST':
        sku = request.form.get('sku','').strip()
        nombre = request.form.get('nombre','').strip()
        categoria = request.form.get('categoria','').strip()
        comentarios = request.form.get('comentarios','').strip() or None
        image_url = request.form.get('image_url','').strip() or None
        image_file_upload = request.files.get('image_file')
        if not sku or not nombre:
            flash('SKU y nombre son obligatorios', 'danger'); return redirect(request.url)
        if Product.query.filter_by(sku=sku).first():
            flash('SKU ya existe', 'danger'); return redirect(request.url)
        p = Product(sku=sku, nombre=nombre, categoria=categoria, comentarios=comentarios)
        if image_url: p.image_url = image_url
        if image_file_upload and image_file_upload.filename:
            fn = save_file(image_file_upload); 
            if fn: p.image_file = fn
        db.session.add(p); db.session.commit()
        flash('Producto creado. Ahora agrega ubicaciones y fotos por área.', 'success')
        return redirect(url_for('producto_editar', product_id=p.id))
    return render_template('producto_form.html', producto=None)

@app.route('/producto/<int:product_id>/editar', methods=['GET','POST'])
@login_required
@role_required('admin','bodeguero')
def producto_editar(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        p.nombre = request.form.get('nombre', p.nombre)
        p.categoria = request.form.get('categoria', p.categoria)
        p.comentarios = request.form.get('comentarios', p.comentarios)
        image_url = request.form.get('image_url','').strip() or None
        if image_url: p.image_url = image_url
        image_file_upload = request.files.get('image_file')
        if image_file_upload and image_file_upload.filename:
            fn = save_file(image_file_upload); 
            if fn: p.image_file = fn
        db.session.commit()
        flash('Producto actualizado', 'success')
    return render_template('producto_form.html', producto=p)

@app.route('/producto/<int:product_id>/ubicacion/agregar', methods=['POST'])
@login_required
@role_required('admin','bodeguero')
def producto_agregar_ubicacion(product_id):
    p = Product.query.get_or_404(product_id)
    tipo = request.form.get('tipo')
    pasillo = request.form.get('pasillo')
    rack = request.form.get('rack')
    cantidad = int(request.form.get('cantidad') or 0)
    loc = ProductLocation(product=p, tipo=tipo, pasillo=pasillo, rack=rack, cantidad=cantidad)
    db.session.add(loc); db.session.commit()
    for f in request.files.getlist('fotos_area'):
        fn = save_file(f)
        if fn: db.session.add(ProductLocationPhoto(location=loc, filename=fn))
    db.session.commit()
    flash('Ubicación agregada', 'success')
    return redirect(url_for('producto_editar', product_id=p.id))

@app.route('/producto/<int:product_id>')
def producto_detalle(product_id):
    p = Product.query.get_or_404(product_id)
    stock_total = sum(loc.cantidad for loc in p.locations)
    return render_template('producto_detalle.html', p=p, stock_total=stock_total)

# ----------------- Buscador (público) -----------------
@app.route('/buscar')
def buscar():
    return render_template('buscar.html')

@app.route('/api/search')
def api_search():
    term = request.args.get('q','').strip()
    if not term: return jsonify([])
    filt = db.or_(Product.nombre.ilike(f'%{term}%'), Product.sku.ilike(f'%{term}%'))
    if len(term) == 4 and term.isdigit():
        filt = db.or_(filt, Product.sku.ilike(f'%{term}'))  # últimos 4
    products = Product.query.filter(filt).limit(12).all()
    data = []
    for p in products:
        stock = sum(loc.cantidad for loc in p.locations)
        loc = next((l for t in ['piso','trastienda','bodega'] for l in p.locations if l.tipo==t), None)
        pasillo = loc.pasillo if loc else None
        rack = loc.rack if loc else None
        foto_area = None
        if loc and loc.photos: foto_area = url_for('uploaded_file', filename=loc.photos[0].filename)
        prod_img = p.image_url or (url_for('uploaded_file', filename=p.image_file) if p.image_file else None)
        data.append({"id": p.id, "sku": p.sku, "nombre": p.nombre, "stock": stock, "pasillo": pasillo, "rack": rack, "foto_area": foto_area, "foto_producto": prod_img})
    return jsonify(data)

# ----------------- Comandas -----------------
def time_slots():
    slots = []
    for h in range(8, 21):  # 8..20
        slots.append(f"{h:02d}:00"); slots.append(f"{h:02d}:30")
    return slots

@app.route('/comanda/nueva', methods=['GET','POST'])
def comanda_nueva():
    if request.method == 'POST':
        requested_by = request.form.get('requested_by','').strip() or 'anonimo'
        requested_for_time = request.form.get('requested_for_time','')
        items_raw = request.form.get('items_json','[]')
        try:
            items = json.loads(items_raw)
        except Exception:
            items = []
        if not items:
            flash('Agrega al menos un producto', 'danger'); return redirect(request.url)
        order = Order(requested_by=requested_by, requested_for_time=requested_for_time, status='pendiente')
        db.session.add(order); db.session.commit()
        for it in items:
            oi = OrderItem(order=order, sku=it.get('sku'), nombre=it.get('nombre'), cantidad=int(it.get('cantidad',1)))
            db.session.add(oi); db.session.commit()
            for field_name in it.get('photo_fields', []):
                fs = request.files.get(field_name)
                if fs and fs.filename:
                    fn = save_file(fs); 
                    if fn: db.session.add(OrderItemPhoto(order_item_id=oi.id, filename=fn))
        db.session.commit()
        flash('Comanda creada. Quedará PENDIENTE hasta que bodega la entregue.', 'success')
        return redirect(url_for('comanda_ver', order_id=order.id))
    return render_template('comanda_nueva.html', time_slots=time_slots())

@app.route('/comanda/<int:order_id>')
@login_required
def comanda_ver(order_id):
    o = Order.query.get_or_404(order_id)
    if not (current_user.role in ['admin','bodeguero'] or current_user.email == o.requested_by):
        abort(403)
    enriched = []
    for it in o.items:
        p = Product.query.filter_by(sku=it.sku).first() if it.sku else None
        foto = None
        if p:
            loc = next((l for l in p.locations if l.tipo in ['piso','trastienda']), None)
            if loc and loc.photos: foto = url_for('uploaded_file', filename=loc.photos[0].filename)
        enriched.append((it, foto))
    return render_template('comanda_detalle.html', order=o, items=enriched)

@app.route('/admin/comandas')
@login_required
@role_required('admin','bodeguero')
def admin_comandas():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin_comandas.html', orders=orders)

@app.route('/admin/comandas/<int:order_id>/entregar', methods=['POST'])
@login_required
@role_required('admin','bodeguero')
def admin_comanda_entregar(order_id):
    o = Order.query.get_or_404(order_id)
    if o.status == 'entregado':
        flash('Esta comanda ya fue entregada', 'info')
        return redirect(url_for('admin_comandas'))
    for it in o.items:
        if it.sku:
            p = Product.query.filter_by(sku=it.sku).first()
            if p:
                for tipo in ['bodega','trastienda','piso']:
                    loc = next((l for l in p.locations if l.tipo==tipo and l.cantidad>0), None)
                    if loc:
                        take = min(loc.cantidad, it.cantidad)
                        loc.cantidad -= take
                        it.cantidad -= take
                        if it.cantidad == 0: break
                db.session.commit()
    o.status = 'entregado'
    db.session.commit()
    flash('Comanda marcada como ENTREGADA y stock descontado.', 'success')
    return redirect(url_for('admin_comandas'))

# ----------------- Admin: Import CSV/XLS/XLSX -----------------
@app.route('/admin/importar', methods=['GET','POST'])
@login_required
@role_required('admin','bodeguero')
def admin_importar():
    created, updated, errors = 0, 0, []
    if request.method == 'POST':
        f = request.files.get('archivo')
        if not f or not f.filename:
            flash('Sube un archivo CSV o XLS/XLSX', 'danger'); return redirect(request.url)
        ext = f.filename.rsplit('.',1)[-1].lower()
        try:
            if ext == 'csv':
                df = pd.read_csv(f)
            elif ext == 'xls':
                df = pd.read_excel(f, engine='xlrd')
            else:
                df = pd.read_excel(f, engine='openpyxl')
        except Exception as e:
            flash(f'Error leyendo archivo: {e}', 'danger'); return redirect(request.url)
        cols = {c.lower().strip(): c for c in df.columns}
        required = ['sku','nombre']
        for r in required:
            if r not in cols:
                flash(f'Falta columna requerida: {r}', 'danger'); return redirect(request.url)
        for i, row in df.iterrows():
            try:
                sku = str(row[cols['sku']]).strip()
                if not sku: continue
                nombre = str(row[cols['nombre']]).strip()
                categoria = str(row[cols['categoria']]).strip() if 'categoria' in cols and not pd.isna(row[cols['categoria']]) else None
                comentarios = str(row[cols['comentarios']]).strip() if 'comentarios' in cols and not pd.isna(row[cols['comentarios']]) else None
                p = Product.query.filter_by(sku=sku).first()
                if p:
                    p.nombre = nombre; p.categoria = categoria; p.comentarios = comentarios; updated += 1
                else:
                    p = Product(sku=sku, nombre=nombre, categoria=categoria, comentarios=comentarios); db.session.add(p); created += 1
                db.session.commit()
                if any(k in cols for k in ['tipo','pasillo','rack','cantidad']):
                    tipo = (str(row[cols.get('tipo')]).strip().lower() if 'tipo' in cols and not pd.isna(row[cols.get('tipo')]) else 'piso')
                    pasillo = str(row[cols.get('pasillo')]).strip() if 'pasillo' in cols and not pd.isna(row[cols.get('pasillo')]) else None
                    rack = str(row[cols.get('rack')]).strip() if 'rack' in cols and not pd.isna(row[cols.get('rack')]) else None
                    try:
                        cantidad = int(row[cols.get('cantidad')]) if 'cantidad' in cols and not pd.isna(row[cols.get('cantidad')]) else 0
                    except Exception: cantidad = 0
                    db.session.add(ProductLocation(product=p, tipo=tipo, pasillo=pasillo, rack=rack, cantidad=cantidad))
                    db.session.commit()
            except Exception as e:
                errors.append(f'Fila {i+1}: {e}')
        flash(f'Importación OK. Creados: {created}, Actualizados: {updated}. Errores: {len(errors)}', 'success')
        if errors: flash('\n'.join(errors[:5]) + ('\n...' if len(errors)>5 else ''), 'warning')
        return redirect(url_for('inventario'))
    return render_template('admin_importar.html')

# ----------------- API stock -----------------
@app.route('/api/stock/<int:product_id>')
def api_stock(product_id):
    p = Product.query.get_or_404(product_id)
    stock = sum(loc.cantidad for loc in p.locations)
    return jsonify({"product_id": p.id, "stock": stock})

# ----------------- Admin core -----------------
@app.route('/admin')
@login_required
@role_required('admin','bodeguero')
def admin_dashboard():
    productos = Product.query.count()
    pedidos_pend = Order.query.filter_by(status='pendiente').count()
    return render_template('admin_dashboard.html', productos=productos, pedidos_pend=pedidos_pend)

@app.route('/admin/planograma', methods=['GET','POST'])
@login_required
@role_required('admin','bodeguero')
def admin_planograma():
    p = Planograma.query.first()
    if not p:
        p = Planograma(titulo="Planograma general", contenido="Escribe aquí tu planograma...")
        db.session.add(p); db.session.commit()
    if request.method == 'POST':
        p.titulo = request.form.get('titulo', p.titulo)
        p.contenido = request.form.get('contenido', p.contenido)
        db.session.commit()
        flash('Planograma actualizado', 'success')
    return render_template('admin_planograma.html', planograma=p)

@app.route('/admin/educacion/nuevo', methods=['GET','POST'])
@login_required
@role_required('admin','bodeguero')
def admin_educacion_nuevo():
    if request.method == 'POST':
        titulo = request.form.get('titulo','').strip()
        descripcion = request.form.get('descripcion','').strip()
        if not titulo:
            flash('Título es obligatorio', 'danger'); return redirect(request.url)
        curso = Curso(titulo=titulo, descripcion=descripcion); db.session.add(curso); db.session.commit()
        files = request.files.getlist('media')
        for f in files:
            fn = save_file(f)
            if fn:
                ext = (fn.rsplit('.',1)[-1] or '').lower()
                media_type = 'video' if ext in ['mp4','mov','webm'] else 'image' if ext in ['jpg','jpeg','png','gif','webp'] else 'file'
                db.session.add(CursoMedia(curso=curso, filename=fn, media_type=media_type))
        db.session.commit()
        flash('Curso creado', 'success')
        return redirect(url_for('educacion_list'))
    return render_template('admin_educacion_nuevo.html')

@app.route('/admin/usuarios', methods=['GET','POST'])
@login_required
@role_required('admin')
def admin_usuarios():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        name = request.form.get('name','').strip()
        role = request.form.get('role','usuario')
        password = request.form.get('password','123456')
        if not email:
            flash('Email requerido', 'danger'); return redirect(request.url)
        if User.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email', 'danger'); return redirect(request.url)
        u = User(email=email, name=name, role=role); u.set_password(password)
        db.session.add(u); db.session.commit()
        flash('Usuario creado', 'success'); return redirect(url_for('admin_usuarios'))
    users = User.query.all()
    return render_template('admin_usuarios.html', users=users)

# Educación (público)
@app.route('/educacion')
def educacion_list():
    cursos = Curso.query.order_by(Curso.id.desc()).all()
    return render_template('educacion_list.html', cursos=cursos)

@app.route('/educacion/<int:curso_id>')
def educacion_detalle(curso_id):
    c = Curso.query.get_or_404(curso_id)
    return render_template('educacion_detalle.html', curso=c)

if __name__ == '__main__':
    # host=0.0.0.0 para que funcione en servidores remotos
    app.run(debug=True, host='0.0.0.0', port=5000)
