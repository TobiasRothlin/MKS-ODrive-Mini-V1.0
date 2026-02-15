from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QHBoxLayout, QLabel, QLineEdit, QGridLayout
from PySide6.QtCore import Qt
import odrive

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ODrive GUI")
        self._setup()
        self.show()

    def _setup(self):
        self.odrive = odrive.find_any()  # find_any() is often more robust than find_sync()

        # Get serial number (hex format is usually easier to read)
        sn = hex(self.odrive.serial_number).upper().replace("0X", "")
        self.odrive_serial_number_label = QLabel(f"ODrive Serial Number: {sn}")

        # Correct way to get firmware version
        fw_major = self.odrive.fw_version_major
        fw_minor = self.odrive.fw_version_minor
        fw_rev = self.odrive.fw_version_revision

        version_str = f"{fw_major}.{fw_minor}.{fw_rev}"
        self.odrive_firmware_version_label = QLabel(f"ODrive Firmware Version: {version_str}")

        self.bottom_layout = QHBoxLayout()

        self.bottom_layout.addWidget(self.odrive_serial_number_label)
        self.bottom_layout.addWidget(self.odrive_firmware_version_label)

        self.central_widget = QWidget()
        self.central_layout = QVBoxLayout()

        self.central_layout.addLayout(self.bottom_layout)
        self.central_widget.setLayout(self.central_layout)
        self.setCentralWidget(self.central_widget)









app = QApplication([])
window = MainWindow()
app.exec()