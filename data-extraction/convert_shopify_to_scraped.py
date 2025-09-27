import json, os, re
from html import unescape

SRC = os.path.join('data', 'json', 'shopify_products.json')
OUT = os.path.join('data', 'scraped_data.json')
BASE_URL = 'https://b2b-demo-store.myshopify.com/products'  # change to real domain if you have it

def html_to_text(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_variant_label(title):
    if not title: return None, None
    parts = [p.strip() for p in title.split('/') if p is not None]
    if len(parts) == 1: return parts[0], None
    if len(parts) >= 2: return parts[0], parts[1]
    return None, None

def product_to_doc(p):
    title = (p.get('title') or '').strip()
    handle = p.get('handle') or re.sub(r'[^a-z0-9-]+', '-', title.lower())
    url = f"{BASE_URL}{handle}"
    body = html_to_text(p.get('body_html',''))

    low = body.lower()
    materials = None
    care = None
    for token in ['100% cotton','cotton','leather','stainless steel','handmade','wool','linen']:
        if token in low:
            materials = token
            break
    for token in ['machine washable','hand wash','dry clean','wash cold']:
        if token in low:
            care = token
            break

    variants = p.get('variants') or []
    var_lines = []
    var_struct = []
    prices = []
    for v in variants:
        label = v.get('title') or ''
        color, size = parse_variant_label(label)
        sku = v.get('sku') or ''
        price = v.get('price') or ''
        available = bool(v.get('available'))
        try:
            if price: prices.append(float(str(price)))
        except Exception:
            pass
        avail_txt = 'in stock' if available else 'out of stock'
        var_lines.append(f"{label} (SKU {sku}) {avail_txt}, price {price}")
        var_struct.append({
            'label': label, 'color': color, 'size': size,
            'sku': sku, 'price': str(price), 'available': available
        })
    best_price = f"{min(prices):.2f}" if prices else ''

    opts = p.get('options') or []
    opt_parts = []
    for o in opts:
        name = o.get('name','').strip()
        vals = ", ".join(o.get('values') or [])
        if name and vals:
            opt_parts.append(f"{name}: {vals}")

    lines = []
    if body: lines.append(body)
    qual = []
    if materials: qual.append(f"Material: {materials}")
    if care: qual.append(f"Care: {care}")
    if qual: lines.append(" ".join(qual))
    if var_lines: lines.append("Variants: " + "; ".join(var_lines))
    if opt_parts: lines.append("Options: " + "; ".join(opt_parts))
    content = ". ".join(lines).strip()

    return {
        "title": title or handle,
        "content": content,
        "url": url,
        "page_type": "product",
        "product_info": {
            "id": p.get('id'), "handle": handle, "vendor": p.get('vendor',''),
            "updated_at": p.get('updated_at',''),
            "best_price": best_price, "materials": materials or '', "care": care or '',
            "variants": var_struct
        }
    }

def main():
    os.makedirs('data', exist_ok=True)
    src = json.load(open(SRC,'r',encoding='utf-8'))
    products = src.get('products', [])
    docs = [product_to_doc(p) for p in products]
    json.dump(docs, open(OUT,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"Wrote {len(docs)} docs to {OUT}")

if __name__ == '__main__':
    main()
