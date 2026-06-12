import duckdb
import os
import pandas as pd

def init_duckdb(db_path="solar_om.duckdb", data_dir="data"):
    """
    Initialize DuckDB and load CSV data into tables.
    If CSV files don't exist, it creates mock data for demonstration purposes.
    """
    conn = duckdb.connect(db_path)
    
    # Check if we need to generate mock data
    if not os.path.exists(os.path.join(data_dir, "telemetry_minute.csv")):
        print("CSV files not found, generating mock data...")
        generate_mock_data(data_dir)
        
    # Load Telemetry
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS telemetry_minute AS 
        SELECT * FROM read_csv_auto('{data_dir}/telemetry_minute.csv')
    """)
    
    # Load Error Events
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS error_events AS 
        SELECT * FROM read_csv_auto('{data_dir}/error_events.csv')
    """)
    
    # Load Service Tickets
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS service_tickets AS 
        SELECT * FROM read_csv_auto('{data_dir}/service_tickets.csv')
    """)
    
    return conn

def generate_mock_data(data_dir):
    """
    Generates mock data for MVP demonstration if real data is not available.
    """
    os.makedirs(data_dir, exist_ok=True)
    
    # Mock Telemetry (Inverter A has a drop at 10:30)
    timestamps = pd.date_range("2023-01-01 10:00", "2023-01-01 12:00", freq="1min")
    data = []
    for ts in timestamps:
        # Inverter A (Target)
        power_a = 100.0
        if "10:30" <= ts.strftime("%H:%M") <= "11:30":
            power_a = 20.0 # Power drop!
        data.append({"timestamp": ts, "inverter_id": "INV-A", "active_power_kw": power_a})
        
        # Inverter B (Peer)
        data.append({"timestamp": ts, "inverter_id": "INV-B", "active_power_kw": 105.0})
        
    pd.DataFrame(data).to_csv(os.path.join(data_dir, "telemetry_minute.csv"), index=False)
    
    # Mock Error Event
    errors = [{
        "event_id": "E-001",
        "inverter_id": "INV-A",
        "start_time": "2023-01-01 10:30:00",
        "end_time": "2023-01-01 11:30:00",
        "error_code": "ERR-404",
        "description": "Cooling Fan Malfunction"
    }]
    pd.DataFrame(errors).to_csv(os.path.join(data_dir, "error_events.csv"), index=False)
    
    # Mock Service Ticket
    tickets = [{
        "ticket_id": "T-999",
        "inverter_id": "INV-A",
        "create_time": "2023-01-01 10:45:00",
        "issue_category": "Hardware",
        "status": "Open"
    }]
    pd.DataFrame(tickets).to_csv(os.path.join(data_dir, "service_tickets.csv"), index=False)

if __name__ == "__main__":
    init_duckdb()
    print("Database initialized successfully.")
