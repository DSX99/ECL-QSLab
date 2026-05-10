import sys
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QScrollArea, QFrame,
    QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QObject

from vna_plot_tools import make_both_plots
import pyvisa
import numpy as np
import time
import atexit
import socket

def format_number(value):
    """
    Format numbers nicely for folder names.
    6.0 -> 6
    6.5 -> 6.5
    """
    value = float(value)

    if value.is_integer():
        return str(int(value))

    return f"{value:.3f}".rstrip("0").rstrip(".")


def format_temp_mk(value):
    """
    Round temperature to nearest decimal.
    133.36 -> 133.4mK
    """
    return f"{float(value):.1f}mK"

# worker for async work
class InstrumentWorker(QThread):
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished_task = pyqtSignal()

    def __init__(self, resource_name):
        super().__init__()
        self.resource_name = resource_name
        self.task_type = None
        self.params = {}
        self.inst = None
        self.download_folder_name = None
        
    def create_task(self, task_type, *args):
        self.task_type = task_type
        self.params = args
        print(self.params)

    def run(self):
        try:
            if self.task_type == "init":
                rm = pyvisa.ResourceManager()
                print(self.resource_name)
                self.inst = rm.open_resource(self.resource_name, read_termination='\n')
                self.inst.timeout = 15e3
                id = self.inst.query('*IDN?')
                self.response_received.emit(id)

                def cleanup():
                    print("Atexit: Closing the connection...")
                    self.inst.close()

                atexit.register(cleanup)
                
                self.inst.write(":MMEMory:STORe:SNP:FORMat 'RI'")
                self.inst.write(":CALCulate1:PARameter1:DEFine 'S21'")
                
            elif self.task_type == "work_dir":
                self.working_dir(*self.params)
            elif self.task_type == "freq_sweep":
                self.freq_sweep(*self.params)
            elif self.task_type == "power_sweep":
                self.power_sweep(*self.params)
            elif self.task_type == "file_download":
                self.file_download()

            self.finished_task.emit()

        except Exception as e:
            self.error_occurred.emit(
                f"An unexpected error occurred in run: {type(e).__name__} - {e} in run"
            )

    def working_dir(self, name):
        try:
            check = self.inst.query(':MMEMory:CATalog:DIR? "/local/auto"')
            if not (name in check):
                self.inst.write(f':MMEM:MDIR "/local/auto/{name}"')

            self.inst.write(f':MMEMory:CDIRectory "/local/auto/{name}"')
            path = self.inst.query(':MMEM:CDIR?').replace('"', '')
            self.response_received.emit(f"Working dir:{path}")
        except pyvisa.errors.VisaIOError as e:
            self.error_occurred.emit(f"VISA IO Error in working_dir: {e.description} in working_dir")
        except Exception as e:
            self.error_occurred.emit(
                f"An unexpected error occurred in working_dir: {type(e).__name__} - {e} in working_dir"
            )

    def file_download(self):
        try:
            self.inst.chunk_size = 20 * 1024 * 1024
            self.inst.timeout = 100e3

            files = self.inst.query(':MMEMory:CATalog?')
            files = files.split(",")

            folder_path = Path(self.download_folder_name)
            folder_path.mkdir(parents=True, exist_ok=True)

            for file in files:
                file = file.strip('"\x00 \n\r')

                if not file:
                    continue

                if not file.lower().endswith(".s2p"):
                    continue

                self.response_received.emit(f"Downloading {file}")

                file_data = self.inst.query_binary_values(
                    f':MMEMory:TRANsfer? "{file}"',
                    datatype='B',
                    container=bytes
                )

                output_file = folder_path / file

                with open(output_file, "wb") as f:
                    f.write(file_data)

            self.inst.timeout = 30e3

        except pyvisa.errors.VisaIOError as e:
            self.error_occurred.emit(f"VISA IO Error in file_download: {e} in file_download")
        except Exception as e:
            self.error_occurred.emit(
                f"An unexpected error occurred in file_download: {type(e).__name__} - {e} in file_download"
            )

    def do_scan(self, start_freq, finish_freq, if_freq, power, point, name):
        start_time = time.perf_counter()
        try:
            self.inst.write(f":SENSe1:SWEep:POINts {point}")
            points = self.inst.query(":SENSe1:SWEep:POINts?")

            self.inst.write(f":SOURce1:POWer {power}")
            pow = self.inst.query(":SOURce1:POWer?")

            self.inst.write(f':SENSe1:FREQuency:STARt {start_freq * 1e9}')
            self.inst.write(f':SENSe1:FREQuency:STOP {finish_freq * 1e9}')

            start = (self.inst.query(":SENSe1:FREQuency:STARt?")).strip('\x00').strip()
            finish = (self.inst.query(":SENSe1:FREQuency:STOP?")).strip('\x00').strip()

            self.inst.write(f':SENSe1:BANDwidth {if_freq}')
            got_if_freq = self.inst.query(":SENSe1:BANDwidth?")

            self.inst.write("TRIG:SOUR BUS")

            self.response_received.emit(
                f"doing a scan for {str(points)} points, "
                f"from {float(start) / 1e9}ghz to {float(finish) / 1e9}ghz "
                f"with IF frequency {str(got_if_freq)}hz and power {pow}dB"
            )

            self.inst.write("TRIG:SING")

            self.response_received.emit("waiting the scan...")

            self.inst.timeout = 200e3
            self.inst.query("*OPC?")
            self.inst.timeout = 25e3

            self.response_received.emit("scan done")

            if name is None:
                self.inst.write(
                    f':MMEMory:STORe:SNP "{float(start) / 1e9}GHz-{float(finish) / 1e9}GHz-{float(power)}dB.s2p"'
                )
            else:
                self.inst.write(f':MMEMory:STORe:SNP "{name}.s2p"')

            self.response_received.emit("scan saved")

            end_time = time.perf_counter()
            self.response_received.emit(f"Elapsed time: {end_time - start_time:.6f} seconds")

        except pyvisa.errors.VisaIOError as e:
            self.error_occurred.emit(f"VISA IO Error in do_scan: {e} in do_scan")
            self.error_occurred.emit(f"timeout was {self.inst.timeout / 1e3} sec in do_scan")
        except Exception as e:
            self.error_occurred.emit(
                f"An unexpected error occurred in do_scan: {type(e).__name__} - {e} in do_scan"
            )

    def freq_sweep(self, start_freq, stop_freq, scan_amount, if_freq, power, points, name=None):

        step = (float(stop_freq) - float(start_freq)) / scan_amount

        for i in range(scan_amount):
            self.do_scan(
                float(start_freq) + i * step,
                float(start_freq) + (i + 1) * step,
                if_freq,
                power,
                points,
                name
            )

    def power_sweep(self, start_freq, stop_freq, scan_amount, if_freq, start_power, stop_power, points, name=None):
        step = (float(stop_power) - float(start_power)) / int(scan_amount)

        for i in range(int(scan_amount)):
            self.do_scan(
                float(start_freq),
                float(stop_freq),
                if_freq,
                float(start_power) + (i * step),
                points,
                name
            )

    def __del__(self):
        if hasattr(self, 'inst') and self.inst is not None:
            try:
                self.inst.close()
            except Exception as e:
                print(f"[cleanup] Error closing instrument: {e}")

