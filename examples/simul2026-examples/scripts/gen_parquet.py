import pathlib
import pandas as pd
import sys


# Process all logs, gather all results into a huge dataframe
# and save it as a parquet file

# ----------------
# These functions are taken from tne notebook "results.ipynb"


def process_logfile(logfile):
    requests = {}
    simulation_status = "running"
    containers_assignment = {}
    requests_assignment = {}
    final_cost = 0.0

    def add_request(line):
        # Line format:
        # [0]   WORKLOAD WorkloadInjector Injected request app_1_req_0_0 for app app_1.

        # Extract timestamp
        parts = line.split()
        timestamp = float(parts[0][1:-1])  # Remove brackets and convert to float
        req_id = parts[5]  # Extract request ID
        app_name = parts[-1][:-1]
        if req_id in requests:
            print("Duplicate request ID found:", req_id)
            return
        requests[req_id] = {"app": app_name, "injected": timestamp}

    def request_at_lb(line):
        # Line format:
        # [0]   INFO     nuberu.plugin_load_balancer Received request app_0_req_0_0 for app App(name='app_0')
        parts = line.split()

        timestamp = float(parts[0][1:-1])  # Extract timestamp
        req_id = parts[5]  # Extract request ID
        if req_id not in requests:
            print("Request ID not found in injected requests at LB:", req_id)
            return
        requests[req_id]["at_lb"] = timestamp

    def request_at_container(line):
        # Line format:
        # [0]   INFO     Container    Assigning request app_0_req_0_0 to container c5.12xlarge-1-app_0_c5_m5_r5_4-0
        parts = line.split()
        timestamp = float(parts[0][1:-1])  # Extract timestamp
        req_id = parts[5]
        container = parts[-1]
        if req_id not in requests:
            print("Request ID not found in injected requests at container:", req_id)
            return
        requests[req_id]["at_container"] = timestamp
        requests[req_id]["container"] = container

        # Add req_id to container queue
        if container not in containers_assignment:
            containers_assignment[container] = []
        containers_assignment[container].append(req_id)
        requests_assignment[req_id] = container

    def requests_assigned(line):
        # Line format
        # [17.116781041931535] INFO     PerformanceModelSimple Container c5.24xlarge-4-app_4_c5_m5_r5_4 processing request app_4_req_17.116781041931535_15
        parts = line.split()
        container = parts[4]
        req_id = parts[-1].strip()
        if req_id not in requests:
            print("Request ID not found in injected requests for assignment:", req_id)
            return
        if container in containers_assignment:
            print("Container already assigned to a request:", container)
            return
        containers_assignment[container] = req_id
        requests_assignment[req_id] = container

    def request_start_service(line):
        # Line format:
        # [0]   INFO     Request      Request app_0_req_0_0 duration set to 156.0000 seconds.
        parts = line.split()
        timestamp = float(parts[0][1:-1])
        req_id = parts[4]
        if req_id not in requests:
            print("Request ID not found in injected requests at service start:", req_id)
            return
        container = requests_assignment.get(req_id, None)
        if container is None:
            print("Container assignment not found for request:", req_id)
            return
        # Get oldest request in container queue
        if container not in containers_assignment:
            print("Container not found in containers assignment for request:", req_id)
            return
        oldest_request = containers_assignment[container][0]
        if oldest_request != req_id:
            print(
                "Oldest request does not match current request for container:",
                container,
            )
            return
        service_time = float(parts[-2])
        requests[req_id]["start_service"] = timestamp
        requests[req_id]["service_time"] = service_time

    def rejected_request(line):
        # line format
        # [22.46040725102658] WARNING  Container    Container c5.12xlarge-6-app_1_c5_m5_r5_1-0 rejected request app_1_req_22.46040725102658_23 due to load/capacity.
        parts = line.split()
        timestamp = float(parts[0][1:-1])
        req_id = parts[7]
        container = parts[4]
        if req_id not in requests:
            print(
                "Request ID not found in injected requests for rejected request:",
                req_id,
            )
            return
        requests[req_id]["end"] = timestamp
        requests[req_id]["status"] = "rejected"
        requests[req_id]["container"] = container
        if req_id in requests_assignment:
            del requests_assignment[req_id]
        if container in containers_assignment:
            if req_id in containers_assignment[container]:
                containers_assignment[container].remove(req_id)
            if not containers_assignment[
                container
            ]:  # If no requests left, remove container
                del containers_assignment[container]
        else:
            print(
                "Container not found in containers assignment for rejected request:",
                container,
            )

    def completed_request(line):
        # line format
        # [150.65081379062966] INFO     PerformanceModelSimple [Container c5.18xlarge-2-app_4_c5_m5_r5_1-20] released: 1 CPU and 1 memory. Available: 0.13799999999999998
        nonlocal simulation_status
        if "SUCCESS  Container" in line:
            return
        parts = line.split()
        timestamp = float(parts[0][1:-1])
        container = parts[4][:-1]
        pending_requests = containers_assignment.get(container, [None])
        req_id = pending_requests.pop(0)
        if req_id is None:
            print(
                "Request ID not found for completed request in containers assignment:",
                container,
            )
            print("**", line)
            return
        if req_id not in requests:
            print(
                "Request ID not found in injected requests for completed request:",
                req_id,
            )
            return
        if container != requests_assignment.get(req_id, None):
            print(
                "Container assignment does not match for completed request:",
                req_id,
                container,
            )
            return
        requests[req_id]["end"] = timestamp
        if simulation_status == "running":
            requests[req_id]["status"] = "completed"
        elif simulation_status == "draining":
            requests[req_id]["status"] = "drained"
        elif simulation_status == "stopped":
            requests[req_id]["status"] = "dropped"
        else:
            print("Unknown simulation status:", simulation_status)
            quit()
        del requests_assignment[req_id]

    def set_status_draining(line):
        nonlocal simulation_status
        simulation_status = "draining"

    def set_status_stopped(line):
        nonlocal simulation_status
        simulation_status = "stopped"

    def drop_pending_requests():
        for req_id in requests_assignment:
            container = requests_assignment[req_id]
            if req_id not in requests:
                print("Request ID not found in injected requests for dropping:", req_id)
                continue
            if container != requests[req_id].get("container", None):
                print(
                    "Container assignment does not match for dropping request:",
                    req_id,
                    container,
                )
                continue
            if container not in containers_assignment:
                print(
                    "Container not found in containers assignment for dropping request:",
                    req_id,
                    container,
                )
                continue
            if req_id not in containers_assignment[container]:
                print(
                    "Request ID not found in containers assignment for dropping request:",
                    req_id,
                    container,
                )
                continue
            requests[req_id]["status"] = "dropped"
            containers_assignment[container].remove(req_id)
            requests_assignment[req_id] = None
        # Rmove all requests with None assignment
        for req_id in list(requests_assignment.keys()):
            if requests_assignment[req_id] is None:
                del requests_assignment[req_id]
        # Remove empty containers
        for container in list(containers_assignment.keys()):
            if not containers_assignment[container]:
                del containers_assignment[container]

    def set_total_cost(line):
        # Line format:
        # [5608.42819554089] INFO     nuberu.components.monitor Total cost: $16.55
        nonlocal final_cost
        parts = line.split()
        cost_str = parts[-1]
        if cost_str.startswith("$"):
            cost_str = cost_str[1:]
        final_cost = float(cost_str)

    keyword_processing = {
        "WorkloadInjector Injected request": add_request,
        "Received request": request_at_lb,
        "Assigning request": request_at_container,
        "duration set to": request_start_service,
        # "processing request": requests_assigned,
        "rejected request": rejected_request,
        "released": completed_request,
        "Waiting for in-flight": set_status_draining,
        "Hard stop": set_status_stopped,
        "Total cost": set_total_cost,
    }

    for line in open(logfile):
        line = line.strip()
        if not line:
            continue
        for keyword, func in keyword_processing.items():
            if keyword in line:
                func(line)
                break
    if requests_assignment:
        print(
            f"Warning: There are still {len(requests_assignment)} requests assigned to containers at the end of the log file. Marking all as dropped."
        )
        drop_pending_requests()
    if requests_assignment:
        print(
            f"ERROR: There are still {len(requests_assignment)} requests assigned to containers after dropping."
        )
        drop_pending_requests()

    return requests, final_cost, containers_assignment, requests_assignment


