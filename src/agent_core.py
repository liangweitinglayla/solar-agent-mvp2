import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class OMAgent:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(
                api_key=os.environ.get("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
        return self._client

    def generate_insights(self, event_details, loss_kwh):
        """
        Takes raw data context and uses LLM to generate a structured O&M report.
        """
        prompt = f"""
        You are an expert Solar Plant O&M Copilot. Analyze the following incident data and provide actionable advice.

        Incident Context:
        - Inverter ID: {event_details.get('inverter_id')}
        - Error Code: {event_details.get('error_code')}
        - Description: {event_details.get('description')}
        - Linked Ticket: {event_details.get('ticket_id', 'None')}
        - Duration: {event_details.get('start_time')} to {event_details.get('end_time')}
        - Estimated Energy Loss: {loss_kwh:.2f} kWh

        Provide your response in strictly JSON format matching this schema:
        {{
            "incident_summary": "One sentence summary of what happened and the impact.",
            "likely_cause": "Based on the error description, what physically went wrong.",
            "suggested_action": "What the O&M team should do next (e.g., dispatch technician, remote reset).",
            "confidence": "High/Medium/Low"
        }}
        """

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            # Fallback if API fails (e.g. no key during local testing)
            return {
                "incident_summary": f"Fallback: Inverter {event_details.get('inverter_id')} lost {loss_kwh:.2f} kWh.",
                "likely_cause": f"Fallback: Likely related to {event_details.get('description')}.",
                "suggested_action": "Fallback: Please check API key. Inspect inverter manually.",
                "confidence": "Low"
            }