#data parser from cryoboss
class CryobossWorker(QObject):
    temperature_signal = pyqtSignal(float)
    debug_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    cycle_started_signal = pyqtSignal(bool)

    def __init__(self, address):
        super().__init__()
        self.address = address
        self.mk_temp = None
        self.magnet_temp = 0.0
        self.connection = None
        self.verifying_cycle = False
        self.temp_at_start_request = None
        
    def initialize_socket(self):
        """Perform network setup inside the thread, not the constructor."""
        try:
            self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connection.settimeout(3.0) 
            self.connection.connect((self.address, 60770))
            
            atexit.register(self.cleanup)
            self.start_monitoring()
        except Exception as e:
            self.error_signal.emit(f"Connection Error: {e}")

    def start_monitoring(self):
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.process_data)
        self.check_timer.start(2000) 
        print("Monitoring Cryoboss")
        self.debug_signal.emit("Monitoring data from Cryoboss")
        
    def process_data(self):
        try:
            # Query FAA temp (50mK)
            self.connection.send(b"Temps.FAA_Display = ?")
            recv = self.connection.recv(4096)
            self.mk_temp = float(recv.decode().split("=")[-1].strip())
            self.temperature_signal.emit(self.mk_temp) 
            
            # Query Magnet Temp
            self.connection.send(b"Temps.Magnet_T = ?")
            recv = self.connection.recv(4096)
            self.magnet_temp = float(recv.decode().split("=")[-1].strip())   
            
            if self.verifying_cycle:
                self.verify_and_execute()
                
        except Exception as e:
            self.error_signal.emit(f"Network error: {str(e)}")

    def start_cycle_request(self):
        """Called by GUI. Instead of sleeping, we set a flag."""
        if self.magnet_temp >= 5:
            self.error_signal.emit("Temp too high (>5) to start cycle.")
            self.cycle_started_signal.emit(False)
            return

        self.temp_at_start_request = self.magnet_temp
        self.verifying_cycle = True

    def verify_and_execute(self):
        """This runs on the next timer tick (usually 1-2 seconds later)."""
        try:
            # Check the same conditions you had in your sleep logic
            if self.magnet_temp >= 5:
                raise RuntimeError("Temp rose above 5 during verification")
            
            # If the temp hasn't changed at all, the hardware might be frozen
            if self.magnet_temp == self.temp_at_start_request:
                self.debug_signal.emit("Temp hasn't changed yet, waiting for next tick...")
                return # Keep waiting; don't reset the flag yet

            # If we reach here, temp has changed and is < 5. Proceed!
            self.connection.send(b"Start MC = 1")
            reciv = self.connection.recv(4096)
            
            if reciv == b"ACK Start MC = TRUE":
                self.cycle_started_signal.emit(True)
            else:
                raise Exception(f"Cryoboss rejected start: {reciv}")
            
            # Reset the state
            self.verifying_cycle = False
            
        except Exception as e:
            self.verifying_cycle = False
            self.error_signal.emit(str(e))
            self.cycle_started_signal.emit(False)
        
    def cleanup(self):
        if self.connection:
            print("Closing the Cryoboss connection...")
            self.connection.close()

