import os
import time
import csv
from datetime import datetime
import wmi # type: ignore
import pythoncom # type: ignore
import logging
logger = logging.getLogger(__name__)

def start_power_monitoring(interval_seconds, stop_event, output_dir=None):
    pythoncom.CoInitialize()
    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    power_file = os.path.join(output_dir, "power_metrics.csv")
    # logger.info(f"Starting power monitoring to {power_file}...")

    # Write header to CSV file
    with open(power_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "power_watts"])

    def get_power_usage(c):
        try:
            power_watts = 0.0
            # First, try Intel processor power counters if available
            try:
                processor_power = c.Win32_PerfFormattedData_Counters_ProcessorInformation()[0]
                perf_percent = float(processor_power.PercentProcessorPerformance)
                power_watts = perf_percent * 0.65  # Rough estimate: 65W max TDP for Intel
            except Exception as e:
                logger.error(f"Performance counter error: {e}")
            # Then, try to get actual power information from WMI (if available)
            try:
                battery = c.Win32_Battery()
                if battery and battery[0].DischargeRate:
                    discharge_rate = float(battery[0].DischargeRate)
                    if discharge_rate != 0:
                        power_watts = abs(discharge_rate / 1000)  # Convert mW to W
            except Exception as e:
                logger.error(f"WMI error: {e}")
                pass
            return power_watts
        except Exception as e:
            logger.error(f"Power monitoring error: {e}")
            return 0.0
    try:
        c = wmi.WMI()
        while not stop_event.is_set():
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            power_watts = get_power_usage(c)
            with open(power_file, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, power_watts])
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("\nPower monitoring stopped by user.")
    finally:
        # logger.info("Power monitoring finished.")
        pythoncom.CoUninitialize()