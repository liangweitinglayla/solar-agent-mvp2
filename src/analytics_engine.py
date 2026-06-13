import duckdb
import pandas as pd

class AnalyticsEngine:
    def __init__(self, db_path="solar_om.duckdb"):
        self.conn = duckdb.connect(db_path)
        
    def get_plants(self):
        return [r[0] for r in self.conn.execute("SELECT DISTINCT plant_id FROM telemetry_minute ORDER BY plant_id").fetchall()]

    def get_events(self, plant_id="Plant A"):
        """Fetch all error events for the UI selector."""
        query = "SELECT event_id, inverter_id, start_time, end_time, error_code, description FROM error_events WHERE plant_id = ?"
        return self.conn.execute(query, [plant_id]).df()
        
    def get_event_details(self, event_id):
        """Get full details of a specific event, including linked tickets."""
        query = f"""
            SELECT e.*, t.ticket_id, t.status, t.issue_category as ticket_category
            FROM error_events e
            LEFT JOIN service_tickets t ON e.inverter_id = t.inverter_id
                AND t.create_time <= e.end_time
                AND (t.end_time IS NULL OR t.end_time >= e.start_time)
            WHERE e.event_id = '{event_id}'
        """
        df = self.conn.execute(query).df()
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_anomalies(self, plant_id="Plant A", days=30, threshold=0.15):
        """
        Detect inverters silently underperforming vs peers over recent `days`,
        even with no active error code. Returns inverters below peer avg by > threshold.
        """
        query = """
            WITH recent AS (
                SELECT t.inverter_id, t.timestamp, t.active_power_kw
                FROM telemetry_minute t
                JOIN solar_altitude a ON a.timestamp = t.timestamp AND a.plant_id = t.plant_id AND a.altitude >= 5
                WHERE t.plant_id = ?
                  AND t.timestamp >= (SELECT MAX(timestamp) FROM telemetry_minute WHERE plant_id = ?) - INTERVAL (?) DAY
            ),
            peer_avg AS (
                SELECT timestamp, AVG(active_power_kw) AS fleet_avg
                FROM recent WHERE active_power_kw > 0 GROUP BY timestamp
            ),
            inv_ratio AS (
                SELECT
                    r.inverter_id,
                    AVG(r.active_power_kw)            AS inv_avg,
                    AVG(p.fleet_avg)                  AS peer_avg,
                    AVG(r.active_power_kw) / NULLIF(AVG(p.fleet_avg), 0) AS ratio,
                    COUNT(*)                           AS samples
                FROM recent r
                JOIN peer_avg p ON p.timestamp = r.timestamp
                GROUP BY r.inverter_id
                HAVING COUNT(*) > 100
            )
            SELECT
                inverter_id,
                ROUND(inv_avg, 2)  AS avg_power_kw,
                ROUND(peer_avg, 2) AS peer_avg_kw,
                ROUND((1 - ratio) * 100, 1) AS underperformance_pct
            FROM inv_ratio
            WHERE ratio < (1 - ?)
            ORDER BY underperformance_pct DESC
        """
        return self.conn.execute(query, [plant_id, plant_id, days, threshold]).df()

    def get_performance_trend(self, inverter_id, plant_id="Plant A", days=90):
        """Weekly rolling performance ratio vs fleet for one inverter."""
        query = """
            WITH weekly AS (
                SELECT
                    DATE_TRUNC('week', t.timestamp) AS week,
                    t.inverter_id,
                    AVG(t.active_power_kw) AS inv_avg,
                    AVG(fleet.fleet_avg)   AS peer_avg
                FROM telemetry_minute t
                JOIN solar_altitude a ON a.timestamp = t.timestamp AND a.plant_id = t.plant_id AND a.altitude >= 5
                JOIN (
                    SELECT timestamp, AVG(active_power_kw) AS fleet_avg
                    FROM telemetry_minute WHERE plant_id = ? AND active_power_kw > 0 GROUP BY timestamp
                ) fleet ON fleet.timestamp = t.timestamp
                WHERE t.inverter_id = ? AND t.plant_id = ?
                  AND t.timestamp >= (SELECT MAX(timestamp) FROM telemetry_minute WHERE plant_id = ?) - INTERVAL (?) DAY
                GROUP BY week, t.inverter_id
            )
            SELECT week, ROUND(inv_avg / NULLIF(peer_avg, 0) * 100, 1) AS performance_ratio
            FROM weekly ORDER BY week
        """
        return self.conn.execute(query, [plant_id, inverter_id, plant_id, plant_id, days]).df()

    def get_top_loss_events(self, plant_id="Plant A", n=10):
        """Return the n events with highest estimated energy loss."""
        query = """
            WITH peer_avg AS (
                SELECT timestamp, AVG(active_power_kw) AS baseline_power
                FROM telemetry_minute WHERE plant_id = ? AND active_power_kw > 0 GROUP BY timestamp
            ),
            event_loss AS (
                SELECT
                    e.event_id,
                    e.inverter_id,
                    e.start_time,
                    e.end_time,
                    e.error_code,
                    e.description,
                    SUM(GREATEST(0, p.baseline_power - t.active_power_kw)) / 12.0 AS loss_kwh
                FROM error_events e
                JOIN telemetry_minute t
                    ON t.inverter_id = e.inverter_id AND t.plant_id = e.plant_id
                    AND t.timestamp BETWEEN e.start_time AND e.end_time
                JOIN peer_avg p ON p.timestamp = t.timestamp
                JOIN solar_altitude a ON a.timestamp = t.timestamp AND a.plant_id = t.plant_id AND a.altitude >= 0
                WHERE e.plant_id = ?
                GROUP BY e.event_id, e.inverter_id, e.start_time, e.end_time, e.error_code, e.description
            )
            SELECT * FROM event_loss ORDER BY loss_kwh DESC LIMIT ?
        """
        return self.conn.execute(query, [plant_id, plant_id, n]).df()

    def get_fault_heatmap(self, plant_id="Plant A"):
        """Return fault counts per inverter per month for heatmap."""
        query = """
            SELECT
                inverter_id,
                STRFTIME(start_time, '%Y-%m') AS month,
                COUNT(*) AS fault_count
            FROM error_events
            WHERE plant_id = ?
            GROUP BY inverter_id, month
            ORDER BY inverter_id, month
        """
        return self.conn.execute(query, [plant_id]).df()

    def get_recurring_faults(self, plant_id="Plant A", min_occurrences=5):
        """Return inverter+error_code combos that recur frequently."""
        query = """
            SELECT
                inverter_id,
                error_code,
                description,
                COUNT(*) AS occurrences,
                SUM(DATEDIFF('minute', start_time, end_time)) AS total_downtime_mins,
                MIN(start_time) AS first_seen,
                MAX(start_time) AS last_seen
            FROM error_events
            WHERE plant_id = ?
            GROUP BY inverter_id, error_code, description
            HAVING COUNT(*) >= ?
            ORDER BY occurrences DESC
            LIMIT 20
        """
        return self.conn.execute(query, [plant_id, min_occurrences]).df()

    def get_inverter_loss_summary(self, plant_id="Plant A"):
        """Total estimated energy loss per inverter across all events."""
        query = """
            WITH peer_avg AS (
                SELECT timestamp, AVG(active_power_kw) AS baseline_power
                FROM telemetry_minute WHERE plant_id = ? AND active_power_kw > 0 GROUP BY timestamp
            )
            SELECT
                e.inverter_id,
                COUNT(DISTINCT e.event_id) AS total_faults,
                SUM(GREATEST(0, p.baseline_power - t.active_power_kw)) / 12.0 AS total_loss_kwh
            FROM error_events e
            JOIN telemetry_minute t
                ON t.inverter_id = e.inverter_id AND t.plant_id = e.plant_id
                AND t.timestamp BETWEEN e.start_time AND e.end_time
            JOIN peer_avg p ON p.timestamp = t.timestamp
            JOIN solar_altitude a ON a.timestamp = t.timestamp AND a.plant_id = t.plant_id AND a.altitude >= 0
            WHERE e.plant_id = ?
            GROUP BY e.inverter_id
            ORDER BY total_loss_kwh DESC
        """
        return self.conn.execute(query, [plant_id, plant_id]).df()

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
                  AND active_power_kw > 0
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
            JOIN solar_altitude a ON a.timestamp = t.timestamp AND a.altitude >= 0
            WHERE t.timestamp BETWEEN CAST('{start_time}' AS TIMESTAMP) - INTERVAL 30 MINUTE
                                  AND CAST('{end_time}' AS TIMESTAMP) + INTERVAL 30 MINUTE
            ORDER BY t.timestamp
        """
        df = self.conn.execute(query).df()
        
        # Data is 5-min resolution: each row = 5/60 h → sum(kW) / 12 = kWh
        total_loss_kwh = df['power_loss_kw'].sum() / 12.0
        
        return total_loss_kwh, df
