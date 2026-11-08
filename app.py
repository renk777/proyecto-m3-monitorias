"""Punto de entrada: `python app.py` inicia el servidor en http://127.0.0.1:3000."""
import os

from monitorias import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "3000")), debug=False)
