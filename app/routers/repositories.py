"""
Repository Router

CRUD endpoints for repository management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID

from app.db import get_db
from app.models import Repository, User
from app.models.repository import RepositoryStatus
from app.schemas.repository import (
    RepositoryCreate,
    RepositoryUpdate,
    RepositoryResponse,
    RepositoryListResponse
)
from app.core.dependencies import get_current_user


router = APIRouter()


@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def create_repository(
    repo_data: RepositoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a repository for analysis.

    Args:
        repo_data: Repository data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created repository

    Raises:
        HTTPException: If user doesn't belong to tenant
    """
    # Verify user belongs to tenant
    if current_user.tenant_id != repo_data.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create repository for different tenant"
        )

    # Create repository
    new_repo = Repository(
        tenant_id=repo_data.tenant_id,
        url=repo_data.url,
        name=repo_data.name,
        branch=repo_data.branch,
        status=RepositoryStatus.PENDING
    )

    db.add(new_repo)
    await db.commit()
    await db.refresh(new_repo)

    # Trigger Celery task for analysis
    from app.tasks.analyzer import analyze_repository
    analyze_repository.delay(str(new_repo.id))

    return new_repo


@router.get("/", response_model=RepositoryListResponse)
async def list_repositories(
    skip: int = 0,
    limit: int = 100,
    status_filter: RepositoryStatus = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List repositories for current user's tenant.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        status_filter: Filter by status (optional)
        current_user: Current authenticated user
        db: Database session

    Returns:
        Paginated list of repositories
    """
    # Build query
    query = select(Repository).where(Repository.tenant_id == current_user.tenant_id)

    if status_filter:
        query = query.where(Repository.status == status_filter)

    # Get total count
    count_query = select(func.count()).select_from(Repository).where(
        Repository.tenant_id == current_user.tenant_id
    )
    if status_filter:
        count_query = count_query.where(Repository.status == status_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = query.offset(skip).limit(limit).order_by(Repository.created_at.desc())
    result = await db.execute(query)
    repositories = result.scalars().all()

    return RepositoryListResponse(
        items=repositories,
        total=total,
        page=skip // limit + 1 if limit > 0 else 1,
        page_size=limit
    )


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get repository by ID.

    Args:
        repo_id: Repository UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Repository details

    Raises:
        HTTPException: If repository not found or access denied
    """
    result = await db.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    # Verify user has access (same tenant)
    if repo.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return repo


@router.patch("/{repo_id}", response_model=RepositoryResponse)
async def update_repository(
    repo_id: UUID,
    repo_data: RepositoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update repository.

    Args:
        repo_id: Repository UUID
        repo_data: Fields to update
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated repository

    Raises:
        HTTPException: If repository not found or access denied
    """
    result = await db.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    # Verify user has access
    if repo.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Update fields
    update_data = repo_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(repo, field, value)

    await db.commit()
    await db.refresh(repo)

    return repo


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete repository.

    ⚠️  This will cascade delete all analysis jobs, API calls, etc.

    Args:
        repo_id: Repository UUID
        current_user: Current authenticated user
        db: Database session

    Raises:
        HTTPException: If repository not found or access denied
    """
    result = await db.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    # Verify user has access
    if repo.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    await db.delete(repo)
    await db.commit()