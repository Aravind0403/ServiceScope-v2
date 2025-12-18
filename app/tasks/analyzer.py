"""
Repository Analysis Task

Main Celery task for analyzing repositories.

Pipeline:
1. Clone repository
2. Extract HTTP calls (AST)
3. Infer service dependencies (LLM)
4. Load to Neo4j
"""

import os
import shutil
import subprocess
from uuid import UUID
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models import Repository, AnalysisJob, ExtractedCall, InferredDependency
from app.models.repository import RepositoryStatus
from app.models.job import JobStatus


@celery_app.task(bind=True, name="analyze_repository")
def analyze_repository(self, repository_id: str):
    """
    Analyze a repository for service dependencies.

    Args:
        repository_id: Repository UUID

    Returns:
        dict: Analysis results
    """
    # Use sync engine for Celery tasks
    engine = create_engine(settings.SYNC_DATABASE_URL)

    with Session(engine) as db:
        # Get repository
        repo = db.execute(
            select(Repository).where(Repository.id == UUID(repository_id))
        ).scalar_one_or_none()

        if not repo:
            return {"error": "Repository not found"}

        # Create analysis job
        job = AnalysisJob(
            repository_id=repo.id,
            status=JobStatus.RUNNING,
            progress=0.0,
            started_at=datetime.utcnow()
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        try:
            # Update repository status
            repo.status = RepositoryStatus.CLONING
            db.commit()

            # Step 1: Clone repository (10% progress)
            job.update_progress(10.0, JobStatus.RUNNING)
            db.commit()

            clone_path = clone_repository(repo.url, repo.branch)
            repo.clone_path = clone_path

            # Get commit hash and file count
            repo.commit_hash = get_commit_hash(clone_path)
            repo.file_count = count_python_files(clone_path)
            db.commit()

            # Step 2: Extract HTTP calls (30% progress)
            job.update_progress(30.0, JobStatus.RUNNING)
            db.commit()

            repo.status = RepositoryStatus.ANALYZING
            db.commit()

            extracted_calls = extract_http_calls(clone_path)

            # Save extracted calls to database
            for call_data in extracted_calls:
                call = ExtractedCall(
                    repository_id=repo.id,
                    service_name=call_data.get("service"),
                    method=call_data.get("method"),
                    url=call_data.get("url"),
                    file_path=call_data.get("file"),
                    line_number=call_data.get("line")
                )
                db.add(call)

            db.commit()

            # Step 3: Infer dependencies with LLM (60% progress)
            job.update_progress(60.0, JobStatus.RUNNING)
            db.commit()

            # Get all saved calls
            calls = db.execute(
                select(ExtractedCall).where(ExtractedCall.repository_id == repo.id)
            ).scalars().all()

            for call in calls:
                # Infer dependency
                inference = infer_service_dependency(
                    caller=call.service_name,
                    url=call.url,
                    method=call.method
                )

                if inference:
                    dependency = InferredDependency(
                        extracted_call_id=call.id,
                        caller_service=call.service_name,
                        callee_service=inference.get("callee"),
                        confidence=inference.get("confidence"),
                        llm_model=inference.get("model"),
                        llm_response=inference.get("raw_response")
                    )
                    db.add(dependency)

            db.commit()

            # Step 4: Load to Neo4j (90% progress)
            job.update_progress(90.0, JobStatus.RUNNING)
            db.commit()

            load_to_neo4j(repo.id, db)

            # Complete (100% progress)
            repo.status = RepositoryStatus.COMPLETED
            job.update_progress(100.0, JobStatus.COMPLETED)
            job.completed_at = datetime.utcnow()
            job.result_summary = {
                "total_calls": len(extracted_calls),
                "services_found": len(set(c.service_name for c in calls)),
                "dependencies_inferred": db.execute(
                    select(InferredDependency).where(
                        InferredDependency.extracted_call_id.in_([c.id for c in calls])
                    )
                ).scalars().all().__len__()
            }

            db.commit()

            # Cleanup
            cleanup_clone(clone_path)

            return {
                "status": "completed",
                "repository_id": str(repo.id),
                "job_id": str(job.id),
                "summary": job.result_summary
            }

        except Exception as e:
            # Handle failure
            repo.status = RepositoryStatus.FAILED
            repo.error_message = str(e)

            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()

            db.commit()

            return {"error": str(e), "repository_id": str(repo.id)}


def clone_repository(url: str, branch: str = "main") -> str:
    """Clone a git repository."""
    clone_dir = os.path.join(settings.REPO_CLONE_DIR, f"repo_{os.urandom(8).hex()}")
    os.makedirs(clone_dir, exist_ok=True)

    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, url, clone_dir],
        check=True,
        timeout=settings.CLONE_TIMEOUT_SECONDS
    )

    return clone_dir


