import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QScrollArea, QFrame,
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QFileSystemWatcher, QObject
import pyqtgraph as pg
import pyvisa
import numpy as np
import time
import csv  

#worker for async work
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
        self.folder_name = None
        
    def create_task(self, task_type, *args):
        self.task_type=task_type
        self.params= args
        print(self.params)
        
    def run(self):
        try:
            if self.task_type == "init":
                rm = pyvisa.ResourceManager()
                print(self.resource_name)
                self.inst = rm.open_resource(self.resource_name, read_termination='\n')
                self.inst.read()
                id = self.inst.query('*IDN?')
                self.response_received.emit(id)
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
            self.error_occurred.emit(f"An unexpected error occurred in run: {type(e).__name__} - {e}")

    def working_dir(self, name):
        try:
            check = self.inst.query(':MMEMory:CATalog:DIR? "/local"')
            if(not (name in check)):
                self.inst.write(f':MMEM:MDIR "/local/auto/{name}"')
            self.inst.write(f':MMEMory:CDIRectory "/local/auto/{name}"')
            path = self.inst.query(':MMEM:CDIR?').replace('"','')
            self.response_received.emit(f"Working dir:{path}")
        except pyvisa.errors.VisaIOError as e:
            self.error_occurred.emit(f"VISA IO Error in working_dir: {e.description}")
        except Exception as e:
            self.error_occurred.emit(f"An unexpected error occurred in working_dir: {type(e).__name__} - {e}")
            
    def file_download(self):
        self.inst.chunk_size = 20 * 1024 * 1024
        self.inst.timeout = 10000
        files = self.inst.query(':MMEMory:CATalog?')
        files = files.split(",")
        os.makedirs(self.folder_name,exist_ok=True)
        for file in files:
            file = file.strip('"\x00 \n\r')
            if not file:
                continue
            self.response_received.emit(f"Downloading {file}")
            file_data = self.inst.query_binary_values(f':MMEMory:TRANsfer? "{file}"', datatype='B', container=bytes)
            with open(f"./{self.folder_name}/{file}", "wb") as f:
                f.write(file_data)
        self.inst.timeout = 3000
            
    def do_scan(self, start_freq, finish_freq, if_freq, power, point, name):
        start_time = time.perf_counter()
        try:
            self.inst.write(f":SENSe1:SWEep:POINts {point}")
            points = self.inst.query(":SENSe1:SWEep:POINts?")
            self.inst.write(f":SOURce1:POWer {power}")
            pow = self.inst.query(":SOURce1:POWer?")
            self.inst.write(f':SENSe1:FREQuency:STARt {start_freq*1e9}')
            self.inst.write(f':SENSe1:FREQuency:STOP {finish_freq*1e9}')
            start = (self.inst.query(":SENSe1:FREQuency:STARt?")).strip('\x00').strip()
            finish = (self.inst.query(":SENSe1:FREQuency:STOP?")).strip('\x00').strip()
            self.inst.write(f':SENSe1:BANDwidth {if_freq}')
            got_if_freq = self.inst.query(":SENSe1:BANDwidth?")
            
            self.inst.write("TRIG:SOUR BUS")
            
            self.response_received.emit(f"doing a scan for {str(points)} points, from {float(start)/1e9}ghz to {float(finish)/1e9}ghz with IF frequency {str(got_if_freq)}hz and power {pow}dB")
            
            self.inst.write("TRIG:SING")
            
            self.response_received.emit("waiting the scan...")
            
            self.inst.timeout = 1e5 # 100 sec
            self.inst.query("*OPC?")
            self.inst.timeout = 1e4
            
            self.response_received.emit("scan done")
            
            if(name==None):
                self.inst.write(f':MMEMory:STORe:SNP "{float(start)/1e9}GHz-{float(finish)/1e9}GHz-{float(power)}dB.s2p"')
            else:
                self.inst.write(f':MMEMory:STORe:SNP "{name}.s2p"')
                
            self.response_received.emit("scan saved")
            
            end_time = time.perf_counter()
            self.response_received.emit(f"Elapsed time: {end_time - start_time:.6f} seconds")
            
        except pyvisa.errors.VisaIOError as e:
            self.error_occurred.emit(f"VISA IO Error in do_scan: {e}")
            self.error_occurred.emit(f"timeout was {self.inst.timeout/1e3} sec")
        except Exception as e:
            self.error_occurred.emit(f"An unexpected error occurred in do_scan: {type(e).__name__} - {e}")

    def freq_sweep(self, start_freq, stop_freq, scan_amount, if_freq, power, points, name=None):
        step = (float(stop_freq)-float(start_freq))/int(scan_amount)
        for i in range(int(scan_amount)):
            self.do_scan(float(start_freq)+i*step,float(start_freq)+(i+1)*step,if_freq,power,points, name)
            
    def power_sweep(self, start_freq, stop_freq, scan_amount, if_freq, start_power, stop_power, points, name=None):
        step = (float(stop_power)-float(start_power))/int(scan_amount)
        for i in range(int(scan_amount)):
            self.do_scan(float(start_freq), float(stop_freq), if_freq, float(start_power)+(i*step), points, name)

