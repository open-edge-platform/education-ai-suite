import wmi
import time
import os
import csv
from datetime import datetime
import pythoncom  # Add this import

def start_cpu_monitoring(interval_seconds=1, output_dir=None):
    pythoncom.CoInitialize()  # Initialize COM for the thread

    if output_dir is None:
        output_dir = os.getcwd()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    cpu_file = os.path.join(output_dir, "cpu_utilization.csv")
    print(f"Starting CPU monitoring to {cpu_file}...")

    # Create header for the CSV file
    with open(cpu_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'total_cpu_utilization', '%user', '%nice', '%system', '%iowait', '%steal', '%idle'])

    try:
        # Initialize WMI
        c = wmi.WMI()

        while True:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            try:
                # Get CPU metrics using WMI
                cpu_stats = c.Win32_PerfFormattedData_PerfOS_Processor(Name='_Total')

                if cpu_stats:
                    # Convert WMI properties to float
                    percent_idle = float(cpu_stats[0].PercentIdleTime)
                    percent_user = float(cpu_stats[0].PercentUserTime)
                    percent_system = float(cpu_stats[0].PercentPrivilegedTime)

                    # Calculate total CPU utilization
                    total_cpu_utilization = 100.0 - percent_idle

                    # Approximate other metrics
                    percent_iowait = 0.0  # Not directly available
                    percent_nice = 0.0    # Not directly available
                    percent_steal = 0.0   # Not directly available

                    # Log the timestamp and CPU metrics
                    with open(cpu_file, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([timestamp, total_cpu_utilization, percent_user, percent_nice, percent_system, percent_iowait, percent_steal, percent_idle])
                else:
                    print("Warning: Failed to get CPU metrics via WMI")
                    with open(cpu_file, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([timestamp, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            except Exception as e:
                print(f"Error: Intel CPU monitoring error: {e}")
                with open(cpu_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nCPU monitoring stopped by user.")
    except Exception as e:
        print(f"Error: CPU monitoring error: {e}")
    finally:
        print("CPU monitoring finished.")
        pythoncom.CoUninitialize()  # Uninitialize COM