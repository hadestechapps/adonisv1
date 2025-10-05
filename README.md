
# Supermercado - Inventario y Comandas (Flask + MySQL)

Proyecto listo para ejecutar con `pip`. Incluye: inventario multi-ubicación (con fotos), comandas internas (pendiente→entregado con descuento de stock al entregar), buscador con autocompletado (imagen + pasillo), planograma, módulo educativo, importación CSV/XLS/XLSX, galería con modal, barra inferior móvil y permisos por rol.

## Requisitos
- Python 3.10+
- MySQL (opcional, para producción). Si no defines `MYSQL_URL` se usa SQLite local (para pruebas).

## Instalación
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
```

## Variables de entorno
```bash
export FLASK_SECRET="cambia-esto"
export ADMIN_EMAIL="admin@tienda.com"
export ADMIN_PASSWORD="admin123"
# Para MySQL (recomendado)
export MYSQL_URL="mysql+pymysql://usuario:password@host:3306/tu_db?charset=utf8mb4"
```
> Crea la base `tu_db` antes (p.ej. `CREATE DATABASE tu_db CHARACTER SET utf8mb4;`).

## Ejecutar
```bash
python app.py
```
Visita: http://127.0.0.1:5000

## Importar CSV/XLS/XLSX
**Admin → Importar**. Columnas:
- Requeridas: `sku`, `nombre`
- Opcionales: `categoria`, `comentarios`, `tipo`, `pasillo`, `rack`, `cantidad`
Puedes repetir `sku` en varias filas para crear múltiples ubicaciones.
