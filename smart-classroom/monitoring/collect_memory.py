import os
import time
import csv
from datetime import datetime
import wmi
import pythoncom

def start_memory_monitoring(interval_seconds=1, output_dir=None):
    pythoncom.CoInitialize()

    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    memory_file = os.path.join(output_dir, "memory_metrics.csv")
    print(f"Starting memory monitoring to {memory_file}...")

    # Write header to CSV file
    with open(memory_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "total_kb", "used_kb", "free_kb", "shared_kb", "buffers_kb", "cached_kb"])

    def get_memory_usage(c):
        try:
            memory = c.Win32_OperatingSystem()[0]
            total_mem = float(memory.TotalVisibleMemorySize)
            free_mem = float(memory.FreePhysicalMemory)
            used_mem = total_mem - free_mem

            # Windows doesn't have exact equivalents to Linux shared/buffers/cached
            shared_mem = 0.0
            buffers_mem = 0.0
            cached_mem = 0.0

            return total_mem, used_mem, free_mem, shared_mem, buffers_mem, cached_mem
        except Exception as e:
            print(f"Memory monitoring error: {e}")
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    try:
        c = wmi.WMI()
        while True:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            total_mem, used_mem, free_mem, shared_mem, buffers_mem, cached_mem = get_memory_usage(c)

            with open(memory_file, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, total_mem, used_mem, free_mem, shared_mem, buffers_mem, cached_mem])

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nMemory monitoring stopped by user.")
    finally:
        print("Memory monitoring finished.")
        pythoncom.CoUninitialize()