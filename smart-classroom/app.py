from fastapi import FastAPI, BackgroundTasks
import threading
import os
import subprocess
import time
from monitoring.collect_cpu import start_cpu_monitoring
from monitoring.collect_npu import start_npu_monitoring
from monitoring.collect_gpu import start_gpu_monitoring
from monitoring.collect_memory import start_memory_monitoring
from monitoring.collect_disk_bandwidth import start_disk_bandwidth_monitoring
from monitoring.collect_power import start_power_monitoring

app = FastAPI()

# Lock for thread safety
utilization_lock = threading.Lock()

# Dictionary to store the utilization values with timestamps
latest_utilization = {
    "cpu_utilization": [],
    "gpu_utilization": [],
    "npu_utilization": [],
    "memory": [],
    "disk_bandwidth": [],
    "power": []
}

# Global variable to control the monitoring process
monitoring_active = False

# Define the interval for monitoring
INTERVAL_SECONDS = 2

# Define the output directory
OUTPUT_DIR = os.getcwd()

def read_log_file(file_path, key, indices):
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
            with utilization_lock:
                latest_utilization[key] = []  # Clear existing data
                for line in lines[1:]:  # Skip header
                    values = line.strip().split(",")
                    timestamp = values[0]
                    data_points = [float(values[i]) for i in indices]
                    latest_utilization[key].append([timestamp] + data_points)
                print(f"Updated {key}: {latest_utilization[key]}")  # Debugging output
    except Exception as e:
        print(f"Error reading log file {file_path}: {e}")

def monitor_logs():
    # Define paths to your log files and indices to extract
    log_files = {
        "cpu_utilization": (os.path.join(OUTPUT_DIR, "cpu_utilization.csv"), [1, 2, 3, 4, 5, 6, 7]),
        "gpu_utilization": (os.path.join(OUTPUT_DIR, "gpu_usage_log.csv"), [1, 2, 3, 4, 5, 6]),
        "npu_utilization": (os.path.join(OUTPUT_DIR, "npu_utilization.csv"), [1]),
        "memory": (os.path.join(OUTPUT_DIR, "memory_metrics.csv"), [1, 2, 3]),
        "disk_bandwidth": (os.path.join(OUTPUT_DIR, "disk_bandwidth_metrics.csv"), [1, 2]),
        "power": (os.path.join(OUTPUT_DIR, "power_metrics.csv"), [1])
    }

    for key, (file_path, indices) in log_files.items():
        if os.path.exists(file_path):
            print(f"Reading log file for {key}: {file_path}")  # Debugging output
            read_log_file(file_path, key, indices)
        else:
            print(f"Log file {file_path} does not exist.")

def start_monitoring():
    global monitoring_active
    monitoring_active = True

    # Start each monitoring function in a separate thread, passing the interval and output directory
    try:
        threading.Thread(target=start_cpu_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting CPU monitoring: {e}")

    try:
        threading.Thread(target=start_npu_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting NPU monitoring: {e}")

    try:
        threading.Thread(target=start_gpu_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting GPU monitoring: {e}")

    try:
        threading.Thread(target=start_memory_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting Memory monitoring: {e}")

    try:
        threading.Thread(target=start_disk_bandwidth_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting Disk Bandwidth monitoring: {e}")

    try:
        threading.Thread(target=start_power_monitoring, args=(INTERVAL_SECONDS, OUTPUT_DIR), daemon=True).start()
    except Exception as e:
        print(f"Error starting Power monitoring: {e}")

def stop_monitoring():
    global monitoring_active
    monitoring_active = False

@app.get("/metrics")
async def get_metrics():
    # Read logs and update the latest_utilization dictionary
    monitor_logs()

    # Return the latest utilization values
    with utilization_lock:
        print("Returning metrics:", latest_utilization)  # Debugging output
        return latest_utilization