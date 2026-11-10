import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import asistente  # noqa: E402


def test_id_corto_alfanumerico_y_sin_ambiguos():
    for _ in range(200):
        i = asistente.id_corto(set())
        assert len(i) == 3
        assert all(c in asistente.ALFABETO_ID for c in i)
        assert any(c.isalpha() for c in i) and any(c.isdigit() for c in i)


def test_nombre_no_repite_ids_del_registro(monkeypatch):
    monkeypatch.setattr(asistente, "id_corto", lambda usados, largo=3: "k7q" if "k7q" not in usados else "m4z")
    reg = [{"nombre": "io-motor-k7q"}]
    assert asistente.nombre_trabajador(Path("/x/Mi Motor"), reg) == "io-mi-motor-m4z"
