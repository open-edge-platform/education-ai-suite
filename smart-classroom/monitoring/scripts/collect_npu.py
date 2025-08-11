import os
import time
import csv
from datetime import datetime
import wmi # type: ignore
import logging
logger = logging.getLogger(__name__)

def start_npu_monitoring(interval_seconds, stop_event, output_dir=None):
    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    npu_file = os.path.join(output_dir, "npu_utilization.csv")
    # logger.info(f"Starting NPU monitoring to {npu_file}...")

    # Write header to CSV file
    with open(npu_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "npu_utilization"])

    def get_intel_npu_usage():
        try:
            # Initialize WMI
            c = wmi.WMI()

            # Query for Intel NPU devices
            npu_devices = c.Win32_PnPEntity(Name="*Intel*NPU*") + \
                          c.Win32_PnPEntity(Name="*Intel*Neural*") + \
                          c.Win32_PnPEntity(Name="*Intel*VPU*")
            if npu_devices:
                # Device exists but no performance data available
                return 0.0
            return None
        except Exception as e:
            return None

    try:
        while not stop_event.is_set():
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            usage = get_intel_npu_usage()

            if usage is None:
                usage = 0.0

            usage_formatted = f"{usage:.2f}"
            
            with open(npu_file, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, usage_formatted])
            
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("\nNPU monitoring stopped by user.")
    finally:
        # logger.info("NPU monitoring finished.") 
        pass