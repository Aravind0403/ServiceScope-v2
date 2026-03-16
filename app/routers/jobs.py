"""
Analysis Jobs Router

Endpoints for monitoring analysis job progress.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID

from app.db import get_db
from app.models import AnalysisJob, Repository, User
from app.schemas.job import AnalysisJobResponse
from app.core.dependencies import get_current_user

router = APIRouter()


@router.get("/repository/{repo_id}", response_model=List[AnalysisJobResponse])
async def get_repository_jobs(
        repo_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get all analysis jobs for a repository.

    Args:
        repo_id: Repository UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of analysis jobs
    """
    # Verify repository exists and user has access
    result = await db.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    if repo.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Get jobs
    result = await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.repository_id == repo_id)
        .order_by(AnalysisJob.created_at.desc())
    )
    jobs = result.scalars().all()

    return jobs


@router.get("/{job_id}", response_model=AnalysisJobResponse)
async def get_job(
        job_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get analysis job by ID.

    Args:
        job_id: Job UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Analysis job details
    """
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    # Verify user has access (check repository tenant)
    result = await db.execute(
        select(Repository).where(Repository.id == job.repository_id)
    )
    repo = result.scalar_one_or_none()

    if not repo or repo.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return job