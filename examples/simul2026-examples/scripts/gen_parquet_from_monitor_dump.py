import pathlib
import pandas as pd
import sys
import json
import re
import os
import multiprocessing
from typing import Dict, Any


# Default stop_time for TTD calculation (can be overridden via config)
DEFAULT_STOP_TIME = 3600  # seconds


def process_metrics(file_path, fixed_cost=None, legacy_mode=False):
    def parse_filename_metadata(file_path):
        filename = os.path.basename(file_path).replace(".jsonl", "")
        # Regex for: distribution_termination_lb_qSize
        match = re.match(r"([^_]+)_([^_]+)_([^_]+)_q(\d+)_l(\d+)", filename)

        if match:
            return {
                "experiment": filename,
                "distribution": match.group(1),
                "termination": match.group(2),
                "LB": match.group(3),
                "queue_size": int(match.group(4)),
                "latency": int(match.group(5)),
            }
        return {"experiment": filename}

    def extract_ic_cc(container_id):
        if not container_id:
            return None
        # Pattern: Container_<ic>-<vm_num>-<cc>-<cc_num>
        # Example: Container_c6i.2xlarge-15-cc1app0-2 -> ic: c6i.2xlarge, cc: cc1app0
        match = re.search(r"(.+?)-(.+?)-([^-]+).*", container_id)
        if match:
            return f"{match.group(1)}-{match.group(3)}"
        return None

    def process_timeline(timeline):
        timeline_dict = {}
        for event in timeline:
            component = event.get("component_id", "")
            event_name = event.get("event", "")
            source = event.get("source_id", "")
            metadata = {}
            if component == "Client_send_to_lb":
                tag = "request_sent_to_lb"
            elif event_name == "receive_from_wi":
                tag = "request_at_lb"
            elif event_name == "receive_from_lb" and source.startswith("LoadBalancer"):
                tag = "request_at_container"
                metadata = {"container": component.replace("Container_", "")}
            elif event_name == "accepted_and_sent_to_runtime":
                tag = "request_at_queue"
                metadata = {"container": component.replace("Container_", "")}
            elif event_name == "receive_from_container" and component.startswith(
                "Runtime"
            ):
                tag = "request_at_runtime"
                metadata = {"container": source.replace("Container_", "")}
            elif event_name == "processing_completed":
                tag = "response_computed"
            elif event_name == "send_to_container" and component.startswith("Runtime"):
                tag = "response_sent_to_lb"
            elif event_name == "receive_from_container" and component.startswith(
                "LoadBalancer"
            ):
                tag = "response_at_lb"
            elif component == "Client_receive_response":
                tag = "response_at_client"
            else:
                continue
            time = event.get("time")
            metadata |= event.get("metadata", {})
            timeline_dict[tag] = (time, metadata)
        return timeline_dict

    file_metadata = parse_filename_metadata(file_path)
    processed_rows = []
    total_cost = 0.0

    with open(file_path, "r", encoding="utf-8") as file:
        for line_n, line in enumerate(file):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON on line {line_n + 1} of {file_path}: {e}")
                continue
            if "total_cost" in data:
                total_cost = data["total_cost"]
                continue  # Skip cost summary lines

            timeline = data.get("timeline", [])
            timeline_dict = process_timeline(timeline)

            # Identify the container and status when the reponse was computed
            container_entry = timeline_dict.get("request_at_container", (None, {}))
            container_id = (
                container_entry[1].get("container") if container_entry[1] else None
            )
            timeline_dict.get("response_computed", (None, {}))[1].get("container_state")

            # Building the row
            row = {
                "app": data.get("app_id"),
                "status": data.get("status"),
                "response_time": data.get("response_time"),
                "finished": data.get("status") in ["completed", "drained"],
                "cost": fixed_cost,
                **file_metadata,
            }

            # Mapping timestamps
            row["injected"] = timeline_dict.get("request_sent_to_lb", (None, {}))[0]
            row["at_lb"] = timeline_dict.get("request_at_lb", (None, {}))[0]
            row["at_container"] = (
                float("nan") if row["status"] == "rejected" else container_entry[0]
            )
            row["container"] = container_id
            row["start_service"] = timeline_dict.get("request_at_runtime", (None, {}))[
                0
            ]
            row["end"] = timeline_dict.get("response_computed", (None, {}))[0]
            row["service_time"] = timeline_dict.get("request_at_runtime", (None, {}))[
                1
            ].get("duration", None)
            row["e2e_time"] = (
                timeline_dict.get("response_at_client", (float("nan"), {}))[0]
                - row["injected"]
            )

            # Logic-based fields
            row["ic-cc"] = extract_ic_cc(container_id)
            if row["start_service"] is not None and row["at_container"] is not None:
                row["queue_time"] = row["start_service"] - row["at_container"]
            else:
                row["queue_time"] = None

            if legacy_mode:
                if row["status"] == "completed" and row["end"] > 30:
                    row["status"] = "drained"
                if row["status"] == "rejected":
                    row["end"] = row["at_lb"]
                    row["response_time"] = 0.0

            if row["status"] in ["completed", "drained"]:
                row["response_time"] = row["end"] - row["injected"]
            processed_rows.append(row)
    order = [
        "app",
        "injected",
        "at_lb",
        "at_container",
        "container",
        "start_service",
        "service_time",
        "end",
        "status",
        "response_time",
        "finished",
        "ic-cc",
        "queue_time",
        "cost",
        "experiment",
        "distribution",
        "termination",
        "LB",
        "queue_size",
        "latency",
        "e2e_time",
    ]
    if legacy_mode:
        total_cost = round(total_cost, 2)

    df = pd.DataFrame(processed_rows)
    # Only select columns that exist in the DataFrame
    available_order = [col for col in order if col in df.columns]
    df = df[available_order]

    # Calculate Time-To-Drain (TTD) metrics
    ttd_metrics = calculate_ttd(df, stop_time=DEFAULT_STOP_TIME)

    return df, total_cost, ttd_metrics


