from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import asyncpg
import httpx
import os

app = FastAPI(title="Composio FastAPI Server")

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY")

# ---------- Neon DB helper ----------
async def save_connected_account(email_id: str, connected_account_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        query = """
            INSERT INTO connected_accounts(email_id, connected_account_id, created_at)
            VALUES($1, $2, NOW())
            ON CONFLICT (email_id) DO UPDATE SET connected_account_id = EXCLUDED.connected_account_id
        """
        await conn.execute(query, email_id, connected_account_id)
    finally:
        await conn.close()

async def get_connected_account_id(email_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        query = "SELECT connected_account_id FROM connected_accounts WHERE email_id = $1"
        row = await conn.fetchrow(query, email_id)
        return row["connected_account_id"] if row else None
    finally:
        await conn.close()

# ---------- Pydantic models ----------
class ConnectedAccount(BaseModel):
    email_id: str
    connected_account_id: str

class WebhookPayload(BaseModel):
    detected_at: str
    row_data: List[str]
    row_number: int
    sheet_name: str
    spreadsheet_id: str

# ---------- Save connected account endpoint ----------
@app.post("/save-connected-account")
async def save_account(payload: ConnectedAccount):
    try:
        await save_connected_account(payload.email_id, payload.connected_account_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- Composio webhook endpoint ----------
@app.post("/composio-webhook")
async def composio_webhook(payload: WebhookPayload):
    try:
        row = payload.row_data
        if len(row) < 1 or not row[-1]:
            raise HTTPException(status_code=400, detail="Email missing in row_data")
        email_id = row[-1].strip()

        # Lookup connected_account_id
        connected_account_id = await get_connected_account_id(email_id)
        if not connected_account_id:
            raise HTTPException(status_code=404, detail="Connected account not found")

        # Map row_data → Salesforce contact (snake_case)
        contact_data = {
            "salutation": row[1] if len(row) > 1 else "",
            "first_name": row[2] if len(row) > 2 else "",
            "last_name": row[3] if len(row) > 3 else "",
            "email": email_id if email_id else "",
            "phone": "",          # optional
            "mailing_street": "", # optional
            "languages__c": ""    # optional
        }

        if not contact_data["last_name"]:
            raise HTTPException(status_code=400, detail="Last name is required for Salesforce contact")

        # Call Composio tool
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://backend.composio.dev/api/v3/tools/execute/SALESFORCE_CREATE_CONTACT",
                headers={
                    "x-api-key": COMPOSIO_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "connected_account_id": connected_account_id,
                    "arguments": contact_data
                }
            )
            result = response.json()
            print(f"SALESFORCE_CREATE_CONTACT result: {result}")

        # Return 200 OK to Composio
        return {"status": "success", "detail": "Trigger handled"}

    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
