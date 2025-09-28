import json, os, re
from html import unescape
from typing import Tuple, List, Dict, Any

# Paths resolved relative to this file for robustness
CUR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(CUR, '..'))
SRC = os.path.normpath(os.path.join(ROOT,'data-extraction', 'data', 'json', 'shopify_products.json'))
OUT = os.path.normpath(os.path.join(ROOT,'data-extraction',  'data', 'scraped_data.json'))

# Change base to the real storefront if needed; keep trailing slash
PRODUCT_BASE_URL = 'https://b2b-demo-store.myshopify.com/products/'

def html_to_text(html: str) -> str:
    """Lightweight HTML to text cleanup."""
    html = html or ''
    text = re.sub(r'<[^>]+>', ' ', html)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text  # For complex HTML, consider BeautifulSoup as an enhancement. [web:711]

def parse_variant_label(label: str) -> Tuple[str, str]:
    """Extract color and size from a variant label like 'Blue / Medium'."""
    if not label:
        return None, None
    parts = [p.strip() for p in label.split('/') if p is not None]
    if len(parts) == 1:
        return parts[0] or None, None
    if len(parts) >= 2:
        return parts[0] or None, parts[1] or None
    return None, None

def safe_list(x):
    return x if isinstance(x, list) else []

def safe_str(x):
    return '' if x is None else str(x)

def build_price_summary(prices: List[float]) -> Tuple[str, str, str]:
    if not prices:
        return '', '', ''
    lo = min(prices)
    hi = max(prices)
    best = f"{lo:.2f}"
    maxp = f"{hi:.2f}"
    prange = best if abs(hi - lo) < 1e-6 else f"{best}–{maxp}"
    return best, maxp, prange  # min, max, range

def extract_metafields(p: Dict[str, Any]) -> Dict[str, str]:
    """Pull common metafields if present in the source JSON."""
    fields = {'materials': '', 'care': '', 'warranty': '', 'shipping_info': '', 'size_chart_url': ''}
    # Accept several shapes: p['metafields'] as array of {namespace,key,value}, or p['metafields'] as dict, or custom keys.
    mf = p.get('metafields')
    if isinstance(mf, list):
        for m in mf:
            key = f"{m.get('namespace','')}.{m.get('key','')}".lower()
            val = safe_str(m.get('value','')).strip()
            if not val:
                continue
            if 'material' in key:
                fields['materials'] = val
            elif 'care' in key or 'wash' in key:
                fields['care'] = val
            elif 'warranty' in key or 'guarantee' in key:
                fields['warranty'] = val
            elif 'shipping' in key or 'delivery' in key:
                fields['shipping_info'] = val
            elif 'size_chart' in key or 'sizechart' in key:
                fields['size_chart_url'] = val
    elif isinstance(mf, dict):
        # Flat dictionary of custom fields
        for k, v in mf.items():
            lk = k.lower()
            val = safe_str(v).strip()
            if not val:
                continue
            if 'material' in lk:
                fields['materials'] = val
            elif 'care' in lk or 'wash' in lk:
                fields['care'] = val
            elif 'warranty' in lk or 'guarantee' in lk:
                fields['warranty'] = val
            elif 'shipping' in lk or 'delivery' in lk:
                fields['shipping_info'] = val
            elif 'size_chart' in lk or 'sizechart' in lk:
                fields['size_chart_url'] = val

    # Fallback: mine body_html if metafields absent
    body_text_low = html_to_text(p.get('body_html','')).lower()
    if not fields['materials']:
        for token in ['100% cotton','cotton','leather','stainless steel','handmade','wool','linen','silk','polyester']:
            if token in body_text_low:
                fields['materials'] = token
                break
    if not fields['care']:
        for token in ['machine washable','hand wash','dry clean','wash cold','do not bleach']:
            if token in body_text_low:
                fields['care'] = token
                break
    return fields  # Metafields carry store-specific details like materials/care/warranty/shipping. [web:690][web:717]

