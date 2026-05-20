"""
Keithley 2450 + Cryoboss cryogenic resistance automation
=========================================================

Single-file PyQt6 application.

Main idea:
- Python/PyQt6 controls the GUI, scheduler, Cryoboss CSV parsing, saving, and plotting.
- Keithley 2450 runs the fast inner resistance measurement block using TSP.
- The app measures resistance while the cryostat temperature is inside a scheduled range.

Before running:
    pip install pyvisa PyQt6 pyqtgraph numpy pandas matplotlib

Optional, for HTML plots:
    pip install plotly

Important:
- Set the Keithley 2450 command set to TSP before using this program.
- For LAN raw socket, use port 5025.
- This program assumes Cryoboss writes a CSV that contains temperature in one column.
  You can set the temperature column index in the GUI.

Author note:
This is a first complete working architecture. You will probably need to adjust the
Cryoboss CSV parser after seeing the exact Cryoboss column format.
"""

import csv
import math
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyvisa

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer, QFileSystemWatcher, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# Constants and folders
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
CSV_DIR = SCRIPT_DIR / "csv"
PLOTS_DIR = SCRIPT_DIR / "plots"

CSV_DIR.mkdir(exist_ok=True)
PLOTS_DIR.mkdir(exist_ok=True)


# ============================================================
# Helper functions
# ============================================================


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        text = str(value).strip().replace("\ufeff", "")
        if text == "":
            return default
        return float(text)
    except Exception:
        return default


def format_float_for_name(value: float, digits: int = 3) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return text.replace("-", "minus").replace(".", "p")


def make_resource_name(user_text: str) -> str:
    """
    Accept either a full VISA resource string or just an IP address.
    Examples:
        192.168.1.50 -> TCPIP0::192.168.1.50::5025::SOCKET
        TCPIP0::192.168.1.50::5025::SOCKET -> unchanged
        USB0::0x05e6::0x2450::...::INSTR -> unchanged
    """
    text = user_text.strip()
    if "::" in text:
        return text
    return f"TCPIP0::{text}::5025::SOCKET"


def inside_temperature_range(temp_mk: float, start_mk: float, stop_mk: float) -> bool:
    low = min(start_mk, stop_mk)
    high = max(start_mk, stop_mk)
    return low <= temp_mk <= high


def should_start_measurement(
    previous_temp_mk: Optional[float],
    current_temp_mk: float,
    start_mk: float,
    stop_mk: float,
) -> bool:
    """
    Start whenever the temperature enters the selected range.
    This works for both heating and cooling.
    """
    if previous_temp_mk is None:
        return inside_temperature_range(current_temp_mk, start_mk, stop_mk)

    was_inside = inside_temperature_range(previous_temp_mk, start_mk, stop_mk)
    is_inside = inside_temperature_range(current_temp_mk, start_mk, stop_mk)
    return (not was_inside) and is_inside


def should_stop_measurement(current_temp_mk: float, start_mk: float, stop_mk: float) -> bool:
    """
    Stop when the temperature leaves the selected range.
    This works for both heating and cooling.
    """
    return not inside_temperature_range(current_temp_mk, start_mk, stop_mk)


def infer_temperature_direction(previous_temp_mk: Optional[float], current_temp_mk: Optional[float]) -> str:
    if previous_temp_mk is None or current_temp_mk is None:
        return "unknown"
    delta = current_temp_mk - previous_temp_mk
    if abs(delta) < 1e-6:
        return "stable"
    return "heating" if delta > 0 else "cooling"


# ============================================================
# Data structures
# ============================================================


@dataclass
class MeasurementTask:
    start_temp_mk: float
    stop_temp_mk: float
    source_current_a: float
    voltage_limit_v: float
    nplc: float
    readings_per_point: int
    interval_s: float
    four_wire: bool
    offset_compensation: bool
    source_readback: bool
    name: str = ""

    def folder_stem(self) -> str:
        label = self.name.strip() or "R_vs_T"
        start = format_float_for_name(self.start_temp_mk, 1)
        stop = format_float_for_name(self.stop_temp_mk, 1)
        current = format_float_for_name(self.source_current_a, 9)
        return f"{now_string()}_{label}_{start}mK_to_{stop}mK_both_I{current}A"


@dataclass
class MeasurementPoint:
    pc_time: str
    elapsed_s: float
    temperature_mk: float
    temperature_k: float
    resistance_ohm: float
    resistance_std_ohm: float
    readings_per_point: int
    source_current_a: float
    voltage_limit_v: float
    nplc: float
    direction: str
    status: str


# ============================================================
# TSP script builder
# ============================================================


def tsp_bool(value: bool) -> str:
    return "smu.ON" if value else "smu.OFF"


def build_tsp_helper_script() -> List[str]:
    """
    This script defines one function on the Keithley:
        cryo_measure_point()

    It takes raw readings continuously for duration_s seconds.
    The readings stay in defbuffer1. Python then fetches the whole buffer.

    This is different from taking one reading, waiting 10 s, and repeating.
    Here, the Keithley measures as fast as the configured NPLC/settings allow
    for the full block duration, then Python receives the batch.
    """
    return [
        "loadscript cryo_helpers",
        "function cryo_measure_block(duration_s)",
        "    defbuffer1.clear()",
        "    smu.measure.count = 1",
        "    smu.source.output = smu.ON",
        "    timer.cleartime()",
        "    while timer.gettime() < duration_s do",
        "        smu.measure.read(defbuffer1)",
        "    end",
        "    smu.source.output = smu.OFF",
        "    return defbuffer1.n",
        "end",
        "endscript",
    ]


