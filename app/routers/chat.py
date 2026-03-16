"""
Chat API Router

Enables users to ask questions about their analyzed repositories.
Uses LLM with repository context for intelligent answers.

Example Flow:
1. User: "What services does my order service depend on?"
2. System: Retrieves dependencies from database
3. System: Sends context + question to LLM
4. LLM: Responds with structured answer
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel, Field
import requests

from app.db.session import get_db
from app.routers.auth import get_current_user
from app.models import User, Repository, ExtractedCall, InferredDependency
from app.config import settings

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# --- Schemas ---

class ChatMessage(BaseModel):
    """User message to chat system."""
    repository_id: str = Field(..., description="Repository to ask about")
    question: str = Field(..., min_length=1, max_length=1000,
                          description="User's question")


class ChatResponse(BaseModel):
    """LLM response to user."""
    answer: str
    context_used: dict
    model: str


# --- Helper Functions ---

async def get_repository_context(
        repository_id: str,
        db: AsyncSession
) -> dict:
    """
    Gather all relevant data about a repository for LLM context.

    Returns structured data about:
    - Services found
    - Dependencies mapped
    - HTTP calls extracted
    """

    # Get repository info
    repo_result = await db.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    repo = repo_result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Get all extracted calls
    calls_result = await db.execute(
        select(ExtractedCall).where(ExtractedCall.repository_id == repository_id)
    )
    calls = calls_result.scalars().all()

    # Get all inferred dependencies
    deps_result = await db.execute(
        select(InferredDependency)
        .join(ExtractedCall, InferredDependency.extracted_call_id == ExtractedCall.id)
        .where(ExtractedCall.repository_id == repository_id)
    )
    dependencies = deps_result.scalars().all()

    # Build service map
    services_map = {}
    for dep in dependencies:
        if dep.caller_service not in services_map:
            services_map[dep.caller_service] = {
                "depends_on": [],
                "called_by": []
            }
        if dep.callee_service not in services_map:
            services_map[dep.callee_service] = {
                "depends_on": [],
                "called_by": []
            }

        services_map[dep.caller_service]["depends_on"].append({
            "service": dep.callee_service,
            "confidence": dep.confidence
        })
        services_map[dep.callee_service]["called_by"].append({
            "service": dep.caller_service,
            "confidence": dep.confidence
        })

    # Build context
    context = {
        "repository": {
            "name": repo.name,
            "url": repo.url,
            "total_files": repo.file_count,
            "commit": repo.commit_hash
        },
        "analysis": {
            "total_http_calls": len(calls),
            "total_dependencies": len(dependencies),
            "services_count": len(services_map)
        },
        "services": services_map,
        "sample_calls": [
            {
                "service": call.service_name,
                "method": call.method,
                "url": call.url,
                "file": call.file_path
            }
            for call in calls[:10]  # First 10 as sample
        ]
    }

    return context


def ask_llm_with_context(
        question: str,
        context: dict
) -> str:
    """
    Send question + repository context to LLM.

    Formats context clearly so LLM can answer accurately.
    """

    # Build context summary
    services_list = ", ".join(context["services"].keys())

    context_text = f"""
Repository Analysis Context:
- Repository: {context['repository']['name']}
- Total HTTP Calls Found: {context['analysis']['total_http_calls']}
- Total Dependencies: {context['analysis']['total_dependencies']}
- Services Identified: {services_list}

Service Dependencies:
"""

    for service, info in context["services"].items():
        if info["depends_on"]:
            deps = ", ".join([d["service"] for d in info["depends_on"]])
            context_text += f"\n- {service} depends on: {deps}"

    # Build prompt
    prompt = f"""You are a software architecture assistant. Use the following repository analysis to answer the user's question accurately.

{context_text}

User Question: {question}

Provide a clear, concise answer based on the analysis data above. If the data doesn't contain enough information to answer, say so."""

    # Call LLM
    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": settings.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"LLM request failed: {str(e)}"
        )


# --- Endpoints ---

@router.post("/ask", response_model=ChatResponse)
async def ask_question(
        message: ChatMessage,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Ask a question about an analyzed repository.

    The system will:
    1. Retrieve analysis data for the repository
    2. Send question + context to LLM
    3. Return LLM's answer

    Example questions:
    - "What services does order_service depend on?"
    - "Which service is most critical (most dependencies)?"
    - "What HTTP calls does payment_service make?"
    - "Explain the architecture of this system"
    """

    # Get repository context
    context = await get_repository_context(message.repository_id, db)

    # Ask LLM
    answer = ask_llm_with_context(message.question, context)

    return ChatResponse(
        answer=answer,
        context_used={
            "services_count": context["analysis"]["services_count"],
            "dependencies_count": context["analysis"]["total_dependencies"],
            "calls_analyzed": context["analysis"]["total_http_calls"]
        },
        model=settings.OLLAMA_MODEL
    )


@router.get("/repositories/{repository_id}/summary")
async def get_repository_summary(
        repository_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get a quick summary of repository analysis.

    Useful for showing user what they can ask about.
    """

    context = await get_repository_context(repository_id, db)

    # Generate automatic summary
    services = list(context["services"].keys())
    critical_services = sorted(
        services,
        key=lambda s: len(context["services"][s]["called_by"]),
        reverse=True
    )[:5]

    return {
        "repository": context["repository"]["name"],
        "statistics": context["analysis"],
        "services": services,
        "most_critical_services": critical_services,
        "sample_dependencies": [
            f"{service} → {', '.join([d['service'] for d in info['depends_on']])}"
            for service, info in list(context["services"].items())[:5]
            if info["depends_on"]
        ]
    }


@router.post("/repositories/{repository_id}/insights")
async def get_ai_insights(
        repository_id: str,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get automatic AI-generated insights about the repository.

    LLM analyzes the architecture and provides:
    - Critical services
    - Potential issues
    - Architecture patterns
    """

    context = await get_repository_context(repository_id, db)

    # Ask LLM for insights
    insights_prompt = f"""Analyze this microservice architecture and provide insights:

Total Services: {context['analysis']['services_count']}
Total Dependencies: {context['analysis']['total_dependencies']}

Service Dependencies:
"""

    for service, info in context["services"].items():
        if info["depends_on"]:
            deps = ", ".join([d["service"] for d in info["depends_on"]])
            insights_prompt += f"\n- {service} → {deps}"

    insights_prompt += """

Provide 3-5 key insights about this architecture:
1. Most critical services (with most dependencies)
2. Potential single points of failure
3. Complexity hotspots
4. Any architectural patterns you notice

Be concise and specific."""

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": settings.OLLAMA_MODEL,
                "prompt": insights_prompt,
                "stream": False
            },
            timeout=240
        )
        response.raise_for_status()
        data = response.json()

        return {
            "repository_id": repository_id,
            "insights": data.get("response", "").strip(),
            "generated_at": "now",
            "model": settings.OLLAMA_MODEL
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate insights: {str(e)}"
        )