#data parser from some csv
class CSVWorker(QObject):
    new_row_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = os.path.abspath(file_path)
        self.last_position = os.path.getsize(self.file_path) if os.path.exists(self.file_path) else 0

    def start_monitoring(self):
        self.watcher = QFileSystemWatcher()
        if os.path.exists(self.file_path):
            self.watcher.addPath(self.file_path)
        
        self.watcher.fileChanged.connect(self.process_file)
        
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.process_file)
        self.check_timer.start(2000) # Check every 2 seconds
        
        print(f"Monitoring: {self.file_path}")
        
    def process_file(self):
        if not os.path.exists(self.file_path):
            print("No such file")

        try:
            current_size = os.path.getsize(self.file_path)
            
            if current_size > self.last_position:
                with open(self.file_path, 'r', newline='', encoding='utf-8') as f:
                    f.seek(self.last_position)
                    reader = csv.reader(f)
                    for row in reader:
                        if row:
                            self.new_row_signal.emit(row)
                    self.last_position = f.tell()
                    
        except PermissionError:
            # File is likely locked by another process (common on Windows)
            pass 
        except Exception as e:
            self.error_signal.emit(str(e))

class TaskBox(QFrame):
    """A single custom box for a task"""
    def __init__(self, task_data, order, delete_callback):
        super().__init__()
        self.task_data = task_data # Store data for easier re-rendering
        self.delete_callback = delete_callback
        
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("TaskBox") # Used for specific CSS targeting
        
        # Main layout for the box
        self.main_layout = QHBoxLayout(self)
        
        # Label to display task details
        self.label = QLabel()
        self.label.setStyleSheet("font-family: 'Courier New'; font-size: 12px;")
        self.update_display_text(order)
        
        # Delete button
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
        """Helper to set or refresh the text based on its position in the list"""
        if self.task_data[0] == "freq_sweep":
            name, s_freq, f_freq, scan, if_f, pwr, pts, temp = self.task_data
            power_str = f"POWER: {pwr} dB"
        else:
            name, s_freq, f_freq, scan, if_f, s_pwr, f_pwr, pts, temp = self.task_data
            power_str = f"POWER: {s_pwr} -> {f_pwr} dB"

        display_text = (
            f"[{order:02d}] TYPE: {name.upper()}\n"
            f"     FREQ : {s_freq} GHz -> {f_freq} GHz (IF: {if_f} Hz)\n"
            f"     {power_str}\n"
            f"     SCAN : {scan} | POINTS: {pts} per scan | TEMP: {temp} mK"
        )
        self.label.setText(display_text)