def build_tsp_config_script(task: MeasurementTask) -> List[str]:
    sense_mode = "smu.SENSE_4WIRE" if task.four_wire else "smu.SENSE_2WIRE"

    return [
        "reset()",
        "smu.terminals = smu.TERMINALS_REAR",
        "defbuffer1.clear()",
        "smu.measure.func = smu.FUNC_DC_VOLTAGE",
        "smu.measure.autorange = smu.ON",
        "smu.measure.unit = smu.UNIT_OHM",
        f"smu.measure.nplc = {task.nplc}",
        f"smu.measure.sense = {sense_mode}",
        f"smu.measure.offsetcompensation = {tsp_bool(task.offset_compensation)}",
        "smu.source.func = smu.FUNC_DC_CURRENT",
        f"smu.source.level = {task.source_current_a}",
        f"smu.source.vlimit.level = {task.voltage_limit_v}",
        f"smu.source.readback = {tsp_bool(task.source_readback)}",
        "smu.source.output = smu.OFF",
    ]


# ============================================================
# Keithley worker
# ============================================================


class KeithleyWorker(QThread):
    connected = pyqtSignal(str)
    measurement_ready = pyqtSignal(float, float, int)  # kept for compatibility, not used in block mode
    measurement_batch_ready = pyqtSignal(object)  # list of (relative_time_s, resistance_ohm) raw readings
    response = pyqtSignal(str)
    error = pyqtSignal(str)
    task_finished = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.resource_name: Optional[str] = None
        self.action: Optional[str] = None
        self.task: Optional[MeasurementTask] = None
        self.readings_per_point: int = 1
        self.block_duration_s: float = 10.0
        self.rm = None
        self.inst = None

    def set_connect_action(self, resource_name: str):
        self.action = "connect"
        self.resource_name = resource_name

    def set_configure_action(self, task: MeasurementTask):
        self.action = "configure"
        self.task = task

    def set_measure_action(self, block_duration_s: float = 10.0):
        # In block mode, Keithley measures continuously for block_duration_s seconds
        # at the highest speed allowed by the selected NPLC/settings.
        # Then Python fetches the full buffer as one batch.
        self.action = "measure"
        self.block_duration_s = float(block_duration_s)

    def set_disconnect_action(self):
        self.action = "disconnect"

    def run(self):
        try:
            if self.action == "connect":
                self._connect()
            elif self.action == "configure":
                self._configure()
            elif self.action == "measure":
                self._measure()
            elif self.action == "disconnect":
                self._disconnect()
            else:
                raise RuntimeError("No valid KeithleyWorker action was selected.")

            self.task_finished.emit(str(self.action))

        except Exception as exc:
            self.error.emit(f"Keithley error during {self.action}: {type(exc).__name__} - {exc}")

    def _connect(self):
        if not self.resource_name:
            raise ValueError("No VISA resource was provided.")

        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(
            self.resource_name,
            read_termination="\n",
            write_termination="\n",
        )
        self.inst.timeout = 30000
        self.inst.chunk_size = 1024 * 1024

        idn = self.inst.query("*IDN?").strip()
        self.connected.emit(idn)

        # Check language. The program expects TSP.
        try:
            lang = self.inst.query("*LANG?").strip()
            self.response.emit(f"Keithley command set: {lang}")
            if "TSP" not in lang.upper():
                self.response.emit(
                    "WARNING: Keithley is not in TSP mode. Change command set to TSP from front panel and reboot."
                )
        except Exception:
            self.response.emit("Could not query *LANG?. Continuing, but TSP mode is still required.")

        self._load_tsp_helpers()

    def _load_tsp_helpers(self):
        if self.inst is None:
            raise RuntimeError("Keithley is not connected.")

        # Delete old helper script if it exists. Ignore error if missing.
        try:
            self.inst.write("script.delete('cryo_helpers')")
        except Exception:
            pass

        for line in build_tsp_helper_script():
            self.inst.write(line)

        self.inst.write("cryo_helpers.run()")
        self.response.emit("TSP helper function loaded.")

    def _configure(self):
        if self.inst is None:
            raise RuntimeError("Keithley is not connected.")
        if self.task is None:
            raise RuntimeError("No measurement task was provided.")

        for line in build_tsp_config_script(self.task):
            self.inst.write(line)

        self.response.emit(
            "Keithley configured: "
            f"I={self.task.source_current_a:g} A, "
            f"Vlim={self.task.voltage_limit_v:g} V, "
            f"NPLC={self.task.nplc:g}, "
            f"raw readings/point=1, "
            f"sense={'4-wire' if self.task.four_wire else '2-wire'}"
        )

    def _measure(self):
        if self.inst is None:
            raise RuntimeError("Keithley is not connected.")

        duration = max(0.1, float(self.block_duration_s))

        # 1) Let Keithley collect raw readings locally for the whole block duration.
        n_raw = self.inst.query(f"print(cryo_measure_block({duration}))").strip()
        n = int(float(n_raw))

        if n <= 0:
            self.measurement_batch_ready.emit([])
            return

        # 2) Fetch relative timestamps and readings as one batch.
        # printbuffer normally returns columns in row order:
        # t1, r1, t2, r2, ... or line-separated pairs depending on firmware/interface.
        raw = self.inst.query(f"printbuffer(1, {n}, defbuffer1.relativetimestamps, defbuffer1.readings)")
        tokens = [tok for tok in re.split(r"[,\s]+", raw.strip()) if tok]

        values = []
        for tok in tokens:
            try:
                values.append(float(tok))
            except ValueError:
                pass

        if len(values) < 2:
            raise ValueError(f"No numeric data returned from printbuffer. Raw response: {raw[:500]}")

        points = []
        # Expected format: relative_time, reading, relative_time, reading, ...
        pair_count = len(values) // 2
        for i in range(pair_count):
            rel_t = values[2 * i]
            resistance = values[2 * i + 1]
            points.append((rel_t, resistance))

        self.measurement_batch_ready.emit(points)

    def _disconnect(self):
        if self.inst is not None:
            try:
                self.inst.write("smu.source.output = smu.OFF")
            except Exception:
                pass
            self.inst.close()
            self.inst = None

        if self.rm is not None:
            try:
                self.rm.close()
            except Exception:
                pass
            self.rm = None

        self.response.emit("Keithley disconnected.")

    def close_safely(self):
        if self.isRunning():
            return
        self.set_disconnect_action()
        self.start()