# NEW: worker for automatic plot generation
class PlotWorker(QThread):
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished_plotting = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.input_folder = None
        self.sweep_type = None
        self.output_root = None

    def set_task(self, input_folder, sweep_type, output_root):
        """
        Update the values used for the next plotting task.

        This avoids creating a new PlotWorker every time.
        """
        self.input_folder = Path(input_folder)
        self.sweep_type = sweep_type
        self.output_root = Path(output_root)

    def run(self):
        try:
            if self.input_folder is None:
                raise ValueError("PlotWorker has no input folder. Call set_task() first.")

            if self.sweep_type is None:
                raise ValueError("PlotWorker has no sweep type. Call set_task() first.")

            if self.output_root is None:
                raise ValueError("PlotWorker has no output folder. Call set_task() first.")

            created_files = []

            for parameter in ["S21", "S11"]:
                magnitude_file, phase_file = make_both_plots(
                    input_folder=self.input_folder,
                    sweep_type=self.sweep_type,
                    parameter=parameter,
                    output_root=self.output_root,
                    show=False,
                )

                created_files.append(magnitude_file)
                created_files.append(phase_file)

            self.response_received.emit("Plot generation finished.")

            for file in created_files:
                self.response_received.emit(f"Created plot: {file}")

            self.finished_plotting.emit()

        except Exception as e:
            self.error_occurred.emit(
                f"Plot generation error: {type(e).__name__} - {e}"
            )

class TaskBox(QFrame):
    """A single custom box for a task"""

    def __init__(self, task_data, order, delete_callback):
        super().__init__()
        self.task_data = task_data
        self.delete_callback = delete_callback

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("TaskBox")

        self.main_layout = QHBoxLayout(self)

        self.label = QLabel()
        self.label.setStyleSheet("font-family: 'Courier New'; font-size: 12px;")
        self.update_display_text(order)

        self.btn_delete = QPushButton("✕")
        self.btn_delete.setFixedSize(24, 24)
        self.btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete.setStyleSheet("""
            QPushButton { 
                background-color: #e74c3c; color: white; border-radius: 12px; font-weight: bold; 
            }
            QPushButton:hover { background-color: #c0392b; }
        """)
        self.btn_delete.clicked.connect(lambda: self.delete_callback(self))

        self.main_layout.addWidget(self.label, stretch=1)
        self.main_layout.addWidget(self.btn_delete)

        self.setStyleSheet("""
            #TaskBox {
                background-color: #ffffff;
                border: 2px solid #34495e;
                border-radius: 8px;
                margin-bottom: 5px;
            }
        """)

    def update_display_text(self, order):
        if self.task_data[0] == "freq_sweep":
            name, s_freq, f_freq, scan, if_f, pwr, pts, from_temp, to_temp = self.task_data
            power_str = f"POWER: {pwr} dB"
        else:
            name, s_freq, f_freq, scan, if_f, s_pwr, f_pwr, pts, from_temp, to_temp = self.task_data
            power_str = f"POWER: {s_pwr} -> {f_pwr} dB"

        display_text = (
            f"[{order:02d}] TYPE: {name.upper()}\n"
            f"     FREQ : {s_freq} GHz -> {f_freq} GHz (IF: {if_f} Hz)\n"
            f"     {power_str}\n"
            f"     SCAN : {scan} | POINTS: {pts} per scan\n"
            f"     FROM_TEMP: {from_temp} mK | TO_TEMP: {to_temp} mK "
        )
        self.label.setText(display_text)


