import sys
import os
import csv
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QFileSystemWatcher, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QTextEdit

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

class MainWindow(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle("Real-Time CSV Monitor")
        self.resize(600, 400)
        
        self.display = QTextEdit()
        self.display.setReadOnly(True)
        self.setCentralWidget(self.display)

        # Thread Setup
        self.thread = QThread()
        self.worker = CSVWorker(path)
        self.worker.moveToThread(self.thread)

        # Signal Connections
        self.thread.started.connect(self.worker.start_monitoring)
        self.worker.new_row_signal.connect(self.handle_new_data)
        self.worker.error_signal.connect(lambda e: print(f"Worker Error: {e}"))
        
        self.thread.start()

    def handle_new_data(self, data):
        self.display.append(f"Row: {', '.join(data)}")

    def closeEvent(self, event):
        self.thread.quit()
        self.thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # --- IMPORTANT: Ensure this file actually exists before running ---
    target_file = "/mnt/d/manual_file_name_auto.csv" 
    if not os.path.exists(target_file):
        with open(target_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Value"])

    win = MainWindow(target_file)
    win.show()
    sys.exit(app.exec())