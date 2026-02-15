import sys
import time
import odrive
from odrive.enums import *
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                               QWidget, QHBoxLayout, QLabel, QLineEdit, QGridLayout, QGroupBox)
from PySide6.QtCore import Qt, QThread, Signal, Slot
import pyqtgraph as pg

# Matplotlib-inspired "Matte" colors
MPL_BLUE = '#1f77b4'
MPL_ORANGE = '#ff7f0e'
MPL_GREEN = '#2ca02c'


class ODriveWorker(QThread):
    data_received = Signal(dict)
    connection_status = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.odrv = None
        self.running = True

    def run(self):
        while self.running:
            if self.odrv is None:
                try:
                    self.connection_status.emit(False, "Searching...")
                    self.odrv = odrive.find_any(timeout=2)
                    self.connection_status.emit(True, "Connected")
                except:
                    time.sleep(1)
                    continue
            try:
                # ODrive units: pos_estimate is in [turns], vel_estimate is in [turns/s]
                data = {
                    "vbus": self.odrv.vbus_voltage,
                    "pos": self.odrv.axis0.encoder.pos_estimate,
                    "vel": self.odrv.axis0.encoder.vel_estimate,
                    "shadow": self.odrv.axis0.encoder.shadow_count,
                    "error": self.odrv.axis0.error,
                    "enc_error": self.odrv.axis0.encoder.error,
                    "state": self.odrv.axis0.current_state,
                }
                self.data_received.emit(data)
                time.sleep(0.05)
            except:
                self.odrv = None
                self.connection_status.emit(False, "Disconnected")

    def clear_errors(self):
        if self.odrv:
            # Standard ODrive V3.6 clear error command
            self.odrv.axis0.error = 0
            self.odrv.axis0.encoder.error = 0
            self.odrv.axis0.motor.error = 0

    def update_config(self, cs_pin, cpr):
        if self.odrv:
            try:
                self.odrv.axis0.encoder.config.abs_spi_cs_gpio_pin = cs_pin
                self.odrv.axis0.encoder.config.mode = ENCODER_MODE_SPI_ABS_AMS
                self.odrv.axis0.encoder.config.cpr = cpr
                self.odrv.save_configuration()
                try:
                    self.odrv.reboot()
                except:
                    pass
                self.odrv = None
            except Exception as e:
                print(f"Config Error: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ODrive Telemetry - Pro View")
        self.resize(1200, 850)
        self.setStyleSheet("QMainWindow { background-color: #f5f5f5; } QGroupBox { font-weight: bold; }")

        self.max_points = 100
        self.vbus_data, self.pos_data, self.vel_data = [], [], []

        self._setup_ui()

        self.worker = ODriveWorker()
        self.worker.data_received.connect(self.update_telemetry)
        self.worker.connection_status.connect(self.update_status)
        self.worker.start()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left Panel (Controls & Labels)
        left_panel = QVBoxLayout()

        # 1. System Info
        info_group = QGroupBox("System Info")
        info_layout = QGridLayout()
        self.status_label = QLabel("Status: Searching...")
        self.vbus_label = QLabel("VBus: 0.00V")
        info_layout.addWidget(self.status_label, 0, 0)
        info_layout.addWidget(self.vbus_label, 1, 0)
        info_group.setLayout(info_layout)
        left_panel.addWidget(info_group)

        # 2. Encoder Data (Requested Telemetry)
        tele_group = QGroupBox("Live Encoder Telemetry")
        tele_layout = QVBoxLayout()
        self.label_shadow = QLabel("Shadow Count: 0")
        self.label_state = QLabel("Axis State: 0")
        self.label_error = QLabel("Axis Error: 0x0")
        self.label_enc_error = QLabel("Enc Error: 0x0")

        tele_layout.addWidget(self.label_shadow)
        tele_layout.addWidget(self.label_state)
        tele_layout.addWidget(self.label_error)
        tele_layout.addWidget(self.label_enc_error)

        self.clear_btn = QPushButton("Clear Errors")
        self.clear_btn.clicked.connect(lambda: self.worker.clear_errors())
        tele_layout.addWidget(self.clear_btn)

        tele_group.setLayout(tele_layout)
        left_panel.addWidget(tele_group)

        # 3. Setup Configuration
        config_group = QGroupBox("Encoder Hardware Config")
        cfg_grid = QGridLayout()
        self.cs_input = QLineEdit("7")
        self.cpr_input = QLineEdit("16384")
        cfg_grid.addWidget(QLabel("CS Pin:"), 0, 0)
        cfg_grid.addWidget(self.cs_input, 0, 1)
        cfg_grid.addWidget(QLabel("CPR:"), 1, 0)
        cfg_grid.addWidget(self.cpr_input, 1, 1)
        self.apply_btn = QPushButton("Save & Reboot")
        self.apply_btn.clicked.connect(self.apply_settings)
        cfg_grid.addWidget(self.apply_btn, 2, 0, 1, 2)
        config_group.setLayout(cfg_grid)
        left_panel.addWidget(config_group)

        left_panel.addStretch()
        main_layout.addLayout(left_panel, 1)

        # Right Panel (Plots)
        right_panel = QVBoxLayout()
        self.vbus_plot = pg.PlotWidget(title="Bus Voltage History")
        self.motion_plot = pg.PlotWidget(title="Motion Telemetry")

        self._style_plot(self.vbus_plot, "Voltage", "V")
        self._style_plot(self.motion_plot, "Value", "Turns")

        self.vbus_curve = self.vbus_plot.plot(pen=pg.mkPen(MPL_BLUE, width=2.5), name="VBus [V]")
        self.pos_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_ORANGE, width=2.5), name="Position [Turns]")
        self.vel_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_GREEN, width=2.5), name="Velocity [Turns/s]")

        right_panel.addWidget(self.vbus_plot)
        right_panel.addWidget(self.motion_plot)
        main_layout.addLayout(right_panel, 3)

    def _style_plot(self, plot_widget, y_name, unit):
        plot_widget.setBackground('w')
        plot_widget.showGrid(x=True, y=True, alpha=0.2)
        title_style = {'color': '#222', 'size': '12pt', 'bold': True}
        label_style = {'color': '#444', 'font-size': '10pt'}
        plot_widget.setTitle(plot_widget.plotItem.titleLabel.text, **title_style)
        plot_widget.setLabel('left', f"{y_name} ({unit})", **label_style)
        plot_widget.setLabel('bottom', "Time (Samples)", **label_style)
        plot_widget.addLegend(offset=(10, 10), labelTextColor='#333', brush=pg.mkBrush(255, 255, 255, 200))
        pen = pg.mkPen(color='#888', width=1)
        for axis in ['left', 'bottom']:
            ax = plot_widget.getAxis(axis)
            ax.setPen(pen)
            ax.setTextPen(pen)

    @Slot(dict)
    def update_telemetry(self, data):
        # Update Labels
        self.vbus_label.setText(f"VBus: {data['vbus']:.2f}V")
        self.label_shadow.setText(f"Shadow Count: {data['shadow']}")
        self.label_state.setText(f"Axis State: {data['state']}")
        self.label_error.setText(f"Axis Error: {hex(data['error'])}")
        self.label_enc_error.setText(f"Enc Error: {hex(data['enc_error'])}")

        # Update Plots
        self.vbus_data.append(data['vbus'])
        self.pos_data.append(data['pos'])
        self.vel_data.append(data['vel'])

        if len(self.vbus_data) > self.max_points:
            self.vbus_data.pop(0)
            self.pos_data.pop(0)
            self.vel_data.pop(0)

        self.vbus_curve.setData(self.vbus_data)
        self.pos_curve.setData(self.pos_data)
        self.vel_curve.setData(self.vel_data)

    @Slot(bool, str)
    def update_status(self, connected, message):
        self.status_label.setText(f"Status: {message}")
        self.apply_btn.setEnabled(connected)
        self.clear_btn.setEnabled(connected)

    def apply_settings(self):
        try:
            cs, cpr = int(self.cs_input.text()), int(self.cpr_input.text())
            self.worker.update_config(cs, cpr)
        except ValueError:
            pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())