"""
main.py - FastAPI Webhook Server
Deploy this on Render.com

This server receives webhook events from Composio when new rows are added
to your Google Sheet, then creates contacts in Salesforce.
"""

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Composio Webhook Server - Enhanced")

# ------------------------------
# CONFIG
# ------------------------------
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "ak_D5D8su1vCNMqIxyI71il")
SALESFORCE_CONNECTED_ACCOUNT_ID = os.getenv("SALESFORCE_CA_ID", "ca_LdMKDhu7AUxJ")

# ------------------------------
# MODELS
# ------------------------------
class WebhookPayload(BaseModel):
    detected_at: str
    row_data: List[str]
    row_number: int
    sheet_name: str
    spreadsheet_id: str
    trigger_name: Optional[str] = None

# ------------------------------
# HELPER FUNCTIONS
# ------------------------------
async def create_salesforce_contact(contact_data: dict) -> dict:
    """Create a Salesforce contact via Composio API"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://backend.composio.dev/api/v3/tools/execute/SALESFORCE_CREATE_CONTACT",
                headers={
                    "x-api-key": COMPOSIO_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "connected_account_id": SALESFORCE_CONNECTED_ACCOUNT_ID,
                    "arguments": contact_data,
                },
                timeout=60,
            )
            
            result = response.json()
            logger.info(f"Salesforce API response: {result}")
            
            if response.status_code != 200:
                raise Exception(f"Salesforce API error: {result}")
            
            return result
            
        except httpx.TimeoutException:
            raise Exception("Salesforce API timeout")
        except Exception as e:
            logger.error(f"Error creating Salesforce contact: {e}")
            raise

def parse_row_to_contact(row: List[str]) -> dict:
    """Parse Google Sheets row into Salesforce contact format"""
    if len(row) < 4:
        raise ValueError("Row must have at least 4 columns: [ID, Salutation, FirstName, LastName]")
    
    contact = {
        "last_name": row[3].strip() if len(row) > 3 else "",
    }
    
    # Optional fields
    if len(row) > 1 and row[1].strip():
        contact["salutation"] = row[1].strip()
    if len(row) > 2 and row[2].strip():
        contact["first_name"] = row[2].strip()
    
    # Validate required fields
    if not contact["last_name"]:
        raise ValueError("Last name is required")
    
    return contact

# ------------------------------
# WEBHOOK ENDPOINTS
# ------------------------------
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Composio Webhook Server",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/composio-webhook")
async def composio_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for Composio triggers
    Receives Google Sheets row data and creates Salesforce contacts
    """
    try:
        # Log raw request
        body = await request.json()
        logger.info(f"Received webhook: {body}")
        
        # Parse payload
        payload = WebhookPayload(**body)
        logger.info(f"Processing row {payload.row_number} from sheet '{payload.sheet_name}'")
        
        # Parse contact data
        contact_data = parse_row_to_contact(payload.row_data)
        logger.info(f"Parsed contact: {contact_data}")
        
        # Create Salesforce contact
        result = await create_salesforce_contact(contact_data)
        
        return {
            "status": "success",
            "message": "Salesforce contact created",
            "row_number": payload.row_number,
            "contact": contact_data,
            "salesforce_result": result.get("data", {})
        }
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process webhook: {str(e)}"
        )

@app.get("/test-salesforce")
async def test_salesforce():
    """Test endpoint to verify Salesforce connection"""
    test_contact = {
        "first_name": "Test",
        "last_name": "Contact",
        "salutation": "Mr."
    }
    
    try:
        result = await create_salesforce_contact(test_contact)
        return {
            "status": "success",
            "message": "Test contact created",
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------
# STARTUP
# ------------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("=== Composio Webhook Server Started ===")
    logger.info(f"Salesforce Connected Account: {SALESFORCE_CONNECTED_ACCOUNT_ID}")
    logger.info(f"Webhook URL: https://webhook-server-tw8c.onrender.com/composio-webhook")