import os
import time
import csv
from datetime import datetime
import wmi  # type: ignore
import pythoncom  # type: ignore
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def start_power_monitoring(interval_seconds, stop_event, output_dir=None):
    pythoncom.CoInitialize()
    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    power_file = os.path.join(output_dir, "power_metrics.csv")
    mode = 'a' if os.path.exists(power_file) else 'w'
    
    try:
        with open(power_file, mode, newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if mode == 'w':
                writer.writerow(["timestamp", "power_watts"])
            file.flush()

            c = wmi.WMI()
            while not stop_event.is_set():
                start_time = time.perf_counter()
                timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                power_watts = get_power_usage(c)
                writer.writerow([timestamp, power_watts])
                file.flush()
                elapsed_time = time.perf_counter() - start_time
                stop_event.wait(max(0, interval_seconds - elapsed_time))

    except KeyboardInterrupt:
        logger.info("Power monitoring stopped by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        pythoncom.CoUninitialize()

def get_power_usage(c):
    try:
        power_watts = 0.0
        try:
            processor_power = c.Win32_PerfFormattedData_Counters_ProcessorInformation()[0]
            perf_percent = float(processor_power.PercentProcessorPerformance)
            power_watts = perf_percent * 0.65  
        except Exception as e:
            logger.error(f"Performance counter error: {e}")
        try:
            battery = c.Win32_Battery()
            if battery and battery[0].DischargeRate:
                discharge_rate = float(battery[0].DischargeRate)
                if discharge_rate != 0:
                    power_watts = abs(discharge_rate / 1000)  
        except Exception as e:
            logger.error(f"WMI error: {e}")
            pass
        return power_watts
    except Exception as e:
        logger.error(f"Power monitoring error: {e}")
        return 0.0