def calculate_ttd(
    df: pd.DataFrame, stop_time: float = DEFAULT_STOP_TIME
) -> Dict[str, Any]:
    """
    Calculate Time-To-Drain (TTD) metrics from a processed DataFrame.

    TTD is defined as the time from the configured stop_time until the last
    request finishes processing. This measures how long the system takes to
    drain all pending requests after new arrivals stop.

    Args:
        df: DataFrame with processed request data (must have 'end' and 'status' columns)
        stop_time: The configured simulation stop time

    Returns:
        Dictionary with TTD metrics at multiple levels:
        - Global metrics (stop_time, max_finish_time, ttd, counts)
        - ttd_by_app: List of per-app TTD metrics
        - ttd_by_container: List of per-container TTD metrics
    """
    # Check required columns exist
    if df.empty or "status" not in df.columns or "end" not in df.columns:
        return {
            "stop_time": stop_time,
            "max_finish_time": None,
            "ttd": None,
            "completed_count": 0,
            "drained_count": 0,
            "rejected_count": 0,
            "ttd_by_app": [],
            "ttd_by_container": [],
        }

    completed_df = df[df["status"].isin(["completed", "drained"])]
    rejected_count = len(df[df["status"] == "rejected"])

    if completed_df.empty:
        return {
            "stop_time": stop_time,
            "max_finish_time": None,
            "ttd": None,
            "completed_count": 0,
            "drained_count": 0,
            "rejected_count": rejected_count,
            "ttd_by_app": [],
            "ttd_by_container": [],
        }

    max_finish_time = completed_df["end"].max()
    drained_df = completed_df[completed_df["end"] > stop_time]

    # Calculate TTD by app
    ttd_by_app = []
    if "app" in completed_df.columns:
        for app_name, app_df in completed_df.groupby("app"):
            app_max = app_df["end"].max()
            app_drained = app_df[app_df["end"] > stop_time]
            ttd_by_app.append(
                {
                    "app": app_name,
                    "max_finish_time": app_max,
                    "ttd": max(0, app_max - stop_time) if pd.notna(app_max) else None,
                    "completed_count": len(app_df),
                    "drained_count": len(app_drained),
                }
            )

    # Calculate TTD by container
    ttd_by_container = []
    if "container" in completed_df.columns:
        for container_name, container_df in completed_df.groupby("container"):
            if pd.isna(container_name):
                continue
            cont_max = container_df["end"].max()
            cont_drained = container_df[container_df["end"] > stop_time]
            ttd_by_container.append(
                {
                    "container": container_name,
                    "max_finish_time": cont_max,
                    "ttd": max(0, cont_max - stop_time) if pd.notna(cont_max) else None,
                    "completed_count": len(container_df),
                    "drained_count": len(cont_drained),
                }
            )

    return {
        "stop_time": stop_time,
        "max_finish_time": max_finish_time,
        "ttd": max(0, max_finish_time - stop_time)
        if pd.notna(max_finish_time)
        else None,
        "completed_count": len(completed_df),
        "drained_count": len(drained_df),
        "rejected_count": rejected_count,
        "ttd_by_app": ttd_by_app,
        "ttd_by_container": ttd_by_container,
    }


