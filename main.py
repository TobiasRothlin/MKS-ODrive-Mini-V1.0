import sys
import time
import odrive
from odrive.enums import *
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                               QWidget, QHBoxLayout, QLabel, QLineEdit, QGridLayout,
                               QGroupBox, QComboBox, QSlider)
from PySide6.QtCore import Qt, QThread, Signal, Slot
import pyqtgraph as pg

# Matplotlib-inspired "Matte" colors
MPL_BLUE = '#1f77b4'
MPL_ORANGE = '#ff7f0e'
MPL_GREEN = '#2ca02c'
MPL_RED = '#d62728'


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

    def set_state(self, state_code):
        if self.odrv:
            self.odrv.axis0.requested_state = state_code

    def update_tuning(self, pos_g, vel_g, vel_i_g, mode):
        if self.odrv:
            self.odrv.axis0.controller.config.control_mode = mode
            self.odrv.axis0.controller.config.pos_gain = pos_g
            self.odrv.axis0.controller.config.vel_gain = vel_g
            self.odrv.axis0.controller.config.vel_integrator_gain = vel_i_g

    def set_input(self, value, is_pos_mode):
        if self.odrv:
            if is_pos_mode:
                self.odrv.axis0.controller.input_pos = value
            else:
                self.odrv.axis0.controller.input_vel = value

    def clear_errors(self):
        if self.odrv:
            self.odrv.axis0.error = 0
            self.odrv.axis0.encoder.error = 0
            self.odrv.axis0.motor.error = 0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ODrive MKS Pro-Tuning Interface")
        self.resize(1300, 900)
        self.setStyleSheet("QMainWindow { background-color: #f5f5f5; } QGroupBox { font-weight: bold; }")

        self.max_points = 100
        self.vbus_data, self.pos_data, self.vel_data = [], [], []

        # FIX: Define worker BEFORE setup_ui to avoid AttributeError
        self.worker = ODriveWorker()

        self._setup_ui()

        # Connect signals
        self.worker.data_received.connect(self.update_telemetry)
        self.worker.connection_status.connect(self.update_status)
        self.worker.start()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # --- LEFT PANEL ---
        left_panel = QVBoxLayout()

        # 1. System Status
        status_group = QGroupBox("System Status")
        status_layout = QVBoxLayout()
        self.status_label = QLabel("Status: Searching...")
        self.vbus_label = QLabel("VBus: 0.00V")
        self.estop_btn = QPushButton("EMERGENCY IDLE")
        self.estop_btn.setStyleSheet(
            f"background-color: {MPL_RED}; color: white; font-weight: bold; height: 40px; border-radius: 5px;")
        self.estop_btn.clicked.connect(lambda: self.worker.set_state(AXIS_STATE_IDLE))
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.vbus_label)
        status_layout.addWidget(self.estop_btn)
        status_group.setLayout(status_layout)
        left_panel.addWidget(status_group)

        # 2. Tuning & Control
        tune_group = QGroupBox("Control & Tuning")
        tune_layout = QGridLayout()
        self.mode_select = QComboBox()
        self.mode_select.addItems(["Position Control", "Velocity Control"])
        self.pos_g_input = QLineEdit("20.0")
        self.vel_g_input = QLineEdit("0.0005")
        self.vel_i_input = QLineEdit("0.001")

        tune_layout.addWidget(QLabel("Mode:"), 0, 0)
        tune_layout.addWidget(self.mode_select, 0, 1)
        tune_layout.addWidget(QLabel("Pos Gain:"), 1, 0)
        tune_layout.addWidget(self.pos_g_input, 1, 1)
        tune_layout.addWidget(QLabel("Vel Gain:"), 2, 0)
        tune_layout.addWidget(self.vel_g_input, 2, 1)
        tune_layout.addWidget(QLabel("Vel Int Gain:"), 3, 0)
        tune_layout.addWidget(self.vel_i_input, 3, 1)

        self.apply_tuning_btn = QPushButton("Apply Gains & Close Loop")
        self.apply_tuning_btn.clicked.connect(self.apply_tuning)
        tune_layout.addWidget(self.apply_tuning_btn, 4, 0, 1, 2)
        tune_group.setLayout(tune_layout)
        left_panel.addWidget(tune_group)

        # 3. Target Setpoint (Slider + Input Field)
        setpoint_group = QGroupBox("Target Setpoint")
        setpoint_layout = QVBoxLayout()

        input_row = QHBoxLayout()
        self.target_input = QLineEdit("0.0")
        self.target_input.setFixedWidth(80)
        self.target_input.returnPressed.connect(self.handle_manual_input)
        input_row.addWidget(QLabel("Setpoint Value:"))
        input_row.addWidget(self.target_input)
        input_row.addStretch()

        self.setpoint_slider = QSlider(Qt.Horizontal)
        self.setpoint_slider.setRange(-100, 100)  # -10.0 to 10.0
        self.setpoint_slider.valueChanged.connect(self.handle_slider_input)

        setpoint_layout.addLayout(input_row)
        setpoint_layout.addWidget(self.setpoint_slider)
        setpoint_group.setLayout(setpoint_layout)
        left_panel.addWidget(setpoint_group)

        # 4. Diagnostics
        diag_group = QGroupBox("Diagnostics")
        diag_layout = QVBoxLayout()
        self.label_shadow = QLabel("Shadow Count: 0")
        self.label_error = QLabel("Axis Error: 0x0")
        self.clear_btn = QPushButton("Clear Errors")
        self.clear_btn.clicked.connect(self.worker.clear_errors)
        diag_layout.addWidget(self.label_shadow)
        diag_layout.addWidget(self.label_error)
        diag_layout.addWidget(self.clear_btn)
        diag_group.setLayout(diag_layout)
        left_panel.addWidget(diag_group)

        left_panel.addStretch()
        main_layout.addLayout(left_panel, 1)

        # --- RIGHT PANEL (Plots & Big Labels) ---
        right_panel = QVBoxLayout()

        # Plots
        self.vbus_plot = pg.PlotWidget(title="Bus Voltage")
        self.motion_plot = pg.PlotWidget(title="Motion Telemetry")
        self._style_plot(self.vbus_plot, "V", "V")
        self._style_plot(self.motion_plot, "Value", "Turns")
        self.vbus_curve = self.vbus_plot.plot(pen=pg.mkPen(MPL_BLUE, width=2))
        self.pos_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_ORANGE, width=2), name="Position")
        self.vel_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_GREEN, width=2), name="Velocity")

        # Big Live Readouts (The labels you wanted back)
        readout_layout = QHBoxLayout()
        readout_style = "font-size: 16pt; font-weight: bold; padding: 10px; border: 1px solid #ccc; border-radius: 8px; background: white;"
        self.label_live_pos = QLabel("Pos: 0.000")
        self.label_live_vel = QLabel("Vel: 0.000")
        self.label_live_pos.setStyleSheet(readout_style + f" color: {MPL_ORANGE};")
        self.label_live_vel.setStyleSheet(readout_style + f" color: {MPL_GREEN};")
        readout_layout.addWidget(self.label_live_pos)
        readout_layout.addWidget(self.label_live_vel)

        right_panel.addWidget(self.vbus_plot, 1)
        right_panel.addWidget(self.motion_plot, 2)
        right_panel.addLayout(readout_layout)
        main_layout.addLayout(right_panel, 3)

    def _style_plot(self, plot, y_name, unit):
        plot.setBackground('w')
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel('left', y_name, units=unit)
        plot.addLegend(offset=(10, 10))

    # --- Target Handling ---
    def handle_slider_input(self, val):
        scaled_val = val / 10.0
        self.target_input.setText(str(scaled_val))
        self.send_target(scaled_val)

    def handle_manual_input(self):
        try:
            val = float(self.target_input.text())
            # Sync slider (multiply back)
            self.setpoint_slider.blockSignals(True)
            self.setpoint_slider.setValue(int(val * 10))
            self.setpoint_slider.blockSignals(False)
            self.send_target(val)
        except ValueError:
            pass

    def send_target(self, val):
        is_pos = self.mode_select.currentIndex() == 0
        self.worker.set_input(val, is_pos)

    def apply_tuning(self):
        try:
            pg = float(self.pos_g_input.text())
            vg = float(self.vel_g_input.text())
            vig = float(self.vel_i_input.text())
            mode = CONTROL_MODE_POSITION_CONTROL if self.mode_select.currentIndex() == 0 else CONTROL_MODE_VELOCITY_CONTROL
            self.worker.update_tuning(pg, vg, vig, mode)
            self.worker.set_state(AXIS_STATE_CLOSED_LOOP_CONTROL)
        except ValueError:
            print("Invalid gain values")

    @Slot(dict)
    def update_telemetry(self, data):
        # Update small and large labels
        self.vbus_label.setText(f"VBus: {data['vbus']:.2f}V")
        self.label_shadow.setText(f"Shadow: {data['shadow']}")
        self.label_error.setText(f"Error: {hex(data['error'])}")
        self.label_live_pos.setText(f"Pos: {data['pos']:.3f} Turns")
        self.label_live_vel.setText(f"Vel: {data['vel']:.3f} Turns/s")

        # Update History
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
        self.apply_tuning_btn.setEnabled(connected)
        self.estop_btn.setEnabled(connected)
        self.clear_btn.setEnabled(connected)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())