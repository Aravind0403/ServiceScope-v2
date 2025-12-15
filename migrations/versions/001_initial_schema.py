"""Initial schema - multi-tenant database

Revision ID: 001
Revises:
Create Date: 2024-12-12 00:00:00

Creates:
- tenants table
- users table
- repositories table
- analysis_jobs table
- extracted_calls table
- inferred_dependencies table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tenants table
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('api_key', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('rate_limit_rpm', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('max_repositories', sa.Integer(), nullable=False,
                  server_default='10'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tenants_api_key', 'tenants', ['api_key'], unique=True)

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255)),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])

    # Create repositories table
    op.create_table(
        'repositories',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('name', sa.String(length=255)),
        sa.Column('branch', sa.String(length=100), server_default='main'),
        sa.Column('status',
                  sa.Enum('PENDING', 'CLONING', 'ANALYZING', 'COMPLETED', 'FAILED',
                          name='repositorystatus'), nullable=False),
        sa.Column('error_message', sa.Text()),
        sa.Column('clone_path', sa.String(length=512)),
        sa.Column('commit_hash', sa.String(length=40)),
        sa.Column('file_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_repositories_tenant_id', 'repositories', ['tenant_id'])
    op.create_index('ix_repositories_status', 'repositories', ['status'])

    # Create analysis_jobs table
    op.create_table(
        'analysis_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status',
                  sa.Enum('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED',
                          name='jobstatus'), nullable=False),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('error_message', sa.Text()),
        sa.Column('result_summary', postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_repository_id', 'analysis_jobs', ['repository_id'])
    op.create_index('ix_jobs_status', 'analysis_jobs', ['status'])

    # Create extracted_calls table
    op.create_table(
        'extracted_calls',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service_name', sa.String(length=255)),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_extracted_calls_repository_id', 'extracted_calls',
                    ['repository_id'])
    op.create_index('ix_extracted_calls_service_name', 'extracted_calls',
                    ['service_name'])

    # Create inferred_dependencies table
    op.create_table(
        'inferred_dependencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('extracted_call_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('caller_service', sa.String(length=255), nullable=False),
        sa.Column('callee_service', sa.String(length=255), nullable=False),
        sa.Column('confidence', sa.Float()),
        sa.Column('llm_model', sa.String(length=100)),
        sa.Column('llm_response', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['extracted_call_id'], ['extracted_calls.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_inferred_deps_extracted_call_id', 'inferred_dependencies',
                    ['extracted_call_id'], unique=True)
    op.create_index('ix_inferred_deps_caller', 'inferred_dependencies',
                    ['caller_service'])
    op.create_index('ix_inferred_deps_callee', 'inferred_dependencies',
                    ['callee_service'])


def downgrade() -> None:
    op.drop_index('ix_inferred_deps_callee', table_name='inferred_dependencies')
    op.drop_index('ix_inferred_deps_caller', table_name='inferred_dependencies')
    op.drop_index('ix_inferred_deps_extracted_call_id',
                  table_name='inferred_dependencies')
    op.drop_table('inferred_dependencies')

    op.drop_index('ix_extracted_calls_service_name', table_name='extracted_calls')
    op.drop_index('ix_extracted_calls_repository_id', table_name='extracted_calls')
    op.drop_table('extracted_calls')

    op.drop_index('ix_jobs_status', table_name='analysis_jobs')
    op.drop_index('ix_jobs_repository_id', table_name='analysis_jobs')
    op.drop_table('analysis_jobs')

    op.drop_index('ix_repositories_status', table_name='repositories')
    op.drop_index('ix_repositories_tenant_id', table_name='repositories')
    op.drop_table('repositories')

    op.drop_index('ix_users_tenant_id', table_name='users')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')

    op.drop_index('ix_tenants_api_key', table_name='tenants')
    op.drop_table('tenants')

    # Drop enums
    sa.Enum(name='repositorystatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='jobstatus').drop(op.get_bind(), checkfirst=True)