def find_all_logs(logs_root):
    log_dir = pathlib.Path(logs_root).resolve()
    if not log_dir.exists():
        print("Log directory does not exist:", log_dir)
        quit()

    logfiles = []
    for path in log_dir.rglob("*.log"):
        if path.is_file():
            logfiles.append(path.absolute())
    if not logfiles:
        print("No log files found in directory:", log_dir)
        quit()
    logfiles.sort()
    return logfiles


def create_requests_df(requests, cost, remove_request_id=True):
    df = pd.DataFrame.from_dict(requests, orient="index")
    df.reset_index(inplace=True)
    df.rename(columns={"index": "request_id"}, inplace=True)
    if remove_request_id:
        df.drop(columns=["request_id"], inplace=True)

    # Añadir columna con tiempo de respuesta
    df["response_time"] = df["end"] - df["injected"]

    # Añadir columna que indica si terminó con éxito
    df["finished"] = df["status"].isin(["completed", "drained"])

    # Extraer el nombre de la instance-class y del container-class
    # primero, quitar el \d+ al final, si existe
    df["ic-cc"] = df["container"].str.replace(r"-\d+$", "", regex=True)
    # Ahora quitar el -\d+ que hay por el medio
    df["ic-cc"] = df["ic-cc"].str.replace(r"-\d+-", "-", regex=True)

    # Añadir columna con tiempo de espera en cola
    df["queue_time"] = df["start_service"] - df["at_container"]
    # Ordenar por tiempo de inyección
    df.sort_values(by="injected", inplace=True)
    df["cost"] = cost
    return df