class SchedulerDisplay(QScrollArea):
    """The scrollable container for all tasks"""
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.setWidget(self.container)

    def add_task(self, task_params):
        order = self.list_layout.count() + 1
        # Pass self.remove_task as the callback
        new_task = TaskBox(task_params, order, self.remove_task)
        self.list_layout.addWidget(new_task)
        
    def remove_task(self, task_widget):
        """Removes the widget from layout and deletes it"""
        self.list_layout.removeWidget(task_widget)
        task_widget.deleteLater() 
        # Schedule renumbering for after the widget is officially gone
        self.renumber_tasks()

    def renumber_tasks(self):
        """Loops through remaining widgets to update their [XX] labels"""
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
        self.current_task=0
        
        self.setWindowTitle("SCPI Instrument Controller")
        self.resize(1500, 900)

        # UI Elements
        self.top_box = QHBoxLayout()


        #buttons (left section)
    
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.btn_init = QPushButton("Connect to inst")
        self.addr = QLineEdit("10.1.199.8")
        self.folder_name = QLineEdit("")
        self.btn_init.clicked.connect(self.inst_init)
    
        #parameters
        self.start_freq = QLineEdit("3")        
        self.finish_freq = QLineEdit("8")
        self.scan_amount = QLineEdit("10")
        self.if_freq = QLineEdit("500")
        self.start_power = QLineEdit("-40")
        self.finish_power = QLineEdit("-20")
        self.points = QLineEdit("5001")
        self.temp = QLineEdit("300")

        self.btn_donwload =  QCheckBox("Download data from VNA")
        self.btn_donwload.setChecked(True)

        self.btn_freq_sweep = QPushButton("Schedule a freq sweep")
        self.btn_freq_sweep.clicked.connect(self.freq_sweep)
        self.btn_power_sweep = QPushButton("Schedule a power sweep")
        self.btn_power_sweep.clicked.connect(self.power_sweep)
        
        #left side constructor
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
        self.left_layout.addWidget(QLabel("Divide whole frequency in to ... individual scans"))
        self.left_layout.addWidget(self.scan_amount)
        self.left_layout.addWidget(QLabel("IF freq (in Hz)"))
        self.left_layout.addWidget(self.if_freq)
        self.left_layout.addWidget(QLabel("Starting power for power sweep, or THE POWER for freq sweep (in dB)"))
        self.left_layout.addWidget(self.start_power)
        self.left_layout.addWidget(QLabel("Finish power for power sweep, not used in freq sweep (in dB)"))
        self.left_layout.addWidget(self.finish_power)
        self.left_layout.addWidget(QLabel("Points per scan"))
        self.left_layout.addWidget(self.points)
        self.left_layout.addWidget(QLabel("Temperature at which to scan (in mK)"))
        self.left_layout.addWidget(self.temp)
        self.left_layout.addWidget(self.btn_donwload)
        self.left_layout.addWidget(self.btn_freq_sweep)
        self.left_layout.addWidget(self.btn_power_sweep)
        
        #console (middle section)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1e1e1e; font-family: monospace;")

        #scheduler + file control (right section)
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.sensor_data = QLineEdit("/mnt/z/manual_file_name_auto.csv" ) 
        self.scheduler_ui = SchedulerDisplay()
        
        self.right_layout.addWidget(QLabel("Address from which to pull temperature data (set it before init)"))
        self.right_layout.addWidget(self.sensor_data)
        self.right_layout.addWidget(self.scheduler_ui)

        #top constructor
        self.top_box.addWidget(self.left_panel)
        self.top_box.addWidget(self.console)
        self.top_box.addWidget(self.right_panel)
        container = QWidget()
        container.setLayout(self.top_box)
        self.setCentralWidget(container)

        
    def log(self, text, color="white"):
            # We wrap the text in a <span> tag with inline CSS for color
            formatted_text = f'<span style="color: {color};">{text}</span>'
            self.console.append(formatted_text)
            
    def inst_init(self):
        if hasattr(self, 'worker'):
            self.log("Instrument already initiated (restart code, i will add this feature later)", color="orange")
            return
        try:
            self.worker = InstrumentWorker(f"TCPIP0::{self.addr.text()}::5024::SOCKET")
            self.worker.create_task("init")
            self.worker.response_received.connect(self.handle_response)
            self.worker.error_occurred.connect(self.handle_error)
            self.worker.start()
            self.csv_reader = CSVWorker(self.sensor_data.text())
            self.csv_reader.new_row_signal.connect(self.send_task)
            
        except Exception as e:
            self.handle_error(f"An unexpected error occurred: {type(e).__name__} - {e}")
            del self.worker
            
            
    def freq_sweep(self):
        self.tasks.append(("freq_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.points.text(), self.temp.text()))
        self.scheduler_ui.add_task(("freq_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.points.text(), self.temp.text()))
        
    def power_sweep(self):
        self.tasks.append(("power_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.finish_power.text(), self.points.text(), self.temp.text()))
        self.scheduler_ui.add_task(("power_sweep",self.start_freq.text(), self.finish_freq.text(), self.scan_amount.text(), self.if_freq.text(),
                               self.start_power.text(), self.finish_power.text(), self.points.text(), self.temp.text()))
        
    def trigger_folder_creation(self):
        folder = self.folder_name.text().strip()
        self.target = folder if folder else time.strftime("%Y-%m-%d-%H-%M-%S")
        self.log(f"Initializing working directory: {self.target}...")
        self.worker.create_task("work_dir",self.target)
        
    def trigger_file_download(self):
        self.worker.finished_task.disconnect(self.trigger_file_download)
        self.worker.folder_name = self.target
        self.worker.create_task("file_download")
        self.worker.finished_task.connect(lambda: self.log("Done downloading"))
        self.worker.start()
        
    def trigger_freq_sweep(self):
        self.worker.finished_task.disconnect(self.trigger_freq_sweep)
        task = self.current_task
        if hasattr(self, 'worker'):
            if self.worker.isRunning():
                self.log("Wait! An experiment is already in progress.", color="orange")
                return
        else:
            self.log("No instruments were initialized", color="orange")
            return
        if self.btn_donwload.isChecked():
            self.worker.finished_task.connect(self.trigger_file_download)
        self.worker.create_task("freq_sweep",*task)
        self.worker.start()

    def trigger_power_sweep(self):
        self.worker.finished_task.disconnect(self.trigger_power_sweep)
        task = self.current_task
        if hasattr(self, 'worker'):
            if self.worker.isRunning():
                self.log("Wait! An experiment is already in progress.", color="orange")
                return
        else:
            self.log("No instruments were initialized", color="orange")
            return
        if self.btn_donwload.isChecked():
            self.worker.finished_task.connect(self.trigger_file_download)
        self.worker.create_task("power_sweep",*task)
        self.worker.start()
        
    def send_task(self,*args):
        try:
            if ((float(args[3])*1000)>=float(self.tasks[0][-1]) and not self.worker.isRunning()):
                task=self.tasks[0]
                self.current_task=task
                self.trigger_folder_creation()
                if(task[0] == "freq_sweep"):
                    self.worker.finished_task.connect(self.trigger_freq_sweep)
                elif(task[0] == "power_sweep"):
                    self.worker.finished_task.connect(self.trigger_power_sweep)
                else:
                    self.handle_error(f"Unknown task: {self.tasks[0]}")
                self.worker.start() #maybe move it to trigger_folder_creation
                self.scheduler_ui.remove_task_index(0)
                self.tasks.pop(0)
                
        except Exception as e:
            self.handle_error(f"An unexpected error occurred: {type(e).__name__} - {e}")
        
    def handle_response(self, text):
        self.log(f"{text}", color = "white")
        
    def handle_error(self, err):
        self.log(f"ERROR: {err}", color="#ff4d4d")

    

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SciControlApp()
    window.show()
    sys.exit(app.exec())
    
    
    
    #possible graph code
    
        # #graph (mid section) (mostly not for vna just a template)
        # self.graph = pg.PlotWidget()
        # self.graph.setBackground('k')
        # self.graph.showGrid(x=True, y=True)
        # self.graph.setLabel('left', 'Amplitude', units='V')
        # self.graph.setLabel('bottom', 'Samples')
        
        # self.y_data = np.zeros(100) #buff for graph   
        
        # # creates a graph object        
        # self.curve = self.graph.plot(pen=pg.mkPen(color='g', width=2))