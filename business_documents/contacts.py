"""Map the verified Access ARCUSFIL schema to reusable customer contacts."""


def currency(value):
    value = value.upper()
    return 'MYR' if value == 'RM' else value


def access_customer(raw):
    row = {str(key).upper(): value for key, value in raw.items()}

    def text(key):
        value = row.get(key)
        return '' if value is None else str(value).strip()

    code, name = text('CUS_NO'), text('CUS_NAME')
    if not code or not name:
        return None
    address = '\n'.join(filter(None, [text(key) for key in (
        'CUS_STREET1', 'CUS_STREET2', 'CUS_CITY', 'CUS_ST', 'CUS_ZIP', 'CUS_COUNTRY')]))
    details = '\n'.join(label + value for label, value in (
        ('Tel: ', text('CUS_PHONE_NO')), ('Tel 2: ', text('CUS_PHONE_NO_2')),
        ('Fax: ', text('CUS_FAX_NO')), ('Email: ', text('EMAIL_ADDR'))) if value)
    return {'_id': 'access:ARCUSFIL:' + code, 'customer_code': code, 'name': name,
            'address': address, 'contact': text('CUS_CONTACT'), 'details': details,
            'currency': currency(text('CUS_CURR_CODE')), 'terms': text('CUS_TERMS_CD'),
            '_source': 'access', 'source_table': 'ARCUSFIL'}


def access_supplier(raw):
    row = {str(k).upper(): '' if v is None else str(v).strip() for k, v in raw.items()}
    code = row.get('SPPL_CD') or row.get('SUPPLIER')
    name = row.get('NAME') or row.get('SUPPLIER')
    if not code or not name:
        return None
    address = '\n'.join(filter(None, [row.get(k) for k in ('ADDR1', 'ADDR2', 'ADDR3')]))
    details = '\n'.join(filter(None, [address,
        'Tel: ' + row['TEL'] if row.get('TEL') else '',
        'Email: ' + row['EMAIL'] if row.get('EMAIL') else '']))
    return {'_id': 'access:SUPPLIER:' + code, 'supplier_code': code, 'name': name,
            'details': details, 'attention': row.get('CONTACT', ''), 'fax': row.get('FAX', ''),
            'currency': currency(row.get('SPPL_CURR', '')), 'terms': row.get('TERM', ''),
            '_source': 'access', 'source_table': 'SUPPLIER'}