# ============================================================
# Cryoboss CSV reader
# ============================================================


class CryobossCSVWorker(QObject):
    temperature_updated = pyqtSignal(float, str, list)  # temp_mK, pc_time, raw row
    error = pyqtSignal(str)
    response = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.file_path: Optional[str] = None
        self.temp_column_index: int = 3
        self.temp_unit: str = "K"
        self.last_position: int = 0
        self.watcher: Optional[QFileSystemWatcher] = None
        self.timer: Optional[QTimer] = None

    def configure(self, file_path: str, temp_column_index: int, temp_unit: str):
        self.file_path = os.path.abspath(file_path)
        self.temp_column_index = int(temp_column_index)
        self.temp_unit = temp_unit
        self.last_position = 0

    def start_monitoring(self):
        if not self.file_path:
            self.error.emit("No Cryoboss CSV path was provided.")
            return

        if not os.path.exists(self.file_path):
            self.error.emit(f"Cryoboss CSV does not exist yet: {self.file_path}")
            # Still start timer. The file may appear later.

        self.watcher = QFileSystemWatcher()
        if os.path.exists(self.file_path):
            self.watcher.addPath(self.file_path)
            self.last_position = os.path.getsize(self.file_path)

        self.watcher.fileChanged.connect(self.process_new_lines)

        self.timer = QTimer()
        self.timer.timeout.connect(self.process_new_lines)
        self.timer.start(2000)

        self.response.emit(f"Monitoring Cryoboss CSV: {self.file_path}")

    def stop_monitoring(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.watcher is not None:
            self.watcher.deleteLater()
            self.watcher = None

    def process_new_lines(self):
        if not self.file_path:
            return

        if not os.path.exists(self.file_path):
            return

        # If file was created after monitoring started, add it to watcher.
        if self.watcher is not None and self.file_path not in self.watcher.files():
            try:
                self.watcher.addPath(self.file_path)
                self.last_position = 0
            except Exception:
                pass

        try:
            current_size = os.path.getsize(self.file_path)

            # File was overwritten or rotated.
            if current_size < self.last_position:
                self.last_position = 0

            if current_size == self.last_position:
                return

            with open(self.file_path, "r", newline="", encoding="utf-8", errors="ignore") as f:
                f.seek(self.last_position)
                reader = csv.reader(f)
                for row in reader:
                    self._process_row(row)
                self.last_position = f.tell()

        except PermissionError:
            # Common when another program is writing the file.
            return
        except Exception as exc:
            self.error.emit(f"Cryoboss CSV error: {type(exc).__name__} - {exc}")

    def _process_row(self, row: List[str]):
        if not row:
            return

        if self.temp_column_index >= len(row):
            return

        temp_value = safe_float(row[self.temp_column_index])
        if temp_value is None:
            # Header or malformed row.
            return

        unit = self.temp_unit.lower()
        if unit == "k":
            temp_mk = temp_value * 1000.0
        elif unit == "mk":
            temp_mk = temp_value
        else:
            self.error.emit(f"Unknown temperature unit: {self.temp_unit}")
            return

        self.temperature_updated.emit(temp_mk, datetime.now().isoformat(timespec="seconds"), row)


# ============================================================
# Plot worker
# ============================================================


class PlotWorker(QThread):
    response = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_plotting = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.csv_path: Optional[Path] = None
        self.output_stem: Optional[str] = None

    def set_task(self, csv_path: Path, output_stem: str):
        self.csv_path = Path(csv_path)
        self.output_stem = output_stem

    def run(self):
        try:
            if self.csv_path is None or self.output_stem is None:
                raise RuntimeError("Plot task is not configured.")

            df = pd.read_csv(self.csv_path)
            if df.empty:
                raise RuntimeError("CSV is empty. No plot was generated.")

            png_path = PLOTS_DIR / f"{self.output_stem}.png"
            html_path = PLOTS_DIR / f"{self.output_stem}.html"

            # PNG plot with matplotlib.
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(df["temperature_mk"], df["resistance_ohm"], marker="o", linewidth=1)
            ax.set_xlabel("Temperature (mK)")
            ax.set_ylabel("Resistance (Ohm)")
            ax.set_title("Resistance vs Temperature")
            ax.grid(True)
            fig.tight_layout()
            fig.savefig(png_path, dpi=200)
            plt.close(fig)

            self.response.emit(f"Saved PNG plot: {png_path}")

            # Optional HTML plot with Plotly.
            try:
                import plotly.graph_objects as go

                fig_html = go.Figure()
                fig_html.add_trace(
                    go.Scatter(
                        x=df["temperature_mk"],
                        y=df["resistance_ohm"],
                        mode="lines+markers",
                        name="R(T)",
                    )
                )
                fig_html.update_layout(
                    title="Resistance vs Temperature",
                    xaxis_title="Temperature (mK)",
                    yaxis_title="Resistance (Ohm)",
                    template="plotly_white",
                )
                fig_html.write_html(html_path)
                self.response.emit(f"Saved HTML plot: {html_path}")
            except Exception as exc:
                self.response.emit(f"HTML plot skipped: {type(exc).__name__} - {exc}")

            self.finished_plotting.emit(str(png_path))

        except Exception as exc:
            self.error.emit(f"Plot error: {type(exc).__name__} - {exc}")


# ============================================================
# Task UI classes
# ============================================================


class TaskBox(QFrame):
    def __init__(self, task: MeasurementTask, order: int, delete_callback):
        super().__init__()
        self.task = task
        self.delete_callback = delete_callback

        self.setObjectName("TaskBox")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(self)
        self.label = QLabel()
        self.label.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        self.update_display_text(order)

        self.btn_delete = QPushButton("✕")
        self.btn_delete.setFixedSize(26, 26)
        self.btn_delete.clicked.connect(lambda: self.delete_callback(self))

        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.btn_delete)

        self.setStyleSheet(
            """
            #TaskBox {
                background-color: #ffffff;
                border: 1px solid #95a5a6;
                border-radius: 8px;
                margin-bottom: 5px;
            }
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border-radius: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            """
        )

    def update_display_text(self, order: int):
        self.label.setText(
            f"[{order:02d}] {self.task.name or 'R(T)'} | both heating/cooling\n"
            f"     TEMP : {self.task.start_temp_mk:g} mK -> {self.task.stop_temp_mk:g} mK\n"
            f"     SMU  : I={self.task.source_current_a:g} A, Vlim={self.task.voltage_limit_v:g} V, "
            f"NPLC={self.task.nplc:g}\n"
            f"     READ : fast block, duration={self.task.interval_s:g} s, "
            f"{'4-wire' if self.task.four_wire else '2-wire'}"
        )


