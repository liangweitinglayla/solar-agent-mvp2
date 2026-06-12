import duckdb
import pandas as pd

class AnalyticsEngine:
    def __init__(self, db_path="solar_om.duckdb"):
        self.conn = duckdb.connect(db_path)
        
    def get_events(self):
        """Fetch all error events for the UI selector."""
        query = "SELECT event_id, inverter_id, start_time, error_code, description FROM error_events"
        return self.conn.execute(query).df()
        
    def get_event_details(self, event_id):
        """Get full details of a specific event, including linked tickets."""
        query = f"""
            SELECT e.*, t.ticket_id, t.status 
            FROM error_events e
            LEFT JOIN service_tickets t ON e.inverter_id = t.inverter_id 
                AND t.create_time >= e.start_time 
                AND t.create_time <= e.end_time
            WHERE e.event_id = '{event_id}'
        """
        df = self.conn.execute(query).df()
        return df.iloc[0].to_dict() if not df.empty else {}

    def calculate_impact(self, inverter_id, start_time, end_time):
        """
        Calculate energy loss by comparing target inverter against peers.
        Returns total loss in kWh and the time-series dataframe for plotting.
        """
        # We add 30 mins padding before and after for visualization context
        query = f"""
            WITH peer_avg AS (
                SELECT timestamp, AVG(active_power_kw) as baseline_power
                FROM telemetry_minute
                WHERE inverter_id != '{inverter_id}'
                GROUP BY timestamp
            ),
            target_data AS (
                SELECT timestamp, active_power_kw
                FROM telemetry_minute
                WHERE inverter_id = '{inverter_id}'
            )
            SELECT 
                t.timestamp, 
                t.active_power_kw as actual_power, 
                p.baseline_power,
                CASE 
                    WHEN t.timestamp >= '{start_time}' AND t.timestamp <= '{end_time}' 
                    THEN GREATEST(0, p.baseline_power - t.active_power_kw) 
                    ELSE 0 
                END as power_loss_kw
            FROM target_data t
            JOIN peer_avg p ON t.timestamp = p.timestamp
            WHERE t.timestamp BETWEEN CAST('{start_time}' AS TIMESTAMP) - INTERVAL 30 MINUTE 
                                  AND CAST('{end_time}' AS TIMESTAMP) + INTERVAL 30 MINUTE
            ORDER BY t.timestamp
        """
        df = self.conn.execute(query).df()
        
        # Calculate integral of power loss over time (assuming 1-min resolution -> / 60 for kWh)
        total_loss_kwh = df['power_loss_kw'].sum() / 60.0
        
        return total_loss_kwh, df