def product_to_doc(p: Dict[str, Any]) -> Dict[str, Any]:
    title = (p.get('title') or '').strip()
    handle = p.get('handle') or re.sub(r'[^a-z0-9-]+', '-', title.lower())
    url = f"{PRODUCT_BASE_URL}{handle}"

    vendor = p.get('vendor','')
    product_type = p.get('product_type','')
    tags = safe_list(p.get('tags')) if isinstance(p.get('tags'), list) else [t.strip() for t in safe_str(p.get('tags','')).split(',') if t.strip()]
    created_at = p.get('created_at','')
    updated_at = p.get('updated_at','')

    body = html_to_text(p.get('body_html',''))

    # Options
    options_in = safe_list(p.get('options'))
    options_out = []
    for o in options_in:
        options_out.append({
            'name': o.get('name',''),
            'position': o.get('position', None),
            'values': safe_list(o.get('values'))
        })

    # Images
    images_in = safe_list(p.get('images'))
    images_out = []
    for img in images_in:
        images_out.append({
            'src': img.get('src',''),
            'alt': img.get('alt','') or img.get('altText','') or '',
            'position': img.get('position', None),
            'id': img.get('id')
        })
    # Featured image first if present
    if images_out:
        images_out.sort(key=lambda x: (x.get('position') is None, x.get('position', 1e9)))

    # Variants
    variants_in = safe_list(p.get('variants'))
    variant_lines = []
    variant_struct = []
    price_list = []
    for v in variants_in:
        label = v.get('title') or ''
        color, size = parse_variant_label(label)
        sku = v.get('sku') or ''
        barcode = v.get('barcode') or ''
        price = safe_str(v.get('price'))
        compare_at_price = safe_str(v.get('compare_at_price') or '')
        # availability/inventory
        inv_qty = v.get('inventory_quantity')
        available = bool(v.get('available')) if v.get('available') is not None else (inv_qty is None or inv_qty > 0)
        # weight
        weight = v.get('weight')
        weight_unit = v.get('weight_unit') or v.get('weightUnit') or ''
        requires_shipping = bool(v.get('requires_shipping')) if v.get('requires_shipping') is not None else True
        taxable = bool(v.get('taxable')) if v.get('taxable') is not None else True
        image_id = v.get('image_id')
        # find image src if image_id matches
        image_src = ''
        if image_id and images_in:
            for img in images_in:
                if str(img.get('id')) == str(image_id):
                    image_src = img.get('src','')
                    break

        try:
            if price:
                price_list.append(float(str(price)))
        except Exception:
            pass

        avail_txt = 'in stock' if available else 'out of stock'
        line = f"{label} (SKU {sku}) {avail_txt}, price {price}"
        if compare_at_price:
            line += f" (was {compare_at_price})"
        if size:
            line += f", size {size}"
        variant_lines.append(line)

        variant_struct.append({
            'id': v.get('id'),
            'label': label,
            'color': color,
            'size': size,
            'sku': sku,
            'barcode': barcode,
            'price': price,
            'compare_at_price': compare_at_price,
            'available': available,
            'inventory_quantity': inv_qty if inv_qty is not None else None,
            'weight': weight,
            'weight_unit': weight_unit,
            'requires_shipping': requires_shipping,
            'taxable': taxable,
            'image_src': image_src
        })

    best_price, max_price, price_range = build_price_summary(price_list)

    # Metafields and policy-like info
    mf = extract_metafields(p)
    materials = mf['materials']
    care = mf['care']
    warranty = mf['warranty']
    shipping_info = mf['shipping_info']
    size_chart_url = mf['size_chart_url']

    # Build enriched content
    lines = []
    if body:
        lines.append(body)
    facts = []
    if materials:
        facts.append(f"Materials: {materials}")
    if care:
        facts.append(f"Care: {care}")
    if warranty:
        facts.append(f"Warranty: {warranty}")
    if shipping_info:
        facts.append(f"Shipping: {shipping_info}")
    if facts:
        lines.append("; ".join(facts))
    if variant_lines:
        lines.append("Variants: " + "; ".join(variant_lines))
    if options_out:
        # concise options line
        opt_parts = []
        for o in options_out:
            name = o['name']
            vals = ", ".join(o['values']) if o['values'] else ''
            if name and vals:
                opt_parts.append(f"{name}: {vals}")
        if opt_parts:
            lines.append("Options: " + "; ".join(opt_parts))
    # vendor/type/tags for more recall
    vt = []
    if vendor: vt.append(f"Vendor: {vendor}")
    if product_type: vt.append(f"Type: {product_type}")
    if tags: vt.append("Tags: " + ", ".join(tags))
    if vt:
        lines.append("; ".join(vt))
    content = ". ".join([s for s in lines if s]).strip()

    return {
        "title": title or handle,
        "content": content,
        "url": url,
        "page_type": "product",
        "product_info": {
            "id": p.get('id'),
            "handle": handle,
            "title": title,
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags,
            "created_at": created_at,
            "updated_at": updated_at,
            "url": url,
            "images": images_out,
            "options": options_out,
            "variants": variant_struct,
            "best_price": best_price,
            "max_price": max_price,
            "price_range": price_range,
            "materials": materials,
            "care": care,
            "warranty": warranty,
            "shipping_info": shipping_info,
            "size_chart_url": size_chart_url
        }
    }  # Includes core fields, variants, images, and metafields for richer Q&A. [web:687][web:690][web:676]

def main():
    if not os.path.exists(SRC):
        raise FileNotFoundError(f"Missing source file: {SRC}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    src = json.load(open(SRC, 'r', encoding='utf-8'))
    products = src.get('products', []) if isinstance(src, dict) else src
    docs = [product_to_doc(p) for p in products]
    json.dump(docs, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"Wrote {len(docs)} docs to {OUT}")

if __name__ == '__main__':
    main()
