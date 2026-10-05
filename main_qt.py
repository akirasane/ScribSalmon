import sys

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import theme
from app.ui import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("ScribSalmon")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.ico")))
    app.setStyle("Fusion")  # consistent base; theme.QSS does the rest
    theme.apply(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
