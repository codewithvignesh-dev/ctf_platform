"""
Bulk student import from Excel and credential export back to Excel.

Expected input columns (case-insensitive, order does not matter):
    Name | Register Number | Category

"Category" is optional per-row text (e.g. "1st Year", "2nd Year").
If omitted, the category selected on the upload form in the admin
panel is used for every row in the file.
"""
import io
from datetime import datetime

import openpyxl
from openpyxl.utils import get_column_letter

from models import db, User, Category
from utils.password_gen import generate_secure_password, generate_unique_username


def _find_column(header_row, *candidates):
    normalized = [str(h).strip().lower() if h else "" for h in header_row]
    for cand in candidates:
        if cand in normalized:
            return normalized.index(cand)
    return None


def import_students_from_excel(file_stream, default_category_id=None):
    """
    Parses the uploaded workbook, creates one User per row (skips rows whose
    register number already exists), and returns:
        (created_records, skipped_rows)

    created_records: list of dicts {name, reg_number, username, password, category}
    skipped_rows: list of dicts {row, reason}
    """
    wb = openpyxl.load_workbook(file_stream, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], [{"row": 0, "reason": "Empty file"}]

    header = rows[0]
    name_col = _find_column(header, "name", "student name")
    reg_col = _find_column(header, "register number", "reg number", "reg no", "registernumber", "register no.")
    cat_col = _find_column(header, "category", "year")

    if name_col is None or reg_col is None:
        return [], [{"row": 0, "reason": "Could not find 'Name' and 'Register Number' columns"}]

    created_records = []
    skipped_rows = []

    for idx, row in enumerate(rows[1:], start=2):
        if row is None or all(c is None for c in row):
            continue

        name = str(row[name_col]).strip() if row[name_col] else None
        reg_number = str(row[reg_col]).strip() if row[reg_col] else None

        if not name or not reg_number:
            skipped_rows.append({"row": idx, "reason": "Missing name or register number"})
            continue

        username = generate_unique_username(reg_number)

        existing = User.query.filter_by(username=username).first()
        if existing:
            skipped_rows.append({"row": idx, "reason": f"Register number {reg_number} already exists"})
            continue

        category_id = default_category_id
        category_name = None
        if cat_col is not None and row[cat_col]:
            cat_name = str(row[cat_col]).strip()
            category = Category.query.filter_by(name=cat_name).first()
            if not category:
                category = Category(name=cat_name)
                db.session.add(category)
                db.session.flush()
            category_id = category.id
            category_name = category.name
        elif default_category_id:
            cat_obj = Category.query.get(default_category_id)
            category_name = cat_obj.name if cat_obj else None

        raw_password = generate_secure_password()

        user = User(
            username=username,
            name=name,
            reg_number=reg_number,
            role="student",
            category_id=category_id,
        )
        user.set_password(raw_password)
        db.session.add(user)

        created_records.append({
            "name": name,
            "reg_number": reg_number,
            "username": username,
            "password": raw_password,
            "category": category_name or "-",
        })

    db.session.commit()
    return created_records, skipped_rows


def build_credentials_workbook(records):
    """Builds an in-memory .xlsx workbook of generated login credentials."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Credentials"

    headers = ["Name", "Register Number", "Username", "Password", "Category"]
    ws.append(headers)

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = openpyxl.styles.Font(bold=True, color="FFFFFF")
        cell.fill = openpyxl.styles.PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")

    for rec in records:
        ws.append([rec["name"], rec["reg_number"], rec["username"], rec["password"], rec["category"]])

    for i, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(16, len(header) + 4)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
