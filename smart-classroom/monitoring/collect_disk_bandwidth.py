import os
import time
import csv
from datetime import datetime
import wmi
import pythoncom

def start_disk_bandwidth_monitoring(interval_seconds=1, output_dir=None):
    pythoncom.CoInitialize()

    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    disk_file = os.path.join(output_dir, "disk_bandwidth_metrics.csv")
    print(f"Starting disk bandwidth monitoring to {disk_file}...")

    # Write header to CSV file
    with open(disk_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "read_bytes_per_sec", "write_bytes_per_sec"])

    def get_disk_io(c):
        try:
            read_bytes = 0.0
            write_bytes = 0.0

            # Get disk counters
            read_counter = c.Win32_PerfFormattedData_PerfDisk_LogicalDisk()[0]
            write_counter = c.Win32_PerfFormattedData_PerfDisk_LogicalDisk()[0]

            read_bytes = float(read_counter.DiskReadBytesPerSec)
            write_bytes = float(write_counter.DiskWriteBytesPerSec)

            return read_bytes, write_bytes
        except Exception as e:
            print(f"Disk monitoring error: {e}")
            return 0.0, 0.0

    try:
        c = wmi.WMI()
        while True:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            read_bytes, write_bytes = get_disk_io(c)

            with open(disk_file, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, read_bytes, write_bytes])

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nDisk bandwidth monitoring stopped by user.")
    finally:
        print("Disk bandwidth monitoring finished.")
        pythoncom.CoUninitialize()