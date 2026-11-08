"""Lectura de archivos CSV/XLSX (reportes DARP) y sugerencia de mapeo de columnas."""
import csv
import io
import unicodedata


def cell_text(value):
    """Texto limpio de una celda; los números enteros de Excel (1001.0) pierden el decimal."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_import(upload):
    """Devuelve (encabezados, filas) de un CSV (`,` `;` o tabulación) o XLSX."""
    filename = upload.filename.lower()
    if filename.endswith(".csv"):
        raw = upload.stream.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        first_line = text.splitlines()[0] if text.strip() else ""
        delimiter = max((",", ";", "\t"), key=first_line.count)
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
        return [(h or "").strip() for h in (reader.fieldnames or [])], rows
    if filename.endswith(".xlsx"):
        from openpyxl import load_workbook
        workbook = load_workbook(upload, read_only=True, data_only=True)
        values = list(workbook.active.values)
        headers = [cell_text(value) for value in values[0]] if values else []
        rows = [dict(zip(headers, [cell_text(value) for value in values_row])) for values_row in values[1:]]
        return headers, rows
    raise ValueError("Solo se aceptan archivos CSV o XLSX.")


def _plain(text):
    """Minúsculas y sin tildes, para comparar encabezados."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def suggested_mapping(headers):
    """Propone qué columna del archivo corresponde a cada campo del sistema."""
    def find(*terms):
        return next((h for h in headers if any(term in _plain(h) for term in terms)), "")
    return {
        "document": find("documento", "cedula", "identificacion"), "name": find("nombre", "estudiante"),
        "email": find("correo", "email"), "phone": find("celular", "telefono"), "program": find("programa"),
        "semester": find("semestre"), "course": find("curso", "materia", "asignatura"),
        "caseType": find("tipo", "caso"), "difficulty": find("dificultad"),
    }
