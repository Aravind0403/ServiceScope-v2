"""
Tenant Router

CRUD endpoints for tenant management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
import secrets

from app.db import get_db
from app.models import Tenant, User
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse
from app.core.dependencies import get_current_user, get_current_admin_user

router = APIRouter()


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
        tenant_data: TenantCreate,
        db: AsyncSession = Depends(get_db)
):
    """
    Create a new tenant.

    Public endpoint - anyone can create a tenant (for demo purposes).
    In production, this would be admin-only or part of signup flow.

    Args:
        tenant_data: Tenant creation data
        db: Database session

    Returns:
        Created tenant with API key
    """
    # Generate API key (SHA-256 hash of random bytes)
    api_key = secrets.token_urlsafe(32)

    # Create tenant
    new_tenant = Tenant(
        name=tenant_data.name,
        api_key=api_key
    )

    db.add(new_tenant)
    await db.commit()
    await db.refresh(new_tenant)

    return new_tenant


@router.get("/", response_model=List[TenantResponse])
async def list_tenants(
        skip: int = 0,
        limit: int = 100,
        current_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
):
    """
    List all tenants (admin only).

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        List of tenants
    """
    result = await db.execute(
        select(Tenant).offset(skip).limit(limit)
    )
    tenants = result.scalars().all()
    return tenants


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get current user's tenant information.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        Tenant information
    """
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )

    return tenant


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
        tenant_id: UUID,
        current_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get tenant by ID (admin only).

    Args:
        tenant_id: Tenant UUID
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        Tenant information

    Raises:
        HTTPException: If tenant not found
    """
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )

    return tenant


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
        tenant_id: UUID,
        tenant_data: TenantUpdate,
        current_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Update tenant (admin only).

    Args:
        tenant_id: Tenant UUID
        tenant_data: Fields to update
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        Updated tenant

    Raises:
        HTTPException: If tenant not found
    """
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )

    # Update fields
    update_data = tenant_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)

    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
        tenant_id: UUID,
        current_user: User = Depends(get_current_admin_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Delete tenant (admin only).

    ⚠  This will cascade delete all users, repositories, etc.

    Args:
        tenant_id: Tenant UUID
        current_user: Current authenticated admin user
        db: Database session

    Raises:
        HTTPException: If tenant not found
    """
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )

    await db.delete(tenant)
    await db.commit()