class SchedulerDisplay(QScrollArea):
    task_deleted = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.container)

    def add_task(self, task: MeasurementTask):
        box = TaskBox(task, self.layout.count() + 1, self.remove_task_widget)
        self.layout.addWidget(box)

    def remove_task_widget(self, widget: TaskBox):
        index = -1
        for i in range(self.layout.count()):
            if self.layout.itemAt(i).widget() == widget:
                index = i
                break

        if index >= 0:
            self.layout.removeWidget(widget)
            widget.deleteLater()
            self.renumber()
            self.task_deleted.emit(index)

    def remove_first(self):
        if self.layout.count() <= 0:
            return
        item = self.layout.itemAt(0)
        widget = item.widget()
        if isinstance(widget, TaskBox):
            self.layout.removeWidget(widget)
            widget.deleteLater()
            self.renumber()

    def renumber(self):
        for i in range(self.layout.count()):
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, TaskBox):
                widget.update_display_text(i + 1)


# ============================================================
# Main application
# ============================================================


class CryoKeithleyApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Keithley 2450 Cryogenic Resistance Automation")
        self.resize(1550, 900)

        self.tasks: List[MeasurementTask] = []
        self.active_task: Optional[MeasurementTask] = None
        self.active_csv_path: Optional[Path] = None
        self.active_output_stem: Optional[str] = None
        self.measurement_points: List[MeasurementPoint] = []

        self.latest_temp_mk: Optional[float] = None
        self.previous_temp_mk: Optional[float] = None
        self.measurement_start_time: Optional[float] = None
        self.scheduler_running = False
        self.measurement_active = False
        self.waiting_for_keithley = False

        self.keithley = KeithleyWorker()
        self.keithley.connected.connect(self.on_keithley_connected)
        self.keithley.measurement_ready.connect(self.on_measurement_ready)
        self.keithley.measurement_batch_ready.connect(self.on_measurement_batch_ready)
        self.keithley.response.connect(self.log)
        self.keithley.error.connect(self.handle_error)
        self.keithley.task_finished.connect(self.on_keithley_task_finished)

        self.cryo_reader = CryobossCSVWorker()
        self.cryo_reader.temperature_updated.connect(self.on_temperature_updated)
        self.cryo_reader.response.connect(self.log)
        self.cryo_reader.error.connect(self.handle_error)

        self.plot_worker = PlotWorker()
        self.plot_worker.response.connect(self.log)
        self.plot_worker.error.connect(self.handle_error)
        self.plot_worker.finished_plotting.connect(lambda path: self.log(f"Plotting finished: {path}", "lightgreen"))

        self.measurement_timer = QTimer()
        self.measurement_timer.timeout.connect(self.request_measurement_point)

        self.temperature_history: List[Tuple[float, float]] = []  # (perf_counter_time, temp_mK)
        self.current_block_start_perf: Optional[float] = None

        self._build_ui()

    # ---------------- UI construction ----------------

    def _build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        self.setCentralWidget(root)

        left = self._build_left_panel()
        center = self._build_center_panel()
        right = self._build_right_panel()

        root_layout.addWidget(left, stretch=0)
        root_layout.addWidget(center, stretch=1)
        root_layout.addWidget(right, stretch=0)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        panel.setFixedWidth(360)

        layout.addWidget(QLabel("<b>Keithley connection</b>"))
        layout.addWidget(QLabel("Keithley IP or VISA resource"))
        self.input_resource = QLineEdit("10.1.197.65")
        layout.addWidget(self.input_resource)

        self.btn_connect = QPushButton("Connect Keithley")
        self.btn_connect.clicked.connect(self.connect_keithley)
        layout.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("Disconnect Keithley")
        self.btn_disconnect.clicked.connect(self.disconnect_keithley)
        layout.addWidget(self.btn_disconnect)

        layout.addSpacing(15)
        layout.addWidget(QLabel("<b>Cryoboss CSV</b>"))
        self.input_cryo_path = QLineEdit(
            "/run/user/1000/gvfs/smb-share:server=10.1.197.100,share=data/manual_file_name_auto.csv"
        )
        layout.addWidget(self.input_cryo_path)

        btn_browse = QPushButton("Browse CSV")
        btn_browse.clicked.connect(self.browse_cryo_csv)
        layout.addWidget(btn_browse)

        grid = QGridLayout()
        grid.addWidget(QLabel("Temperature column index"), 0, 0)
        self.spin_temp_col = QSpinBox()
        self.spin_temp_col.setRange(0, 100)
        self.spin_temp_col.setValue(3)
        grid.addWidget(self.spin_temp_col, 0, 1)

        grid.addWidget(QLabel("Temperature unit"), 1, 0)
        self.combo_temp_unit = QComboBox()
        self.combo_temp_unit.addItems(["K", "mK"])
        grid.addWidget(self.combo_temp_unit, 1, 1)
        layout.addLayout(grid)

        self.btn_start_cryo = QPushButton("Start temperature monitor")
        self.btn_start_cryo.clicked.connect(self.start_temperature_monitor)
        layout.addWidget(self.btn_start_cryo)

        self.btn_stop_cryo = QPushButton("Stop temperature monitor")
        self.btn_stop_cryo.clicked.connect(self.stop_temperature_monitor)
        layout.addWidget(self.btn_stop_cryo)

        layout.addStretch()
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        status_layout = QGridLayout()
        self.label_temp = QLabel("Temperature: --- mK")
        self.label_temp.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.label_resistance = QLabel("Resistance: --- Ω")
        self.label_resistance.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.label_status = QLabel("Status: idle")
        self.label_status.setStyleSheet("font-size: 15px;")

        status_layout.addWidget(self.label_temp, 0, 0)
        status_layout.addWidget(self.label_resistance, 0, 1)
        status_layout.addWidget(self.label_status, 1, 0, 1, 2)
        layout.addLayout(status_layout)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("bottom", "Temperature", units="mK")
        self.plot_widget.setLabel("left", "Resistance", units="Ω")
        self.plot_widget.showGrid(x=True, y=True)
        self.rt_curve = self.plot_widget.plot([], [], symbol="o", symbolSize=6, pen=pg.mkPen(width=2))
        layout.addWidget(self.plot_widget, stretch=1)

        layout.addWidget(QLabel("<b>Console</b>"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1e1e1e; color: white; font-family: Consolas, monospace;")
        layout.addWidget(self.console, stretch=1)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        panel.setFixedWidth(430)

        layout.addWidget(QLabel("<b>Measurement task</b>"))

        self.input_task_name = QLineEdit("sample_RT")
        layout.addWidget(QLabel("Task name"))
        layout.addWidget(self.input_task_name)

        grid = QGridLayout()

        self.spin_start_temp = QDoubleSpinBox()
        # Wide range so you can test at room temperature too.
        # Example: 280 K = 280000 mK.
        self.spin_start_temp.setRange(-1_000_000_000, 1_000_000_000)
        self.spin_start_temp.setDecimals(3)
        self.spin_start_temp.setValue(100.0)
        self.spin_start_temp.setSuffix(" mK")

        self.spin_stop_temp = QDoubleSpinBox()
        # Wide range so you can test at room temperature too.
        # Example: 280 K = 280000 mK.
        self.spin_stop_temp.setRange(-1_000_000_000, 1_000_000_000)
        self.spin_stop_temp.setDecimals(3)
        self.spin_stop_temp.setValue(300.0)
        self.spin_stop_temp.setSuffix(" mK")

        self.spin_source_current = QDoubleSpinBox()
        self.spin_source_current.setRange(-1.0, 1.0)
        self.spin_source_current.setDecimals(12)
        self.spin_source_current.setSingleStep(1e-6)
        self.spin_source_current.setValue(1e-6)
        self.spin_source_current.setSuffix(" A")

        self.spin_vlimit = QDoubleSpinBox()
        self.spin_vlimit.setRange(0.001, 200.0)
        self.spin_vlimit.setDecimals(6)
        self.spin_vlimit.setValue(1.0)
        self.spin_vlimit.setSuffix(" V")

        self.spin_nplc = QDoubleSpinBox()
        self.spin_nplc.setRange(0.0005, 15)
        self.spin_nplc.setDecimals(4)
        self.spin_nplc.setValue(1.0)

        self.spin_readings = QSpinBox()
        self.spin_readings.setRange(1, 1)
        self.spin_readings.setValue(1)

        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 3600.0)
        self.spin_interval.setDecimals(2)
        self.spin_interval.setValue(10.0)
        self.spin_interval.setSuffix(" s")

        self.check_four_wire = QCheckBox("4-wire sensing")
        self.check_four_wire.setChecked(True)

        self.check_ocomp = QCheckBox("Offset compensation")
        self.check_ocomp.setChecked(True)

        self.check_readback = QCheckBox("Source readback")
        self.check_readback.setChecked(False)

        grid.addWidget(QLabel("Start temp"), 0, 0)
        grid.addWidget(self.spin_start_temp, 0, 1)
        grid.addWidget(QLabel("Stop temp"), 1, 0)
        grid.addWidget(self.spin_stop_temp, 1, 1)
        grid.addWidget(QLabel("Source current"), 2, 0)
        grid.addWidget(self.spin_source_current, 2, 1)
        grid.addWidget(QLabel("Voltage limit"), 3, 0)
        grid.addWidget(self.spin_vlimit, 3, 1)
        grid.addWidget(QLabel("NPLC"), 4, 0)
        grid.addWidget(self.spin_nplc, 4, 1)
        grid.addWidget(QLabel("Readings / point (raw mode: fixed at 1)"), 5, 0)
        grid.addWidget(self.spin_readings, 5, 1)
        grid.addWidget(QLabel("Block duration / send interval"), 6, 0)
        grid.addWidget(self.spin_interval, 6, 1)
        layout.addLayout(grid)

        layout.addWidget(self.check_four_wire)
        layout.addWidget(self.check_ocomp)
        layout.addWidget(self.check_readback)

        self.btn_add_task = QPushButton("Add task to schedule")
        self.btn_add_task.clicked.connect(self.add_task)
        layout.addWidget(self.btn_add_task)

        self.scheduler_display = SchedulerDisplay()
        self.scheduler_display.task_deleted.connect(self.remove_task_by_index)
        layout.addWidget(QLabel("<b>Scheduled tasks</b>"))
        layout.addWidget(self.scheduler_display, stretch=1)

        self.btn_start_scheduler = QPushButton("Start scheduler")
        self.btn_start_scheduler.clicked.connect(self.start_scheduler)
        layout.addWidget(self.btn_start_scheduler)

        self.btn_stop_scheduler = QPushButton("Stop scheduler")
        self.btn_stop_scheduler.clicked.connect(self.stop_scheduler)
        layout.addWidget(self.btn_stop_scheduler)

        self.btn_abort = QPushButton("Abort measurement")
        self.btn_abort.clicked.connect(self.abort_measurement)
        self.btn_abort.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        layout.addWidget(self.btn_abort)

        return panel

    # ---------------- Logging ----------------

    def log(self, text: str, color: str = "white"):
        self.console.append(f'<span style="color:{color};">{datetime.now().strftime("%H:%M:%S")} | {text}</span>')

    def handle_error(self, text: str):
        self.log(f"ERROR: {text}", "#ff6b6b")
        self.label_status.setText(f"Status: error")

    # ---------------- Button callbacks ----------------

    def browse_cryo_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Cryoboss CSV", str(SCRIPT_DIR), "CSV files (*.csv);;All files (*)")
        if path:
            self.input_cryo_path.setText(path)

    def connect_keithley(self):
        if self.keithley.isRunning():
            self.log("Keithley worker is busy.", "orange")
            return

        resource = make_resource_name(self.input_resource.text())
        self.log(f"Connecting to Keithley: {resource}", "lightblue")
        self.keithley.set_connect_action(resource)
        self.keithley.start()

    def disconnect_keithley(self):
        if self.keithley.isRunning():
            self.log("Keithley worker is busy. Cannot disconnect now.", "orange")
            return
        self.keithley.set_disconnect_action()
        self.keithley.start()

    def start_temperature_monitor(self):
        self.cryo_reader.stop_monitoring()
        self.cryo_reader.configure(
            file_path=self.input_cryo_path.text(),
            temp_column_index=self.spin_temp_col.value(),
            temp_unit=self.combo_temp_unit.currentText(),
        )
        self.cryo_reader.start_monitoring()

    def stop_temperature_monitor(self):
        self.cryo_reader.stop_monitoring()
        self.log("Temperature monitor stopped.", "orange")

    def add_task(self):
        task = MeasurementTask(
            start_temp_mk=self.spin_start_temp.value(),
            stop_temp_mk=self.spin_stop_temp.value(),
            source_current_a=self.spin_source_current.value(),
            voltage_limit_v=self.spin_vlimit.value(),
            nplc=self.spin_nplc.value(),
            readings_per_point=self.spin_readings.value(),
            interval_s=self.spin_interval.value(),
            four_wire=self.check_four_wire.isChecked(),
            offset_compensation=self.check_ocomp.isChecked(),
            source_readback=self.check_readback.isChecked(),
            name=self.input_task_name.text().strip(),
        )

        if task.stop_temp_mk == task.start_temp_mk:
            QMessageBox.warning(self, "Invalid task", "Start and stop temperatures should not be the same.")
            return

        self.tasks.append(task)
        self.scheduler_display.add_task(task)
        self.log(f"Task added: {task.name or 'R(T)'}", "lightgreen")

    def remove_task_by_index(self, index: int):
        if 0 <= index < len(self.tasks):
            removed = self.tasks.pop(index)
            self.log(f"Removed scheduled task: {removed.name or 'R(T)'}", "gray")

    def start_scheduler(self):
        if self.scheduler_running:
            self.log("Scheduler is already running.", "orange")
            return

        if not self.tasks:
            self.log("No scheduled tasks.", "orange")
            return

        self.scheduler_running = True
        self.label_status.setText("Status: scheduler running, waiting for temperature crossing")
        self.log("Scheduler started.", "lightgreen")

    def stop_scheduler(self):
        self.scheduler_running = False
        self.label_status.setText("Status: scheduler stopped")
        self.log("Scheduler stopped. Active measurement is not aborted automatically.", "orange")

    def abort_measurement(self):
        self.scheduler_running = False
        self.measurement_active = False
        self.waiting_for_keithley = False
        self.measurement_timer.stop()

        try:
            if self.keithley.inst is not None:
                self.keithley.inst.write("smu.source.output = smu.OFF")
        except Exception:
            pass

        self.finalize_active_measurement(aborted=True)
        self.label_status.setText("Status: aborted")
        self.log("Measurement aborted.", "#ffb86c")

    # ---------------- Temperature and scheduler ----------------

    def on_temperature_updated(self, temp_mk: float, pc_time: str, row: list):
        self.previous_temp_mk = self.latest_temp_mk
        self.latest_temp_mk = temp_mk
        self.temperature_history.append((time.perf_counter(), temp_mk))
        if len(self.temperature_history) > 20000:
            self.temperature_history = self.temperature_history[-10000:]
        self.label_temp.setText(f"Temperature: {temp_mk:.3f} mK")

        if self.scheduler_running and not self.measurement_active and self.tasks:
            next_task = self.tasks[0]
            if should_start_measurement(
                self.previous_temp_mk,
                self.latest_temp_mk,
                next_task.start_temp_mk,
                next_task.stop_temp_mk,
            ):
                self.start_task(next_task)

        if self.measurement_active and self.active_task is not None:
            if should_stop_measurement(self.latest_temp_mk, self.active_task.start_temp_mk, self.active_task.stop_temp_mk):
                self.log("Temperature left the selected range. Current block will finish, then measurement will stop.", "lightgreen")
                self.measurement_active = False

    def start_task(self, task: MeasurementTask):
        if self.keithley.inst is None:
            self.handle_error("Keithley is not connected. Cannot start measurement.")
            return

        if self.keithley.isRunning():
            self.log("Keithley is busy. Start will be retried at next temperature update.", "orange")
            return

        self.active_task = task
        self.measurement_active = False  # becomes true after Keithley is configured
        self.measurement_points = []
        self.measurement_start_time = time.perf_counter()

        self.active_output_stem = task.folder_stem()
        self.active_csv_path = CSV_DIR / f"{self.active_output_stem}.csv"

        self.log(f"Starting task: {task.name or 'R(T)'}", "lightgreen")
        self.log(f"Output CSV: {self.active_csv_path}", "lightblue")

        self.write_csv_header(self.active_csv_path)

        self.keithley.set_configure_action(task)
        self.keithley.start()

    def on_keithley_task_finished(self, action: str):
        if action == "configure" and self.active_task is not None:
            self.measurement_active = True
            self.scheduler_display.remove_first()
            if self.tasks:
                self.tasks.pop(0)

            self.label_status.setText("Status: measuring R(T) in continuous blocks")
            self.log(
                f"Starting first measurement block. Keithley will measure continuously for {self.active_task.interval_s:g} s, then send the batch.",
                "lightgreen",
            )
            self.request_measurement_point()

    def request_measurement_point(self):
        if not self.measurement_active or self.active_task is None:
            return

        if self.latest_temp_mk is None:
            self.log("No temperature yet. Skipping measurement point.", "orange")
            return

        if self.keithley.isRunning() or self.waiting_for_keithley:
            self.log("Keithley still busy. Skipping this interval.", "orange")
            return

        self.waiting_for_keithley = True
        self.current_block_start_perf = time.perf_counter()
        self.keithley.set_measure_action(self.active_task.interval_s)
        self.keithley.start()

    def on_measurement_ready(self, avg_ohm: float, std_ohm: float, n: int):
        # Old single-point mode. Kept only so the signal connection does not break.
        # The current program uses on_measurement_batch_ready().
        pass

    def estimate_temperature_at_time(self, target_perf_time: float) -> float:
        """
        Estimate temperature at a particular PC perf_counter time.
        This uses the latest Cryoboss values seen by Python. If the Cryoboss file updates
        slowly, several Keithley readings may receive the same interpolated temperature.
        """
        if self.latest_temp_mk is None:
            return float("nan")

        hist = self.temperature_history
        if not hist:
            return self.latest_temp_mk

        if target_perf_time <= hist[0][0]:
            return hist[0][1]
        if target_perf_time >= hist[-1][0]:
            return hist[-1][1]

        for i in range(1, len(hist)):
            t0, temp0 = hist[i - 1]
            t1, temp1 = hist[i]
            if t0 <= target_perf_time <= t1:
                if t1 == t0:
                    return temp1
                frac = (target_perf_time - t0) / (t1 - t0)
                return temp0 + frac * (temp1 - temp0)

        return self.latest_temp_mk

    def on_measurement_batch_ready(self, points):
        self.waiting_for_keithley = False

        if self.active_task is None or self.measurement_start_time is None:
            return

        if self.current_block_start_perf is None:
            self.current_block_start_perf = time.perf_counter()

        if not points:
            self.log("Keithley returned an empty block.", "orange")
        else:
            for rel_t, resistance in points:
                sample_perf_time = self.current_block_start_perf + float(rel_t)
                elapsed = sample_perf_time - self.measurement_start_time
                temp_mk = self.estimate_temperature_at_time(sample_perf_time)

                point = MeasurementPoint(
                    pc_time=datetime.now().isoformat(timespec="seconds"),
                    elapsed_s=elapsed,
                    temperature_mk=temp_mk,
                    temperature_k=temp_mk / 1000.0 if not math.isnan(temp_mk) else float("nan"),
                    resistance_ohm=float(resistance),
                    resistance_std_ohm=0.0,
                    readings_per_point=1,
                    source_current_a=self.active_task.source_current_a,
                    voltage_limit_v=self.active_task.voltage_limit_v,
                    nplc=self.active_task.nplc,
                    direction=infer_temperature_direction(self.previous_temp_mk, self.latest_temp_mk),
                    status="ok",
                )

                self.measurement_points.append(point)
                self.append_point_to_csv(point)

            self.update_live_plot()
            last = self.measurement_points[-1]
            self.label_resistance.setText(f"Resistance: {last.resistance_ohm:.6g} Ω")
            self.log(
                f"Received block: {len(points)} raw readings | "
                f"latest T={last.temperature_mk:.3f} mK | latest R={last.resistance_ohm:.6g} Ω"
            )

        # Start the next block immediately if still inside range.
        if self.active_task is not None and self.latest_temp_mk is not None:
            if inside_temperature_range(self.latest_temp_mk, self.active_task.start_temp_mk, self.active_task.stop_temp_mk):
                if self.measurement_active:
                    self.request_measurement_point()
            else:
                self.finish_current_task()

    def finish_current_task(self):
        self.measurement_timer.stop()
        self.measurement_active = False
        self.waiting_for_keithley = False
        self.finalize_active_measurement(aborted=False)

        if self.scheduler_running and self.tasks:
            self.label_status.setText("Status: waiting for next scheduled task")
        else:
            self.scheduler_running = False
            self.label_status.setText("Status: all tasks finished")
            self.log("All scheduled tasks finished.", "lightgreen")

    def finalize_active_measurement(self, aborted: bool):
        if self.active_csv_path is not None and self.active_output_stem is not None and self.active_csv_path.exists():
            if len(self.measurement_points) > 0 and not self.plot_worker.isRunning():
                self.plot_worker.set_task(self.active_csv_path, self.active_output_stem)
                self.plot_worker.start()
            elif len(self.measurement_points) == 0:
                self.log("No measurement points were collected. Plot skipped.", "orange")

        if aborted:
            self.log("Active task finalized as aborted.", "orange")
        else:
            self.log("Active task finalized.", "lightgreen")

        self.active_task = None
        self.active_csv_path = None
        self.active_output_stem = None
        self.measurement_start_time = None

    # ---------------- CSV saving and plotting ----------------

    def write_csv_header(self, path: Path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(MeasurementPoint("", 0, 0, 0, 0, 0, 0, 0, 0, 0, "", "")).keys()))
            writer.writeheader()

    def append_point_to_csv(self, point: MeasurementPoint):
        if self.active_csv_path is None:
            return
        with open(self.active_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(point).keys()))
            writer.writerow(asdict(point))

    def update_live_plot(self):
        if not self.measurement_points:
            return
        x = [p.temperature_mk for p in self.measurement_points]
        y = [p.resistance_ohm for p in self.measurement_points]
        self.rt_curve.setData(x, y)

    # ---------------- Keithley signals ----------------

    def on_keithley_connected(self, idn: str):
        self.log(f"Connected: {idn}", "lightgreen")
        self.label_status.setText("Status: Keithley connected")

    # ---------------- Close event ----------------

    def closeEvent(self, event):
        self.measurement_timer.stop()
        self.cryo_reader.stop_monitoring()

        try:
            if self.keithley.inst is not None:
                self.keithley.inst.write("smu.source.output = smu.OFF")
                self.keithley.inst.close()
        except Exception:
            pass

        event.accept()


# ============================================================
# Main
# ============================================================


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CryoKeithleyApp()
    window.show()
    sys.exit(app.exec())