def filter_requests_df(df, app=None, status=None):
    if app is not None:
        df = df[df["app"] == app]
    if status is not None:
        df = df[df["status"] == status]
    return df


def extract_parameters_from_filename(filename):
    """
    Extract parameters from filename following pattern:
    log_<distribution>_<termination>_<LB>_q<queue_size>.log
    """
    # Remove .log extension and log_ prefix
    base_name = filename.replace(".log", "").replace("log_", "")

    # Split by underscore
    parts = base_name.split("_")

    if len(parts) != 4:
        raise ValueError(f"Unexpected filename format: {filename}")

    distribution = parts[0]
    termination = parts[1]
    lb = parts[2]
    queue_size = int(parts[3][1:])  # Remove 'q' prefix and convert to int

    return {
        "experiment": base_name,
        "distribution": distribution,
        "termination": termination,
        "LB": lb,
        "queue_size": queue_size,
    }


def combine_all_logs(logs_root):
    logfiles = find_all_logs(logs_root)
    if not logfiles:
        print("No log files found to process.")
        return pd.DataFrame()
    combined_data = []
    for log in logfiles:
        print(f"Procesando {log.name}")
        requests, cost, c_map, r_map = process_logfile(log)
        df = create_requests_df(requests, cost)
        params = extract_parameters_from_filename(log.name)
        # Añadir columnas de parámetros al dataframe
        for param_name, param_value in params.items():
            df[param_name] = param_value
        combined_data.append(df)

    all_df = pd.concat(combined_data, ignore_index=True)
    return all_df


def save_combined_results(all_df, output_file):
    if all_df.empty:
        print("No data to save.")
        return
    all_df.to_parquet(output_file, index=False)
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python gen_parquet.py <logs_root>")
        sys.exit(1)

    logs_root = sys.argv[1]
    all_df = combine_all_logs(logs_root)
    output_file = pathlib.Path(logs_root) / "combined_results.parquet"
    save_combined_results(all_df, output_file)
