import pyvisa
import time
import atexit
import numpy as np
import pandas as pd
import io

def vna_init():
    global vna
    
    rm = pyvisa.ResourceManager()
    
    try:
        vna = rm.open_resource('TCPIP0::10.1.199.8::5024::SOCKET', read_termination='\n')
        welcome = vna.read()
        print(welcome)
        idn = vna.query('*IDN?')
        print(f"Connected to: {idn}")

    except pyvisa.errors.VisaIOError as e:
        print(f"VISA IO Error: {e.description}")
        raise
    except ConnectionRefusedError:
        print("Error: The VNA refused the connection. Check if the socket server is enabled.")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {type(e).__name__} - {e}")
        raise
    

    def cleanup():
        print("Atexit: Closing the conenction...")
        vna.close()
    
    atexit.register(cleanup)

    try:
        vna.write(":MMEMory:STORe:SNP:FORMat 'RI'")
        dat = vna.query(":MMEMory:STORe:SNP:FORMat?")
        vna.write(":CALCulate1:PARameter1:DEFine 'S21'")
        s21 = vna.query(":CALCulate1:PARameter1:DEFine?")
        
        print(f"Set to {s21}, data reading to {dat}")
    except pyvisa.errors.VisaIOError as e:
        print(f"VISA IO Error: {e.description}")
        raise
    except ConnectionRefusedError:
        print("Error: The VNA refused the connection. Check if the socket server is enabled.")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {type(e).__name__} - {e}")
        raise
        
def test_func(cmd):
    start = time.perf_counter()
    ret = vna.query(f"{cmd}")
    end = time.perf_counter()
    print(f"Return : {ret} \n Finished in   {end - start:.6f} seconds ")

def working_dir(name):
    global path
    try:
        check = vna.query(':MMEMory:CATalog:DIR? "/local"')
        
        if(not (name in check)):
            vna.write(f':MMEM:MDIR "/local/auto/{name}"')
        vna.write(f':MMEMory:CDIRectory "/local/auto/{name}"')
        time.sleep(1)
        path = vna.query(':MMEM:CDIR?').replace('"','')
        print(f"Working dir:{path}")
    except pyvisa.errors.VisaIOError as e:
        print(f"VISA IO Error: {e.description}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {type(e).__name__} - {e}")
        raise
        
def do_scan(start_freq, finish_freq, if_freq, power, point, name=None):
    start = time.perf_counter()
    try:
        vna.write(f":SENSe1:SWEep:POINts {point}")
        points = vna.query(":SENSe1:SWEep:POINts?")
        vna.write(f":SOURce1:POWer {power}")
        pow = vna.query(":SOURce1:POWer?")
        vna.write(f':SENSe1:FREQuency:STARt {start_freq}')
        vna.write(f':SENSe1:FREQuency:STOP {finish_freq}')
        start = (vna.query(":SENSe1:FREQuency:STARt?")).strip('\x00').strip()
        finish = (vna.query(":SENSe1:FREQuency:STOP?")).strip('\x00').strip()
        vna.write(f':SENSe1:BANDwidth {if_freq}')
        if_freq_vna = vna.query(":SENSe1:BANDwidth?")
        
        vna.write("TRIG:SOUR BUS")
        
        print(f"doing a scan for {points} points, from {int(start)/1e9}ghz to {int(finish)/1e9}ghz with IF frequency {if_freq_vna}hz and power {pow}dB")
        
        vna.write("TRIG:SING")
        
        print("waiting the scan...")
        
        vna.timeout = 1e5 # 100 sec
        vna.query("*OPC?")
        vna.timeout = 1e4
        
        print("scan done")
        
        if(name==None):
            vna.write(f':MMEMory:STORe:SNP "{int(start)/1e9}ghz-{int(finish)/1e9}ghz.s2p"')
        else:
            vna.write(f':MMEMory:STORe:SNP "{name}.s2p"')
            
        print("scan saved")
        
        end = time.perf_counter()
        print(f"Elapsed time: {end - start:.6f} seconds")
        
    except pyvisa.errors.VisaIOError as e:
        print(f"VISA IO Error: {e.description}")
        print(f"timeout was {vna.timeout/1e3} sec")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {type(e).__name__} - {e}")
        raise
        
def freq_sweep(start_freq, stop_freq, scan_amount, if_freq, power, points):
    step = (stop_freq-start_freq)/scan_amount
    for i in range(0,scan_amount):
        do_scan(start_freq+i*step,start_freq+(i+1)*step,if_freq,power,points)
        
def power_sweep(start_freq, stop_freq, scan_amoint, if_freq, start_power, stop_power, points):
    step = (stop_power - start_power)/scan_amoint
    for i in range(0,scan_amoint+1):
        do_scan(start_freq, stop_freq, if_freq, start_power+i*step, points)


def write_data(vna_file,data):
    
    print("start write")
    vna.chunk_size = 10240
    vna.timeout = 10000
    data = vna.write(f':MMEMory:TRANsfer "{vna_file}", "{data}"')
    
    print("transfer success \n data:")
    print(data)
        
def read_data(vna_file):
    
    print("start read")
    vna.chunk_size = 10240
    vna.timeout = 10000
    data = vna.query(f':MMEMory:TRANsfer? "{vna_file}"')
    
    print("transfer success \n data:")
    print(data)
        
# if __name__ == "__main__":
#     vna_init()
#     working_dir(time.strftime("%Y-%m-%d-%H-%M-%S"))
#     freq_sweep(1.8*1e9,2.6*1e9,8,100,-55,10001)
    
if __name__ == "__main__":
    vna_init()
    REMOTE_FILE = "local/11.csv"
    try:
        vna.chunk_size = 1024 * 1024
        vna.timeout = 10000
        
        # 1. Generate Random Data
        df = pd.DataFrame({
            'Frequency_Hz': np.linspace(1e6, 6e9, 10),
            'Magnitude_dB': np.random.uniform(-60, 0, 10)
        })
        csv_text = df.to_csv(index=False)
        csv_bytes = csv_text.encode('utf-8')
        
        # 2. MANUALLY Construct the IEEE 488.2 Header
        # Let's say csv_bytes is 1234 bytes.
        # The length string is "1234" (4 digits).
        # The header is "#" + "4" + "1234"
        data_len = len(csv_bytes)
        len_str = str(data_len)
        header = f"#{len(len_str)}{len_str}"
        
        # 3. Combine everything into one big byte payload
        # Format: :MMEM:TRAN <filename>,#<len_len><len><data>
        command = f":MMEMory:TRANsfer {REMOTE_FILE},".encode('utf-8')
        full_payload = command + header.encode('utf-8') + csv_bytes
        
        print(f"Total Transaction Size: {len(full_payload)} bytes")
        print(f"Header used: {header}")

        # 4. Send the raw bytes directly
        # We use write_raw because we've already built the header manually
        vna.write(full_payload)

        print("Transfer successful.")

    except Exception as e:
        print(f"Error: {e}")
        
# if __name__ == "__main__":
#     vna_init()
#     working_dir(time.strftime("%Y-%m-%d"))
    
#     start = 70e8
#     finish = 75e8
    
#     print(f':MMEMory:STORe:SNP "{path}/{int(start)/1e9}ghz-{int(finish)/1e9}ghz.s2p"')
#     print(path)
    
#     vna.write(f':MMEMory:STORe:SNP "{int(start)/1e9}ghz-{int(finish)/1e9}ghz.s2p"')