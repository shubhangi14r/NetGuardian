import requests
import csv
import time
import os

MONITOR_URL = "http://127.0.0.1:9000/metrics"
OUTPUT_FILE = "network_metrics.csv"


FIELDS = [
    "service",
    "latency",
    "response_time",
    "failure_rate",
    "status",
    "failure_rate_pct",
    "timestamp",
    "p95_latency_ms",
    "p95_response_time_ms",
    "consecutive_failures",
    "sample_count",
    "last_error"
]

def main():

    file_exists = os.path.exists(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="") as file:

        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if not file_exists:
            writer.writeheader()

        while True:

            try:
                response = requests.get(MONITOR_URL, timeout=5)
                response.raise_for_status()

                all_metrics = response.json()

                for metrics in all_metrics:
                    row = {
                        field: metrics.get(field)
                        for field in FIELDS
                    }

                    writer.writerow(row)

                file.flush()

                print("Metrics saved")

            except requests.RequestException as error:
                print("Could not collect metrics:", error)

            time.sleep(2)

if __name__ == "__main__":
    main()