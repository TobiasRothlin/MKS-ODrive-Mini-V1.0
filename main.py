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


# Helper to reverse lookup enum names
def get_enum_name(enum_class, value):
    for name, val in enum_class.__dict__.items():
        if val == value:
            return name
    return str(value)


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

                    # --- NEW: Fetch current config once on connection ---
                    init_cfg = {
                        "pos_gain": self.odrv.axis0.controller.config.pos_gain,
                        "vel_gain": self.odrv.axis0.controller.config.vel_gain,
                        "vel_integrator_gain": self.odrv.axis0.controller.config.vel_integrator_gain,
                        "mode": self.odrv.axis0.controller.config.control_mode
                    }
                    self.data_received.emit({"init_config": init_cfg})
                    # ----------------------------------------------------

                    self.connection_status.emit(True, "Connected")
                except:
                    time.sleep(1)
                    continue
            try:
                data = {
                    "iq": self.odrv.axis0.motor.current_control.Iq_measured,
                    "vbus": self.odrv.vbus_voltage,
                    "pos": self.odrv.axis0.encoder.pos_estimate,
                    "vel": self.odrv.axis0.encoder.vel_estimate,
                    "shadow": self.odrv.axis0.encoder.shadow_count,
                    "error": self.odrv.axis0.error,
                    "enc_error": self.odrv.axis0.encoder.error,
                    "state": self.odrv.axis0.current_state,
                    "ctrl_mode": self.odrv.axis0.controller.config.control_mode,
                    "input_mode": self.odrv.axis0.controller.config.input_mode,
                }
                self.data_received.emit(data)
                time.sleep(0.05)
            except:
                self.odrv = None
                self.connection_status.emit(False, "Disconnected")

    def set_state(self, state_code):
        if self.odrv:
            self.odrv.axis0.requested_state = state_code

    # Inside ODriveWorker class
    def update_tuning(self, pos_g, vel_g, vel_i_g, vel_lim, mode):  # Added vel_lim
        if self.odrv:
            self.odrv.axis0.controller.config.control_mode = mode
            self.odrv.axis0.controller.config.input_mode = 1

            # Apply the limit here
            self.odrv.axis0.controller.config.vel_limit = vel_lim

            self.odrv.axis0.controller.config.pos_gain = pos_g
            self.odrv.axis0.controller.config.vel_gain = vel_g
            self.odrv.axis0.controller.config.vel_integrator_gain = vel_i_g

            self.odrv.axis0.controller.input_pos = self.odrv.axis0.encoder.pos_estimate
            self.odrv.axis0.controller.input_vel = 0

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
            try:
                self.odrv.clear_errors()
            except:
                pass

    def reboot(self):
        if self.odrv:
            try:
                self.odrv.reboot()
            except:
                pass
            self.odrv = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ODrive MKS Pro-Tuning Interface")
        self.resize(1300, 900)
        self.setStyleSheet("QMainWindow { background-color: #f5f5f5; } QGroupBox { font-weight: bold; }")

        self.max_points = 200
        self.vbus_data, self.pos_data, self.vel_data, self.iq_data = [], [], [], [] # Added iq_data
        self.current_axis_state = 0  # Default to undefined

        self.worker = ODriveWorker()
        self._setup_ui()

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
        self.current_label = QLabel("Motor Current: 0.00 A")
        self.power_label = QLabel("Power: 0.00 W")
        self.estop_btn = QPushButton("EMERGENCY IDLE")
        self.estop_btn.setStyleSheet(
            f"background-color: {MPL_RED}; color: white; font-weight: bold; height: 40px; border-radius: 5px;")
        self.estop_btn.clicked.connect(lambda: self.worker.set_state(AXIS_STATE_IDLE))
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.vbus_label)
        status_layout.addWidget(self.estop_btn)
        status_layout.addWidget(self.current_label)
        status_layout.addWidget(self.power_label)
        status_group.setLayout(status_layout)
        left_panel.addWidget(status_group)

        # 2. Tuning & Control
        tune_group = QGroupBox("Control & Tuning")
        tune_layout = QGridLayout()
        self.mode_select = QComboBox()
        self.mode_select.addItems(["Position Control", "Velocity Control"])
        self.mode_select.currentIndexChanged.connect(self.update_slider_limits)
        self.pos_g_input = QLineEdit("20.0")
        self.vel_g_input = QLineEdit("0.0005")
        self.vel_i_input = QLineEdit("0.001")
        self.vel_lim_input = QLineEdit("2.0")  # Default 2.0 turns/s

        tune_layout.addWidget(QLabel("Mode:"), 0, 0)
        tune_layout.addWidget(self.mode_select, 0, 1)
        tune_layout.addWidget(QLabel("Pos Gain:"), 1, 0)
        tune_layout.addWidget(self.pos_g_input, 1, 1)
        tune_layout.addWidget(QLabel("Vel Gain:"), 2, 0)
        tune_layout.addWidget(self.vel_g_input, 2, 1)
        tune_layout.addWidget(QLabel("Vel Int Gain:"), 3, 0)
        tune_layout.addWidget(self.vel_i_input, 3, 1)
        tune_layout.addWidget(QLabel("Vel Limit:"), 4, 0)  # Adjust row numbers
        tune_layout.addWidget(self.vel_lim_input, 4, 1)

        self.apply_tuning_btn = QPushButton("Apply Gains & Close Loop")
        self.apply_tuning_btn.clicked.connect(self.apply_tuning)
        tune_layout.addWidget(self.apply_tuning_btn, 5, 0, 1, 2)
        tune_group.setLayout(tune_layout)
        left_panel.addWidget(tune_group)

        # 3. Target Setpoint
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
        self.setpoint_slider.setRange(-1000, 1000)

        self.setpoint_slider.valueChanged.connect(self.handle_slider_input)
        setpoint_layout.addLayout(input_row)
        setpoint_layout.addWidget(self.setpoint_slider)
        setpoint_group.setLayout(setpoint_layout)
        left_panel.addWidget(setpoint_group)

        # 4. Diagnostics & Tools
        diag_group = QGroupBox("Diagnostics & Tools")
        diag_layout = QVBoxLayout()

        # New Toggle Button
        self.toggle_ctrl_btn = QPushButton("ENABLE CONTROL")
        self.toggle_ctrl_btn.setStyleSheet("font-weight: bold; height: 30px;")
        self.toggle_ctrl_btn.clicked.connect(self.handle_toggle_control)

        self.label_state = QLabel("State: N/A")
        self.label_ctrl_mode = QLabel("Ctrl Mode: N/A")
        self.label_inp_mode = QLabel("Inp Mode: N/A")
        self.label_shadow = QLabel("Shadow Count: 0")
        self.label_error = QLabel("Axis Error: 0x0")

        self.clear_btn = QPushButton("Clear Errors")
        self.clear_btn.clicked.connect(self.worker.clear_errors)

        self.reboot_btn = QPushButton("Reboot ODrive")
        self.reboot_btn.clicked.connect(self.handle_reboot)

        # Add widgets to layout
        diag_layout.addWidget(self.toggle_ctrl_btn)
        diag_layout.addSpacing(10)

        diag_style = "font-family: monospace; font-size: 10pt;"
        for lbl in [self.label_state, self.label_ctrl_mode, self.label_inp_mode, self.label_shadow, self.label_error]:
            lbl.setStyleSheet(diag_style)
            diag_layout.addWidget(lbl)

        diag_layout.addWidget(self.clear_btn)
        diag_layout.addWidget(self.reboot_btn)
        diag_group.setLayout(diag_layout)
        left_panel.addWidget(diag_group)

        left_panel.addStretch()
        main_layout.addLayout(left_panel, 1)

        # --- RIGHT PANEL ---
        right_panel = QVBoxLayout()
        self.vbus_plot = pg.PlotWidget(title="Bus Voltage")
        self.iq_plot = pg.PlotWidget(title="IQ Current")  # Added IQ plot
        self.motion_plot = pg.PlotWidget(title="Motion Telemetry")
        self._style_plot(self.vbus_plot, "V", "V")
        self._style_plot(self.motion_plot, "Value", "Turns")
        self._style_plot(self.iq_plot, "A", "A")
        self.vbus_curve = self.vbus_plot.plot(pen=pg.mkPen(MPL_BLUE, width=2))

        self.iq_curve = self.iq_plot.plot(pen=pg.mkPen(MPL_RED, width=2))  # Added IQ curve
        self.power_curve = self.iq_plot.plot(pen=pg.mkPen(MPL_ORANGE, width=2))  # Added Power curve (scaled IQ for visualization)

        self.pos_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_ORANGE, width=2), name="Position")
        self.vel_curve = self.motion_plot.plot(pen=pg.mkPen(MPL_GREEN, width=2), name="Velocity")

        readout_layout = QHBoxLayout()
        readout_style = "font-size: 16pt; font-weight: bold; padding: 10px; border: 1px solid #ccc; border-radius: 8px; background: white;"
        self.label_live_pos = QLabel("Pos: 0.000")
        self.label_live_vel = QLabel("Vel: 0.000")
        self.label_live_pos.setStyleSheet(readout_style + f" color: {MPL_ORANGE};")
        self.label_live_vel.setStyleSheet(readout_style + f" color: {MPL_GREEN};")
        readout_layout.addWidget(self.label_live_pos)
        readout_layout.addWidget(self.label_live_vel)

        right_panel.addWidget(self.vbus_plot, 1)
        right_panel.addWidget(self.iq_plot, 1)  # Added IQ plot to right panel
        right_panel.addWidget(self.motion_plot, 2)
        right_panel.addLayout(readout_layout)
        main_layout.addLayout(right_panel, 3)

    def _style_plot(self, plot, y_name, unit):
        plot.setBackground('w')
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel('left', y_name, units=unit)
        plot.addLegend(offset=(10, 10))

    def handle_slider_input(self, val):
        scaled_val = val / 100.0
        self.target_input.setText(str(scaled_val))
        self.send_target(scaled_val)

    def handle_manual_input(self):
        try:
            val = float(self.target_input.text())
            self.setpoint_slider.blockSignals(True)
            self.setpoint_slider.setValue(int(val * 100))
            self.setpoint_slider.blockSignals(False)
            self.send_target(val)
        except ValueError:
            pass

    def send_target(self, val):
        # Index 0 is Position, Index 1 is Velocity
        is_pos_mode = (self.mode_select.currentIndex() == 0)

        if is_pos_mode:
            # Tell worker to set input_pos
            self.worker.set_input(val, True)
        else:
            # Tell worker to set input_vel
            self.worker.set_input(val, False)

    def update_slider_limits(self, index):
        self.setpoint_slider.blockSignals(True)
        if index == 0:  # Position
            self.setpoint_slider.setRange(-100, 100)  # -10.0 to 10.0 Turns
            self.target_input.setText("0.0")
        else:  # Velocity
            self.setpoint_slider.setRange(-500, 500)  # -5.0 to 5.0 Turns/s
            self.target_input.setText("0.0")
        self.setpoint_slider.setValue(0)
        self.setpoint_slider.blockSignals(False)

    def apply_tuning(self):
        try:
            self.worker.clear_errors()

            pg_val = float(self.pos_g_input.text())
            vg_val = float(self.vel_g_input.text())
            vig_val = float(self.vel_i_input.text())
            vlim_val = float(self.vel_lim_input.text())  # Get the limit

            mode = CONTROL_MODE_POSITION_CONTROL if self.mode_select.currentIndex() == 0 else CONTROL_MODE_VELOCITY_CONTROL

            # Pass vlim_val to the worker
            self.worker.update_tuning(pg_val, vg_val, vig_val, vlim_val, mode)

            time.sleep(0.1)
            self.worker.set_state(AXIS_STATE_CLOSED_LOOP_CONTROL)
        except ValueError:
            print("Invalid numerical values")

    def handle_toggle_control(self):
        if self.current_axis_state == 8:  # CLOSED_LOOP
            self.worker.set_state(1)  # IDLE
        else:
            self.apply_tuning()  # Apply gains and enter CLOSED_LOOP

    def handle_reboot(self):
        self.worker.reboot()
        self.status_label.setText("Status: Rebooting...")

    @Slot(dict)
    def update_telemetry(self, data):
        if "init_config" in data:
            cfg = data["init_config"]
            self.pos_g_input.setText(f"{cfg['pos_gain']:.4f}")
            self.vel_g_input.setText(f"{cfg['vel_gain']:.6f}")
            self.vel_i_input.setText(f"{cfg['vel_integrator_gain']:.6f}")

            # Sync the dropdown mode
            # 1 = Pos, 3 = Vel (standard ODrive enums)
            mode_idx = 0 if cfg['mode'] == 1 else 1
            self.mode_select.setCurrentIndex(mode_idx)
            return  # Don't process the rest of telemetry for this packet


        self.current_axis_state = data['state']

        # Update Toggle Button Appearance
        if data['state'] == 8:  # CLOSED_LOOP
            self.toggle_ctrl_btn.setText("DISABLE CONTROL (IDLE)")
            self.toggle_ctrl_btn.setStyleSheet(
                "background-color: #d32f2f; color: white; font-weight: bold; height: 30px;")
        else:
            self.toggle_ctrl_btn.setText("ENABLE CLOSED LOOP")
            self.toggle_ctrl_btn.setStyleSheet(
                "background-color: #388E3C; color: white; font-weight: bold; height: 30px;")

        # Update labels
        states = {0: "UNDEFINED", 1: "IDLE", 8: "CLOSED_LOOP"}
        state_text = states.get(data['state'], f"State: {data['state']}")
        self.label_state.setText(f"State: {state_text}")

        ctrl_modes = {1: "VOLTAGE", 2: "TORQUE", 3: "VELOCITY", 4: "POSITION"}
        self.label_ctrl_mode.setText(f"Ctrl Mode: {ctrl_modes.get(data['ctrl_mode'], data['ctrl_mode'])}")
        self.label_inp_mode.setText(f"Inp Mode: {data['input_mode']}")

        current_amps = data['iq']
        bus_voltage = data['vbus']
        power_watts = bus_voltage * abs(current_amps)  # If using ibus for input power

        self.current_label.setText(f"Motor Current: {current_amps:.2f} A")
        self.power_label.setText(f"Power: {power_watts:.1f} W")

        self.vbus_label.setText(f"VBus: {data['vbus']:.2f}V")
        self.label_shadow.setText(f"Shadow: {data['shadow']}")
        self.label_error.setText(f"Error: {hex(data['error'])}")
        self.label_live_pos.setText(f"Pos: {data['pos']:.3f} Turns")
        self.label_live_vel.setText(f"Vel: {data['vel']:.3f} Turns/s")

        # History updates for plots
        self.iq_data.append(data['iq'])
        self.vbus_data.append(data['vbus'])
        self.pos_data.append(data['pos'])
        self.vel_data.append(data['vel'])

        # Keep list sizes managed
        if len(self.iq_data) > self.max_points:
            self.iq_data.pop(0)
            self.vbus_data.pop(0)
            self.pos_data.pop(0)
            self.vel_data.pop(0)

        # Update the curves
        self.iq_curve.setData(self.iq_data)
        self.vbus_curve.setData(self.vbus_data)
        self.pos_curve.setData(self.pos_data)
        self.vel_curve.setData(self.vel_data)

    @Slot(bool, str)
    def update_status(self, connected, message):
        self.status_label.setText(f"Status: {message}")
        self.apply_tuning_btn.setEnabled(connected)
        self.estop_btn.setEnabled(connected)
        self.clear_btn.setEnabled(connected)
        self.toggle_ctrl_btn.setEnabled(connected)
        self.reboot_btn.setEnabled(connected)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())