def find_all_jsonl(jsonl_root):
    jsonl_dir = pathlib.Path(jsonl_root).resolve()
    if not jsonl_dir.exists():
        print("JSONL directory does not exist:", jsonl_dir)
        quit()

    jsonl_files = []
    for path in jsonl_dir.rglob("*.jsonl"):
        if path.is_file():
            jsonl_files.append(path.absolute())
    if not jsonl_files:
        print("No JSONL files found in directory:", jsonl_dir)
        quit()
    jsonl_files.sort()
    return jsonl_files


def create_requests_df(requests, cost, remove_request_id=True):
    df = requests.copy()
    df.reset_index(inplace=True)
    df.rename(columns={"index": "request_id"}, inplace=True)
    if remove_request_id:
        df.drop(columns=["request_id"], inplace=True, errors="ignore")
    if "injected" in df.columns:
        df.sort_values(by="injected", inplace=True)
    df["cost"] = cost
    return df


def filter_requests_df(df, app=None, status=None):
    if app is not None:
        df = df[df["app"] == app]
    if status is not None:
        df = df[df["status"] == status]
    return df


def process_single_log_file(args):
    jsonl_path, legacy_mode = args
    print(f"Procesando {jsonl_path.name}")
    requests, cost, ttd_metrics = process_metrics(jsonl_path, legacy_mode=legacy_mode)
    df = create_requests_df(requests, cost)

    # Save to temporary parquet to avoid pickling overhead
    temp_parquet_path = jsonl_path.with_suffix(".temp.parquet")
    df.to_parquet(temp_parquet_path, index=False)

    # Add experiment metadata to TTD metrics (safely extract from DataFrame)
    def safe_get(df, col):
        try:
            if col in df.columns and not df.empty:
                return df[col].iloc[0]
        except (IndexError, KeyError):
            pass
        return None

    experiment = safe_get(requests, "experiment") or jsonl_path.stem
    distribution = safe_get(requests, "distribution")
    termination = safe_get(requests, "termination")
    lb = safe_get(requests, "LB")
    queue_size = safe_get(requests, "queue_size")

    # Global TTD (without nested structures)
    ttd_global = {
        k: v
        for k, v in ttd_metrics.items()
        if k not in ["ttd_by_app", "ttd_by_container"]
    }
    ttd_global["experiment"] = experiment
    ttd_global["distribution"] = distribution
    ttd_global["termination"] = termination
    ttd_global["LB"] = lb
    ttd_global["queue_size"] = queue_size
    ttd_global["cost"] = cost

    # TTD by app
    ttd_by_app_list = []
    for app_ttd in ttd_metrics.get("ttd_by_app", []):
        app_ttd["experiment"] = experiment
        app_ttd["distribution"] = distribution
        app_ttd["termination"] = termination
        app_ttd["LB"] = lb
        app_ttd["queue_size"] = queue_size
        ttd_by_app_list.append(app_ttd)

    # TTD by container
    ttd_by_container_list = []
    for cont_ttd in ttd_metrics.get("ttd_by_container", []):
        cont_ttd["experiment"] = experiment
        cont_ttd["distribution"] = distribution
        cont_ttd["termination"] = termination
        cont_ttd["LB"] = lb
        cont_ttd["queue_size"] = queue_size
        ttd_by_container_list.append(cont_ttd)

    return temp_parquet_path, ttd_global, ttd_by_app_list, ttd_by_container_list


