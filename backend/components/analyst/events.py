from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging
import json

from backend.components.shared.models import FinancialEvent
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

router = APIRouter()

class EventClassificationRequest(BaseModel):
    text: str
    date: datetime = datetime.now()

class EventClassificationResponse(BaseModel):
    events: List[FinancialEvent]

@router.post("/events/classify", response_model=EventClassificationResponse)
async def classify_events(request: EventClassificationRequest):
    """
    Detects financial events from text.
    """
    events = await classify_events_logic(request.text, request.date)
    return EventClassificationResponse(events=events)

async def classify_events_logic(text: str, date: datetime) -> List[FinancialEvent]:
    logger.info(f"Classifying events from text ({len(text)} chars)")
    system, prompt = render("classify_events", text=text)

    try:
        response = await llm_service.get_completion(
            prompt,
            system_prompt=system,
            tier="fast",
        )
        
        if response == "LLM_DISABLED":
            return []
            
        # Clean response
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
            
        data = json.loads(response.strip())
        events = []
        for item in data:
            events.append(FinancialEvent(
                event_type=item["event_type"],
                description=item["description"],
                date=date,
                symbols=item.get("symbols", []),
                impact_rating=item.get("impact_rating", 5)
            ))
            
        logger.info(f"Event classification complete. Found {len(events)} events")
        return events
        
    except Exception as e:
        logger.error(f"Error classifying events: {e}")
        return []
