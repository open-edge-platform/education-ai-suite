import threading
import os
import time
from utils.config_loader import config 
from monitoring.scripts.collect_cpu import start_cpu_monitoring
from monitoring.scripts.collect_npu import start_npu_monitoring
from monitoring.scripts.collect_gpu import start_gpu_monitoring
from monitoring.scripts.collect_memory import start_memory_monitoring
from monitoring.scripts.collect_disk_bandwidth import start_disk_bandwidth_monitoring
from monitoring.scripts.collect_power import start_power_monitoring
import logging

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = config.monitoring.interval
OUTPUT_DIR = config.monitoring.logs_dir
monitoring_threads=[]


def read_log_file(file_path, indices):
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
            data = []
            for line in lines[1:]:  # Skip header
                values = line.strip().split(",")
                timestamp = values[0]
                data_points = [float(values[i]) for i in indices]
                data.append([timestamp] + data_points)
            # logger.info(f"Successfully read data from {file_path}")
            return data
    except Exception as e:
        logger.error(f"Error reading log file {file_path}: {e}")
        return []

def monitor_logs():
    latest_utilization = {
        "cpu_utilization": [],
        "gpu_utilization": [],
        "npu_utilization": [],
        "memory": [],
        "disk_bandwidth": [],
        "power": []
    }

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
            # logger.info(f"Reading log file for {key}: {file_path}")
            latest_utilization[key] = read_log_file(file_path, indices)
        else:
            logger.warning(f"Log file {file_path} does not exist.")
    return latest_utilization

def start_monitoring():
    global stop_event
    stop_event = threading.Event()
    logger.info("Starting monitoring processes")
    monitoring_threads=[
        threading.Thread(name="cpu_worker",target=start_cpu_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True),
        threading.Thread(name="npu_worker",target=start_npu_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True),
        threading.Thread(name="gpu_worker",target=start_gpu_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True),
        threading.Thread(name="memory_worker",target=start_memory_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True),
        threading.Thread(name="disk_worker",target=start_disk_bandwidth_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True),
        threading.Thread(name="power_worker",target=start_power_monitoring, args=(INTERVAL_SECONDS,stop_event,OUTPUT_DIR), daemon=True)
    ]
    for mt in monitoring_threads:
        try:
            mt.start()
            logger.info(f'{mt.name} started')
        except Exception as e:
            logger.error(f"Error starting {mt.name}:{e}")

def stop_monitoring():
    stop_event.set()
    for mt in monitoring_threads:
        mt.join()
    logger.info("Stopped monitoring processes")

def get_metrics():
    latest_utilization = monitor_logs()
    logger.info("Returning latest utilization metrics")
    return latest_utilization