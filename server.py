from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import hmac
import hashlib

app = FastAPI(title="Composio Webhook Server - Secure Single User")

# ------------------------------
# CONFIG
# ------------------------------
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "ak_D5D8su1vCNMqIxyI71il")

# Hardcode your user's connected account (for shreya2002pandey@gmail.com)
CONNECTED_ACCOUNT_ID = "ca_LdMKDhu7AUxJ"

# The secret you get after registering your webhook in Composio
COMPOSIO_WEBHOOK_SECRET = os.getenv("COMPOSIO_WEBHOOK_SECRET")

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
# HELPERS
# ------------------------------
def verify_signature(payload_body: bytes, signature: Optional[str]) -> bool:
    """
    Verify Composio webhook signature using HMAC SHA256.
    """
    if not signature:
        return False

    expected_sig = hmac.new(
        key=COMPOSIO_WEBHOOK_SECRET.encode(),
        msg=payload_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature)

# ------------------------------
# WEBHOOK ENDPOINT
# ------------------------------
@app.post("/composio-webhook")
async def composio_webhook(request: Request, composio_signature: Optional[str] = Header(None)):
    try:
        # Read raw request body
        body = await request.body()

        # Verify webhook authenticity
        if not verify_signature(body, composio_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Parse the JSON payload
        payload = WebhookPayload.parse_raw(body)
        row = payload.row_data

        if len(row) < 4:
            raise HTTPException(status_code=400, detail="Insufficient data in row")

        # Map Google Sheets row → Salesforce contact (NO email)
        contact_data = {
            "salutation": row[1] if len(row) > 1 else "",
            "first_name": row[2] if len(row) > 2 else "",
            "last_name": row[3] if len(row) > 3 else "",
        }

        if not contact_data["last_name"]:
            raise HTTPException(status_code=400, detail="Last name is required")

        # Call Composio SALESFORCE_CREATE_CONTACT tool
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://backend.composio.dev/api/v3/tools/execute/SALESFORCE_CREATE_CONTACT",
                headers={
                    "x-api-key": COMPOSIO_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "connected_account_id": CONNECTED_ACCOUNT_ID,
                    "arguments": contact_data
                },
                timeout=60
            )

            result = response.json()
            print("SALESFORCE_CREATE_CONTACT result:", result)

            if response.status_code != 200 or not result.get("successful", True):
                raise HTTPException(status_code=400, detail=f"Salesforce error: {result}")

        return {"status": "success", "message": "Salesforce contact created"}

    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