class SchedulerDisplay(QScrollArea):
    """The scrollable container for all tasks"""

    task_deleted = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)

        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.setWidget(self.container)

    def add_task(self, task_params):
        order = self.list_layout.count() + 1
        new_task = TaskBox(task_params, order, self.remove_task)
        self.list_layout.addWidget(new_task)

    def remove_task(self, task_widget):
        index = -1

        for i in range(self.list_layout.count()):
            if self.list_layout.itemAt(i).widget() == task_widget:
                index = i
                break

        if index != -1:
            self.list_layout.removeWidget(task_widget)
            task_widget.deleteLater()
            self.renumber_tasks()
            self.task_deleted.emit(index)

    def remove_task_index(self, index):
        if 0 <= index < self.list_layout.count():
            item = self.list_layout.itemAt(index)
            if item:
                widget = item.widget()
                if isinstance(widget, TaskBox):
                    self.remove_task(widget)

    def renumber_tasks(self):
        for i in range(self.list_layout.count()):
            item = self.list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, TaskBox):
                    widget.update_display_text(i + 1)


# --- Main Window ---
class SciControlApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.tasks = []
        self.current_task = None
        self.current_temp = None
        
        self.script_dir = Path(__file__).resolve().parent
        self.plot_root = self.script_dir / "plot"
        self.data_root = self.script_dir / "downloaded_s2p"

        self.starting_temp=None
        self.cooling=False
        self.is_starting_cycle = False
        
        self.setWindowTitle("SCPI Instrument Controller")
        self.resize(1500, 900)

        self.top_box = QHBoxLayout()

        # buttons, left section
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)

        self.btn_init = QPushButton("Connect to inst")
        self.addr = QLineEdit("10.1.199.8")
        self.folder_name = QLineEdit("")
        self.btn_init.clicked.connect(self.inst_init)
    
        #parameters
        self.start_freq = QLineEdit("1")        
        self.finish_freq = QLineEdit("8")
        self.scan_amount = QLineEdit("30")
        self.if_freq = QLineEdit("500")
        self.start_power = QLineEdit("-45")
        self.finish_power = QLineEdit("-15")
        self.points = QLineEdit("20001")
        self.from_temp = QLineEdit("150")
        self.to_temp = QLineEdit("200")


        self.btn_donwload = QCheckBox("Download data from VNA")
        self.btn_donwload.setChecked(True)

        self.btn_freq_sweep = QPushButton("Schedule a freq sweep")
        self.btn_freq_sweep.clicked.connect(self.freq_sweep)

        self.btn_power_sweep = QPushButton("Schedule a power sweep")
        self.btn_power_sweep.clicked.connect(self.power_sweep)

        self.left_layout.addWidget(QLabel("<b>SCPI Control</b>"))
        self.left_layout.addWidget(QLabel("Enter a VNA addr"))
        self.left_layout.addWidget(self.addr)
        self.left_layout.addWidget(QLabel("Enter a working directory (where saves will be on a VNA), left empty for current timestamp"))
        self.left_layout.addWidget(self.folder_name)
        self.left_layout.addWidget(self.btn_init)
        self.left_layout.addWidget(QLabel("Frequency start (in GHz)"))
        self.left_layout.addWidget(self.start_freq)
        self.left_layout.addWidget(QLabel("Frequency finish (in GHz)"))
        self.left_layout.addWidget(self.finish_freq)
        self.left_layout.addWidget(QLabel("Divide whole frequency into ... individual scans"))
        self.left_layout.addWidget(self.scan_amount)
        self.left_layout.addWidget(QLabel("IF freq (in Hz)"))
        self.left_layout.addWidget(self.if_freq)
        self.left_layout.addWidget(QLabel("Starting power for power sweep, or THE POWER for freq sweep (in dB)"))
        self.left_layout.addWidget(self.start_power)
        self.left_layout.addWidget(QLabel("Finish power for power sweep, not used in freq sweep (in dB)"))
        self.left_layout.addWidget(self.finish_power)
        self.left_layout.addWidget(QLabel("Points per scan"))
        self.left_layout.addWidget(self.points)
        self.left_layout.addWidget(QLabel("Temperature from which to scan (in mK)"))
        self.left_layout.addWidget(self.from_temp)
        self.left_layout.addWidget(QLabel("Temperature to which to scan (in mK)"))
        self.left_layout.addWidget(self.to_temp)
        self.left_layout.addWidget(self.btn_donwload)
        self.left_layout.addWidget(self.btn_freq_sweep)
        self.left_layout.addWidget(self.btn_power_sweep)

        # console
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1e1e1e; font-family: monospace;")

        # scheduler + file control
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.sensor_data = QLineEdit("10.1.197.100") 
        self.scheduler_ui = SchedulerDisplay()
        self.scheduler_ui.task_deleted.connect(self.sync_task_list)
        
        self.right_layout.addWidget(QLabel("Address of Cryoboss (set it before init)"))
        self.right_layout.addWidget(self.sensor_data)
        self.right_layout.addWidget(QLabel(f"last temperature at 50mK: {format_temp_mk(self.current_temp*1000)}mK"))
        self.right_layout.addWidget(self.scheduler_ui)

        self.top_box.addWidget(self.left_panel)
        self.top_box.addWidget(self.console)
        self.top_box.addWidget(self.right_panel)

        container = QWidget()
        container.setLayout(self.top_box)
        self.setCentralWidget(container)

        self.print_wrapper = lambda: self.log("Done downloading")

    def log(self, text, color="white"):
        formatted_text = f'<span style="color: {color};">{text}</span>'
        self.console.append(formatted_text)

    def inst_init(self):
        try:
            if hasattr(self, 'worker'):
                if self.worker.isRunning():
                    self.worker.quit()
                    self.worker.wait()
                del self.worker

            self.worker = InstrumentWorker(f"TCPIP0::{self.addr.text()}::5025::SOCKET")
            self.worker.create_task("init")
            self.worker.response_received.connect(self.handle_response)
            self.worker.error_occurred.connect(self.handle_error)
            self.worker.start()
            
            
            self.cryo_thread = QThread()
            self.cryoworker = CryobossWorker(self.sensor_data.text())
            self.cryoworker.moveToThread(self.cryo_thread)
            self.cryo_thread.started.connect(self.cryoworker.initialize_socket)
            self.cryoworker.debug_signal.connect(self.handle_response)
            self.cryoworker.error_signal.connect(self.handle_error)
            self.cryoworker.temperature_signal.connect(self.send_task)
            self.cryoworker.cycle_started_signal.connect(self.handle_cycle_status)
            self.cryo_thread.start()
            
            self.plot_worker = PlotWorker()
            self.plot_worker.response_received.connect(self.handle_response)
            self.plot_worker.error_occurred.connect(self.handle_error)
            self.plot_worker.finished_plotting.connect(self.handle_plot_finished)
            
        except Exception as e:
            self.handle_error(f"An unexpected error occurred: {type(e).__name__} - {e} in inst_init")
            del self.worker

    def freq_sweep(self):
        self.tasks.append(("freq_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.points.text(), self.from_temp.text(), self.to_temp.text()))
        self.scheduler_ui.add_task(("freq_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.points.text(), self.from_temp.text(), self.to_temp.text()))
        
    def power_sweep(self):
        self.tasks.append(("power_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.finish_power.text(), self.points.text(), self.from_temp.text(), self.to_temp.text()))
        self.scheduler_ui.add_task(("power_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.finish_power.text(), self.points.text(), self.from_temp.text(), self.to_temp.text()))
        
    def trigger_folder_creation(self):
        folder = self.folder_name.text().strip()
        self.target = folder if folder else time.strftime("%Y-%m-%d-%H-%M-%S")
        self.target = self.target +f"_{np.round(self.current_temp,2)}mK_{self.current_task[1]}-{self.current_task[2]}GHz_{self.current_task[0]}"
        self.log(f"Initializing working directory: {self.target}...")
        self.worker.create_task("work_dir", self.target)
        self.worker.start()

    def trigger_file_download(self):
        self.worker.finished_task.disconnect(self.trigger_file_download)

        self.download_folder = self.data_root / (self.target.split("_")[0]+ f"_{format_temp_mk(self.starting_temp*1000)}mK-{format_temp_mk(self.current_temp*1000)}mK")
        self.worker.download_folder_name = self.download_folder

        self.worker.create_task("file_download")
        self.worker.finished_task.connect(self.trigger_plot_generation)
        self.worker.start()

    def trigger_plot_generation(self):
        try:
            self.worker.finished_task.disconnect(self.trigger_plot_generation)
        except (TypeError, RuntimeError):
            pass

        self.log("Done downloading.", color="lightgreen")
        self.log("Generating HTML plots...", color="lightblue")

        if self.current_task[0] == "freq_sweep":
            sweep_type = "frequency"
        elif self.current_task[0] == "power_sweep":
            sweep_type = "power"
        else:
            self.handle_error(f"Unknown sweep type: {self.current_task[0]}")
            return

        if self.plot_worker.isRunning():
            self.handle_error("Plot worker is already running. Skipping new plot task.")
            return

        self.plot_worker.set_task(
            input_folder=self.download_folder,
            sweep_type=sweep_type,
            output_root=self.plot_root,
        )

        self.plot_worker.start()

    def trigger_freq_sweep(self):
        task = self.current_task

        if hasattr(self, 'worker'):
            self.worker.finished_task.disconnect(self.trigger_freq_sweep)
            if self.worker.isRunning():
                self.log("Wait! An experiment is already in progress.", color="orange")
                return
        else:
            self.log("No instruments were initialized", color="orange")
            return

        if self.btn_donwload.isChecked():
            self.worker.finished_task.connect(self.trigger_file_download)
        self.worker.create_task("freq_sweep",*task[1:-2])
        self.worker.start()

    def trigger_power_sweep(self):
        task = self.current_task

        if hasattr(self, 'worker'):
            self.worker.finished_task.disconnect(self.trigger_power_sweep)
            if self.worker.isRunning():
                self.log("Wait! An experiment is already in progress.", color="orange")
                return
        else:
            self.log("No instruments were initialized", color="orange")
            return

        if self.btn_donwload.isChecked():
            self.worker.finished_task.connect(self.trigger_file_download)
        self.worker.create_task("power_sweep",*task[1:-2])
        self.worker.start()
        
    def send_task(self, got_temp):
        self.current_temp=got_temp
        try:
            self.worker.finished_task.disconnect(self.print_wrapper)
        except (TypeError, RuntimeError):
            pass

        try:
            if not self.tasks:
                return
            if(not self.cooling):
                for index, task in enumerate(self.tasks):
                    if ((self.current_temp*1000)<=float(task[-1]) and (self.current_temp*1000)>=float(task[-2]) and not self.worker.isRunning()):
                        self.current_task=task
                        if(task[0] == "freq_sweep"):
                            self.worker.finished_task.connect(self.trigger_freq_sweep)
                        elif(task[0] == "power_sweep"):
                            self.worker.finished_task.connect(self.trigger_power_sweep)
                        else:
                            self.handle_error(f"Unknown task: {self.tasks[0]}")
                        self.trigger_folder_creation()
                        self.log(f"Starting new measurement:{task[0]} with expected temp:{task[-1]}mK, current temp:{self.current_temp*1000}mK")
                        self.starting_temp = self.current_temp
                        self.scheduler_ui.remove_task_index(index)
                        break
                    
            if(not self.worker.isRunning() and len(self.tasks)>0 and not self.cooling and not self.is_starting_cycle):
                self.handle_response("Starting cooling cycle")
                self.is_starting_cycle = True
                QTimer.singleShot(0, self.cryoworker.start_cycle_request)
                    
            if(self.current_temp<0.150):
                self.cooling=False
                
        except Exception as e:
            self.handle_error(f"An unexpected error occurred: {type(e).__name__} - {e} in send_task")
            
    def handle_cycle_status(self, success):
        self.is_starting_cycle = False
        if success:
            self.log("Cryoboss cycle started successfully. Cooling...", color="green")
            self.cooling = True
        else:
            self.handle_error("Cryoboss failed to start cycle.")
            self.cooling = False
        
    def sync_task_list(self, index):
        if 0 <= index < len(self.tasks):
            removed = self.tasks.pop(index)
            self.log(f"Removed task {index + 1} from schedule: {removed[0]}", color="gray")

    def handle_response(self, text):
        self.log(f"{text}", color="white")

    def handle_error(self, err):
        self.log(f"ERROR: {err}", color="#ff4d4d")

    def handle_plot_finished(self):
        self.log("All plots saved successfully.", color="lightgreen")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SciControlApp()
    window.show()
    sys.exit(app.exec())