def get_commit_hash(clone_path: str) -> str:
    """Get current commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone_path,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def count_python_files(clone_path: str) -> int:
    """Count Python files in repository."""
    count = 0
    for root, dirs, files in os.walk(clone_path):
        count += sum(1 for f in files if f.endswith(".py"))
    return count


def extract_http_calls(clone_path: str) -> list:
    """Extract HTTP calls using AST analysis."""
    from app.extraction import walk_and_extract_calls
    return walk_and_extract_calls(clone_path)


def infer_service_dependency(caller: str, url: str, method: str) -> dict:
    """Infer service dependency using LLM."""
    import requests

    prompt = f"""
Given the URL {url} used by service {caller}, what is the most likely internal service name being called?
Please only return the most probable service name as a short answer like: "payment_service" or "order_service".
    """

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": settings.OLLAMA_MODEL,
                "prompt": prompt.strip(),
                "stream": False
            },
            timeout=settings.OLLAMA_TIMEOUT
        )

        data = response.json()

        if "response" in data:
            raw_response = data["response"].strip()
            cleaned = raw_response.replace("**", "").strip().strip('"').split('\n')[0]

            return {
                "callee": cleaned,
                "confidence": 0.8,  # Default confidence
                "model": settings.OLLAMA_MODEL,
                "raw_response": raw_response
            }
    except Exception as e:
        print(f"LLM inference failed: {e}")
        return None


def load_to_neo4j(repository_id: UUID, db: Session):
    """Load dependencies to Neo4j graph database."""
    try:
        from app.db.neo4j_session import neo4j_client

        # Get all dependencies for this repository
        calls = db.execute(
            select(ExtractedCall).where(ExtractedCall.repository_id == repository_id)
        ).scalars().all()

        for call in calls:
            # Get inference
            dependency = db.execute(
                select(InferredDependency).where(
                    InferredDependency.extracted_call_id == call.id
                )
            ).scalar_one_or_none()

            if dependency:
                # Create nodes and relationship in Neo4j
                neo4j_client.create_service_node(dependency.caller_service)
                neo4j_client.create_service_node(dependency.callee_service)
                neo4j_client.create_dependency_edge(
                    caller=dependency.caller_service,
                    callee=dependency.callee_service,
                    method=call.method,
                    url=call.url,
                    confidence=dependency.confidence
                )
        print("✅ Loaded to Neo4j")
    except Exception as e:
        print(f"⚠️  Neo4j not available, skipping graph creation: {e}")


    def load_to_neo4j(repository_id: UUID, db: Session):
        """Load dependencies to Neo4j graph database."""
        try:
            from app.db.neo4j_session import neo4j_client

            # Get all dependencies for this repository
            calls = db.execute(
                select(ExtractedCall).where(ExtractedCall.repository_id == repository_id)
            ).scalars().all()

            for call in calls:
                # Get inference
                dependency = db.execute(
                    select(InferredDependency).where(
                        InferredDependency.extracted_call_id == call.id
                    )
                ).scalar_one_or_none()

                if dependency:
                    # Create nodes and relationship in Neo4j
                    neo4j_client.create_service_node(dependency.caller_service)
                    neo4j_client.create_service_node(dependency.callee_service)
                    neo4j_client.create_dependency_edge(
                        caller=dependency.caller_service,
                        callee=dependency.callee_service,
                        method=call.method,
                        url=call.url,
                        confidence=dependency.confidence
                    )
            print("✅ Loaded to Neo4j")
        except Exception as e:
            print(f"⚠️  Neo4j not available, skipping graph creation: {e}")
def cleanup_clone(clone_path: str):
    """Remove cloned repository."""
    if os.path.exists(clone_path):
        shutil.rmtree(clone_path)