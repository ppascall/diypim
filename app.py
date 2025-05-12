from flask import Flask, render_template, request, redirect, send_file, jsonify
import csv
import os
import requests
from io import StringIO

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

CATEGORY_FILE = 'categories.csv'
PRODUCT_FILE = 'products.csv'
FEED_URL = "https://files.channable.com/cpw-UGScaZUwnJfd0TyLKQ==.csv"

# --- Helper Functions ---

def normalize_dict(d):
    return {k.strip().lower(): v.strip() for k, v in d.items() if k}

def load_fields():
    if not os.path.exists(CATEGORY_FILE):
        return []
    with open(CATEGORY_FILE, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def save_fields(fields):
    with open(CATEGORY_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['field_name', 'required', 'description'])
        writer.writeheader()
        writer.writerows(fields)

def load_products():
    if not os.path.exists(PRODUCT_FILE):
        return []
    with open(PRODUCT_FILE, newline='', encoding='utf-8', errors='ignore') as f:
        return list(csv.DictReader(f))

def save_products(products):
    if not products:
        return
    normalized_products = [normalize_dict(p) for p in products]
    fieldnames = sorted({k for p in normalized_products for k in p.keys()})
    with open(PRODUCT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized_products)

def save_product(product):
    file_exists = os.path.exists(PRODUCT_FILE)
    normalized = normalize_dict(product)
    with open(PRODUCT_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=normalized.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(normalized)

def import_feed():
    response = requests.get(FEED_URL)
    if response.status_code != 200:
        print("Failed to fetch feed.")
        return

    content = response.content.decode('utf-8')
    reader = csv.DictReader(StringIO(content))
    rows = [normalize_dict(row) for row in reader]

    if not rows:
        return

    existing_products = [normalize_dict(p) for p in load_products()]
    existing_fields = {f['field_name'].lower() for f in load_fields()}

    new_fields = [h.lower() for h in reader.fieldnames if h.lower() not in existing_fields]
    if new_fields:
        with open(CATEGORY_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['field_name', 'required', 'description'])
            if os.path.getsize(CATEGORY_FILE) == 0:
                writer.writeheader()
            for field in new_fields:
                writer.writerow({'field_name': field, 'required': 'False', 'description': ''})

    key_field = next((k for k in ['ean', 'id', 'title'] if k in rows[0]), None)
    if not key_field:
        print("No suitable key field found in feed.")
        return

    product_index = {p.get(key_field): p for p in existing_products if key_field in p}

    for row in rows:
        row_key = row.get(key_field)
        if not row_key:
            continue
        if row_key in product_index:
            product_index[row_key].update({k: v for k, v in row.items() if v})
        else:
            existing_products.append(row)

    save_products(existing_products)
    print("Feed imported and merged.")

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add_field', methods=['GET', 'POST'])
def add_field():
    if request.method == 'POST':
        field_name = request.form.get('field_name', '').strip().lower()
        required = request.form.get('required', 'no').strip().capitalize()
        description = request.form.get('description', '').strip()

        if not field_name:
            return jsonify({'success': False, 'message': 'Field name is required'}), 400

        fields = load_fields()
        if any(f['field_name'].lower() == field_name for f in fields):
            return jsonify({'success': False, 'message': 'Field already exists'}), 400

        new_field = {
            'field_name': field_name,
            'required': 'True' if required == 'Yes' else 'False',
            'description': description
        }

        fields.append(new_field)
        save_fields(fields)

        return jsonify({'success': True})

    return render_template('add_field.html', fields=load_fields())

@app.route('/manage_fields', methods=['GET', 'POST'])
def manage_fields():
    fields = load_fields()
    search_field = request.args.get('search_field', '').lower()

    if search_field:
        fields = [f for f in fields if search_field in f['field_name'].lower()]

    if request.method == 'POST':
        if 'field_index' in request.form:
            index = int(request.form['field_index'])
            old_name = fields[index]['field_name']
            new_name = request.form['field_name'].strip().lower()
            updated_desc = request.form['description']
            updated_required = request.form.get('required', 'False')

            fields[index] = {
                'field_name': new_name,
                'description': updated_desc,
                'required': updated_required
            }
            save_fields(fields)

            if old_name != new_name:
                products = load_products()
                for product in products:
                    if old_name in product:
                        product[new_name] = product.pop(old_name)
                save_products(products)

            return redirect('/manage_fields')

        elif 'delete_field_index' in request.form:
            index = int(request.form['delete_field_index'])
            deleted_field = fields[index]['field_name']
            del fields[index]
            save_fields(fields)

            products = load_products()
            for product in products:
                product.pop(deleted_field, None)
            save_products(products)
            return redirect('/manage_fields')

    selected_field = None
    field_index = request.args.get('field_index')
    if field_index and field_index.isdigit():
        i = int(field_index)
        if 0 <= i < len(fields):
            selected_field = fields[i]

    return render_template('manage_fields.html', fields=fields, selected_field=selected_field, search_field=search_field)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    fields = load_fields()
    if request.method == 'POST':
        product = {field['field_name']: request.form.get(field['field_name'], '') for field in fields}
        save_product(product)
        return redirect('/search')
    return render_template('add_product.html', fields=fields)

@app.route('/search')
def search():
    query = request.args.get('query', '').lower()
    field_key = request.args.get('field_key', '').lower()
    field_value = request.args.get('field_value', '').lower()
    products = [normalize_dict(p) for p in load_products()]

    results = []
    for i, product in enumerate(products):
        field_match = not field_key or not field_value or product.get(field_key, '') == field_value
        search_match = not query or any(query in str(v).lower() for v in product.values())
        if field_match and search_match:
            results.append({'index': i, 'data': product})

    return render_template('search.html', products=results, fields=load_fields())

@app.route('/delete/<int:index>', methods=['POST'])
def delete(index):
    products = load_products()
    if 0 <= index < len(products):
        del products[index]
        save_products(products)
    return redirect('/search')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        file = request.files['file']
        if file and (file.filename.endswith('.csv') or file.filename.endswith('.txt')):
            content = file.read().decode('utf-8')
            delimiter = '\t' if '\t' in content.splitlines()[0] else ','
            rows = [normalize_dict(r) for r in csv.DictReader(content.splitlines(), delimiter=delimiter)]

            if not rows:
                return redirect('/search')

            existing_products = [normalize_dict(p) for p in load_products()]
            existing_fields = {f['field_name'].lower() for f in load_fields()}

            new_fields = [h for h in rows[0].keys() if h not in existing_fields]
            if new_fields:
                with open(CATEGORY_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['field_name', 'required', 'description'])
                    if os.path.getsize(CATEGORY_FILE) == 0:
                        writer.writeheader()
                    for field in new_fields:
                        writer.writerow({
                            'field_name': field,
                            'required': 'False',
                            'description': ''
                        })

            key_field = next((k for k in ['ean', 'id', 'title'] if k in rows[0]), None)
            if not key_field:
                return "No key field found in uploaded data.", 400

            product_index = {p.get(key_field): p for p in existing_products if key_field in p}

            for row in rows:
                row_key = row.get(key_field)
                if not row_key:
                    continue
                if row_key in product_index:
                    product_index[row_key].update({k: v for k, v in row.items() if v})
                else:
                    existing_products.append(row)

            save_products(existing_products)
            return redirect('/search')

    return render_template('upload.html')

@app.route('/manage_products', methods=['GET', 'POST', 'DELETE'])
def manage_products_page():
    products = load_products()
    fields = load_fields()
    selected_product = None
    product_index = None

    if request.method == 'POST':
        product_index_raw = request.form.get('product_index')
        if product_index_raw is None or not product_index_raw.isdigit():
            return "Invalid product index.", 400
        product_index = int(product_index_raw)
        if not (0 <= product_index < len(products)):
            return "Invalid product index.", 400

        for field in fields:
            field_name = field['field_name']
            products[product_index][field_name] = request.form.get(field_name, '')

        save_products(products)
        return redirect('/manage_products')

    elif request.method == 'DELETE':
        product_index_raw = request.form.get('product_index')
        if product_index_raw is None or not product_index_raw.isdigit():
            return "Invalid product index.", 400
        product_index = int(product_index_raw)
        if not (0 <= product_index < len(products)):
            return "Invalid product index.", 400
        del products[product_index]
        save_products(products)
        return redirect('/manage_products')

    elif request.method == 'GET':
        product_index_raw = request.args.get('product_index', -1)
        try:
            product_index = int(product_index_raw)
            if 0 <= product_index < len(products):
                selected_product = products[product_index]
        except (ValueError, IndexError):
            selected_product = None

    search_product = request.args.get('search_product', '')

    return render_template('manage_products.html',
                           products=products,
                           fields=fields,
                           selected_product=selected_product,
                           product_index=product_index,
                           search_product=search_product)

@app.route('/download')
def download():
    return send_file(PRODUCT_FILE, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