def combine_all_logs(logs_root, legacy_mode=False):
    jsonl_files = find_all_jsonl(logs_root)
    if not jsonl_files:
        print("No JSONL files found to process.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    combined_data = []
    ttd_data = []
    ttd_by_app_data = []
    ttd_by_container_data = []

    # Use multiprocessing to process files in parallel
    cpu_count = os.cpu_count() or 1
    max_workers = min(cpu_count, 16)
    print(f"Starting parallel processing with {max_workers} processes...")

    with multiprocessing.Pool(processes=max_workers) as pool:
        # Prepare arguments for map
        map_args = [(f, legacy_mode) for f in jsonl_files]
        results = pool.map(process_single_log_file, map_args)

    print("Parallel processing finished. Aggregating results...")

    temp_files = []
    for parquet_path, ttd_global, ttd_by_app_list, ttd_by_container_list in results:
        combined_data.append(pd.read_parquet(parquet_path))
        temp_files.append(parquet_path)

        ttd_data.append(ttd_global)
        ttd_by_app_data.extend(ttd_by_app_list)
        ttd_by_container_data.extend(ttd_by_container_list)

    # Clean up temp files
    for p in temp_files:
        try:
            p.unlink()
        except OSError:
            pass

    if combined_data:
        all_df = pd.concat(combined_data, ignore_index=True)
    else:
        all_df = pd.DataFrame()

    ttd_df = pd.DataFrame(ttd_data)
    ttd_by_app_df = pd.DataFrame(ttd_by_app_data)
    ttd_by_container_df = pd.DataFrame(ttd_by_container_data)

    return all_df, ttd_df, ttd_by_app_df, ttd_by_container_df


def save_combined_results(all_df, output_file):
    if all_df.empty:
        print("No data to save.")
        return
    all_df.to_parquet(output_file, index=False)
    print(f"Results saved to {output_file}")


def save_ttd_results(ttd_df, output_file, title="TTD SUMMARY"):
    """Save TTD summary to a separate parquet file."""
    if ttd_df.empty:
        print(f"No {title} data to save.")
        return
    ttd_df.to_parquet(output_file, index=False)
    print(f"{title} saved to {output_file}")


def print_ttd_summary(ttd_df, ttd_by_app_df, ttd_by_container_df):
    """Print TTD summary tables to console."""
    print("\n" + "=" * 80)
    print(" TIME-TO-DRAIN (TTD) SUMMARY - GLOBAL")
    print("=" * 80)

    if not ttd_df.empty:
        summary_cols = [
            "experiment",
            "termination",
            "LB",
            "queue_size",
            "ttd",
            "drained_count",
            "rejected_count",
            "cost",
        ]
        available_cols = [c for c in summary_cols if c in ttd_df.columns]
        print(ttd_df[available_cols].to_string(index=False))
    else:
        print("No global TTD data.")

    print("\n" + "=" * 80)
    print(" TIME-TO-DRAIN (TTD) BY APP")
    print("=" * 80)

    if not ttd_by_app_df.empty:
        app_cols = [
            "experiment",
            "termination",
            "LB",
            "queue_size",
            "app",
            "ttd",
            "drained_count",
            "completed_count",
        ]
        available_cols = [c for c in app_cols if c in ttd_by_app_df.columns]
        print(ttd_by_app_df[available_cols].to_string(index=False))
    else:
        print("No per-app TTD data.")

    print("\n" + "=" * 80)
    print(" TIME-TO-DRAIN (TTD) BY CONTAINER (top 10 by TTD)")
    print("=" * 80)

    if not ttd_by_container_df.empty:
        cont_cols = [
            "experiment",
            "container",
            "ttd",
            "drained_count",
            "completed_count",
        ]
        available_cols = [c for c in cont_cols if c in ttd_by_container_df.columns]
        # Show top 10 containers by TTD
        top_containers = (
            ttd_by_container_df.nlargest(10, "ttd")
            if "ttd" in ttd_by_container_df.columns
            else ttd_by_container_df.head(10)
        )
        print(top_containers[available_cols].to_string(index=False))
        print(f"\n(Showing top 10 of {len(ttd_by_container_df)} containers)")
    else:
        print("No per-container TTD data.")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python gen_parquet_from_monitor_dump.py <logs_root>")
        sys.exit(1)

    logs_root = sys.argv[1]
    all_df, ttd_df, ttd_by_app_df, ttd_by_container_df = combine_all_logs(
        logs_root, legacy_mode=False
    )

    output_dir = pathlib.Path(logs_root)

    # Save request-level data
    save_combined_results(all_df, output_dir / "combined_results.parquet")

    # Save TTD summaries
    save_ttd_results(ttd_df, output_dir / "ttd_summary.parquet", "TTD Global Summary")
    save_ttd_results(ttd_by_app_df, output_dir / "ttd_by_app.parquet", "TTD by App")
    save_ttd_results(
        ttd_by_container_df, output_dir / "ttd_by_container.parquet", "TTD by Container"
    )

    # Print summary to console
    print_ttd_summary(ttd_df, ttd_by_app_df, ttd_by_container_df)
