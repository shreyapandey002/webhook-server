from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List
import httpx
import os

app = FastAPI(title="Composio Webhook Server - Single User (No Signature Check)")

# ------------------------------
# CONFIG
# ------------------------------
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "ak_D5D8su1vCNMqIxyI71il")

# Hardcoded Salesforce connected account
CONNECTED_ACCOUNT_ID = "ca_LdMKDhu7AUxJ"

# ------------------------------
# MODELS
# ------------------------------
class WebhookPayload(BaseModel):
    detected_at: str
    row_data: List[str]
    row_number: int
    sheet_name: str
    spreadsheet_id: str

# ------------------------------
# WEBHOOK ENDPOINT
# ------------------------------
@app.post("/composio-webhook")
async def composio_webhook(request: Request):
    try:
        body = await request.json()
        payload = WebhookPayload(**body)
        row = payload.row_data

        if len(row) < 4:
            raise HTTPException(status_code=400, detail="Insufficient data in row")

        # Map Google Sheets row → Salesforce contact
        contact_data = {
            "salutation": row[1] if len(row) > 1 else "",
            "first_name": row[2] if len(row) > 2 else "",
            "last_name": row[3] if len(row) > 3 else "",
        }

        if not contact_data["last_name"]:
            raise HTTPException(status_code=400, detail="Last name is required")

        # Call Composio Salesforce tool
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://backend.composio.dev/api/v3/tools/execute/SALESFORCE_CREATE_CONTACT",
                headers={
                    "x-api-key": COMPOSIO_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "connected_account_id": CONNECTED_ACCOUNT_ID,
                    "arguments": contact_data,
                },
                timeout=60,
            )

            result = response.json()
            print("SALESFORCE_CREATE_CONTACT result:", result)

            if response.status_code != 200 or not result.get("successful", True):
                raise HTTPException(status_code=400, detail=f"Salesforce error: {result}")

        return {"status": "success", "message": "Salesforce contact created"}

    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
