import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_QML_PROTOTYPE = os.path.join(_HERE, "qml_prototype")

import PySide6


def _register_qt_dll_dirs():
    if sys.platform != "win32":
        return
    add_dll_dir = getattr(os, "add_dll_directory", None)
    if add_dll_dir is None:
        return
    base = os.path.dirname(PySide6.__file__)
    for cand in (os.path.join(base, "Qt", "bin"),
                 os.path.join(base, "Qt6", "bin"),
                 os.path.join(base, "bin"),
                 base):
        if os.path.isdir(cand):
            try:
                add_dll_dir(cand)
            except Exception:
                pass


_register_qt_dll_dirs()

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from qml_prototype.backend import Backend
from storage import init_db


def _pyside_qml_dirs():
    base = os.path.dirname(PySide6.__file__)
    candidates = [
        os.path.join(base, "Qt", "qml"),
        os.path.join(base, "Qt6", "qml"),
    ]
    return [d for d in candidates if os.path.isdir(d)]


def main():
    init_db()
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    for qml_dir in _pyside_qml_dirs():
        engine.addImportPath(qml_dir)
    backend = Backend()
    app.aboutToQuit.connect(backend.shutdown)
    engine.rootContext().setContextProperty("backend", backend)
    qml_path = os.path.join(_QML_PROTOTYPE, "qml", "main.qml")
    engine.load(qml_path)
    if not engine.rootObjects():
        print("ERROR: QML gagal dimuat. Cek instalasi PySide6:",
              file=sys.stderr)
        print(f"  PySide6 di: {os.path.dirname(PySide6.__file__)}",
              file=sys.stderr)
        print(f"  Folder QML yang ditemukan: {_pyside_qml_dirs()}",
              file=sys.stderr)
        print(f"  Import path engine: {engine.importPathList()}",
              file=sys.stderr)
        print("  Kalau daftar di atas kosong / tidak ada QtQuick, "
              "instalasi PySide6-nya tidak lengkap. Perbaiki dengan:",
              file=sys.stderr)
        print("    python -m pip uninstall -y PySide6 PySide6-Essentials "
              "PySide6-Addons shiboken6", file=sys.stderr)
        print("    python -m pip install --force-reinstall PySide6",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
