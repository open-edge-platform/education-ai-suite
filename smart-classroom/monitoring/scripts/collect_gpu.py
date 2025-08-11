import csv
import time
from datetime import datetime
import pythoncom  # type: ignore
import win32com.client  # type: ignore
import os
import logging
logger = logging.getLogger(__name__)

# WMI categories to extract
TARGET_ENGINES = {
    '3D': 'engtype_3D',
    'VideoDecode': 'engtype_VideoDecode',
    'VideoProcessing': 'engtype_VideoProcessing',
    'VideoEncode': 'engtype_VideoEncode'
}

def get_gpu_metrics(wmi_service):
    gpu_util = {key: 0.0 for key in TARGET_ENGINES}
    total_util = 0.0
    memory_usage = 0
    try:
        engine_data = wmi_service.ExecQuery("SELECT * FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine")
        for item in engine_data:
            name = item.Name
            utilization = float(item.UtilizationPercentage)
            for label, engtype in TARGET_ENGINES.items():
                if engtype in name:
                    gpu_util[label] += utilization
            total_util += utilization

        mem_data = wmi_service.ExecQuery("SELECT * FROM Win32_PerfFormattedData_PerfProc_Process WHERE Name='dwm'")
        for mem in mem_data:
            try:
                memory_usage = int(mem.WorkingSetPrivate / (1024 * 1024))  # in MB
                memory_usage = f"{memory_usage:.2f} MB"
                break
            except:
                pass

    except Exception as e:
        logger.error("Error collecting GPU data:", e)
    return total_util, gpu_util, memory_usage

def start_gpu_monitoring(interval_seconds, stop_event, output_dir=None):
    if output_dir is None:
        output_dir = os.getcwd()
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    gpu_file = os.path.join(output_dir, "gpu_usage_log.csv")
    # logger.info(f"Starting GPU monitoring to {gpu_file}...")
    pythoncom.CoInitialize()
    wmi_service = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", "root\\CIMV2")
    with open(gpu_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        header = ['Timestamp', 'TotalGPUUtil', '3D', 'VideoDecode', 'VideoProcessing', 'VideoEncode', 'GPUMemory(MB)']
        writer.writerow(header)
    # logger.info("GPU monitoring started...")

    try:
        while not stop_event.is_set():
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            total_util, gpu_engines, memory = get_gpu_metrics(wmi_service)
            row = [timestamp, total_util]
            for key in TARGET_ENGINES:
                row.append(gpu_engines[key])
            row.append(memory)
            with open(gpu_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(row)
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        logger.info("\nGPU monitoring stopped by user.")
    finally:
        pythoncom.CoUninitialize()