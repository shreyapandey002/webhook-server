from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List
import asyncpg
import httpx
import os
import hmac
import hashlib

app = FastAPI(title="Composio FastAPI Server")

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # For verifying Composio webhook

db_pool: asyncpg.pool.Pool | None = None

# ---------- Startup / Shutdown ----------
@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)

@app.on_event("shutdown")
async def shutdown():
    await db_pool.close()

# ---------- Neon DB helpers ----------
async def save_connected_account(email_id: str, connected_account_id: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users(email_id, connected_account_id, created_at)
            VALUES($1, $2, NOW())
            ON CONFLICT (email_id) DO UPDATE SET connected_account_id = EXCLUDED.connected_account_id
        """, email_id, connected_account_id)

async def get_connected_account_id(email_id: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT connected_account_id FROM users WHERE email_id = $1", email_id)
        return row["connected_account_id"] if row else None

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
        print("Error saving connected account:", e)
        raise HTTPException(status_code=500, detail=str(e))

# ---------- Helper: verify webhook ----------
def verify_webhook(request: Request, body: bytes):
    signature = request.headers.get("x-webhook-signature")
    if not signature:
        return False
    computed_hmac = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hmac, signature)

# ---------- Composio webhook endpoint ----------
@app.post("/composio-webhook")
async def composio_webhook(request: Request):
    body = await request.body()

    # Verify webhook signature
    if not verify_webhook(request, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = WebhookPayload.parse_raw(body)

    try:
        row = payload.row_data
        if len(row) < 4:
            raise HTTPException(status_code=400, detail="Incomplete row data")
        email_id = row[-1].strip()

        # Lookup connected_account_id
        connected_account_id = await get_connected_account_id(email_id)
        if not connected_account_id:
            raise HTTPException(status_code=404, detail="Connected account not found")

        # Map row_data → Salesforce contact (snake_case, without email)
        contact_data = {
            "salutation": row[1],
            "first_name": row[2],
            "last_name": row[3]
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

        return {"status": "success", "detail": "Trigger handled"}

    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
