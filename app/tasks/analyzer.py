"""
Repository Analysis Task

Main Celery task for analyzing repositories.

Pipeline:
1. Clone repository
2. Extract HTTP calls (AST)
3. Infer service dependencies (LLM)
4. Load to Neo4j
"""

import json as _json
import os
import re
import shutil
import subprocess
import requests
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

            failed_inferences = 0
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
                else:
                    failed_inferences += 1

            db.commit()

            # Step 4: Load to Neo4j (90% progress)
            job.update_progress(90.0, JobStatus.RUNNING)
            db.commit()

            load_to_neo4j(repo.id, repo.tenant_id, db)

            # Complete (100% progress)
            total_calls = len(calls)
            inference_failure_rate = (failed_inferences / total_calls) if total_calls > 0 else 0.0
            final_status = (
                JobStatus.COMPLETED_WITH_WARNINGS
                if inference_failure_rate > 0.5
                else JobStatus.COMPLETED
            )

            repo.status = RepositoryStatus.COMPLETED
            job.update_progress(100.0, final_status)
            job.completed_at = datetime.utcnow()
            job.result_summary = {
                "total_calls": len(extracted_calls),
                "services_found": len(set(c.service_name for c in calls)),
                "dependencies_inferred": db.execute(
                    select(InferredDependency).where(
                        InferredDependency.extracted_call_id.in_([c.id for c in calls])
                    )
                ).scalars().all().__len__(),
                "failed_inferences": failed_inferences,
                "inference_failure_rate": round(inference_failure_rate, 3),
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

        except subprocess.CalledProcessError as e:
            # Catch any raw CalledProcessError not already handled by clone_repository()
            stderr_detail = (
                e.stderr.strip()
                if hasattr(e, "stderr") and e.stderr
                else str(e)
            )
            error_msg = f"Git operation failed: {stderr_detail}"

            repo.status = RepositoryStatus.FAILED
            repo.error_message = error_msg

            job.status = JobStatus.FAILED
            job.error_message = error_msg
            job.completed_at = datetime.utcnow()

            db.commit()
            return {"error": error_msg, "repository_id": str(repo.id)}

        except Exception as e:
            # Handle all other failures (LLM errors, DB errors, etc.)
            repo.status = RepositoryStatus.FAILED
            repo.error_message = str(e)

            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()

            db.commit()

            return {"error": str(e), "repository_id": str(repo.id)}


def _parse_git_error(stderr: str, url: str, branch: str) -> str:
    """
    Translate raw git stderr into a human-readable error message.

    Args:
        stderr: Captured stderr from the failed git subprocess.
        url:    Repository URL that was cloned.
        branch: Branch name that was requested.

    Returns:
        Concise user-facing error string.
    """
    lower = stderr.lower()

    if "not found" in lower and "repository" in lower:
        return f"Repository not found or is private: {url}"

    if "could not read from remote" in lower:
        return f"Cannot access repository (private or URL invalid): {url}"

    if re.search(r"remote branch .+ not found", lower):
        return (
            f"Branch '{branch}' does not exist in {url}. "
            f"Try 'main' or 'master'."
        )

    if "authentication failed" in lower:
        return f"Authentication failed for {url}. Repository may be private."

    if "could not resolve host" in lower:
        return f"Cannot resolve hostname in URL: {url}"

    if "already exists" in lower and "not an empty directory" in lower:
        return f"Clone directory conflict for {url}. Please retry."

    if stderr:
        truncated = stderr[:500] if len(stderr) > 500 else stderr
        return f"Git clone failed: {truncated}"

    return f"Git clone failed with no error output for: {url}"


def clone_repository(url: str, branch: str = "main") -> str:
    """
    Clone a git repository (shallow, single branch).

    Attempts the specified branch first. If that branch does not exist,
    retries without --branch to use the repo's default branch.
    Raises RuntimeError with a human-readable message on any failure.
    """
    clone_dir = os.path.join(settings.REPO_CLONE_DIR, f"repo_{os.urandom(8).hex()}")
    os.makedirs(clone_dir, exist_ok=True)

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, url, clone_dir],
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.CLONE_TIMEOUT_SECONDS,
        )
        return clone_dir

    except subprocess.TimeoutExpired:
        shutil.rmtree(clone_dir, ignore_errors=True)
        raise RuntimeError(
            f"Clone timed out after {settings.CLONE_TIMEOUT_SECONDS}s: {url}"
        )

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""

        # Branch not found → retry without --branch (uses repo default)
        if re.search(r"remote branch .+ not found", stderr.lower()):
            shutil.rmtree(clone_dir, ignore_errors=True)
            os.makedirs(clone_dir, exist_ok=True)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", url, clone_dir],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=settings.CLONE_TIMEOUT_SECONDS,
                )
                return clone_dir  # fallback succeeded
            except subprocess.TimeoutExpired:
                shutil.rmtree(clone_dir, ignore_errors=True)
                raise RuntimeError(
                    f"Clone timed out after {settings.CLONE_TIMEOUT_SECONDS}s "
                    f"on fallback: {url}"
                )
            except subprocess.CalledProcessError as e2:
                shutil.rmtree(clone_dir, ignore_errors=True)
                raise RuntimeError(
                    _parse_git_error(e2.stderr or "", url, branch)
                ) from e2

        shutil.rmtree(clone_dir, ignore_errors=True)
        raise RuntimeError(_parse_git_error(stderr, url, branch)) from e


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

    prompt = f"""You are a microservice architecture assistant.

Given this HTTP call made by service "{caller}":
  Method: {method.upper()}
  URL: {url}

Identify the most likely internal service being called and your confidence.

Respond with ONLY a JSON object, no markdown, no explanation:
{{"service": "service_name", "confidence": 0.0}}

Where "service" is a short snake_case name (e.g. "payment_service") and
"confidence" is a float between 0.0 and 1.0."""

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

        if "response" not in data:
            return None

        raw_response = data["response"].strip()

        # Parse JSON response; fall back to text extraction if needed
        confidence = 0.5  # fallback if LLM does not provide a valid score
        callee = None

        try:
            # Strip any markdown fences the model may have added
            clean = raw_response.strip().strip("```json").strip("```").strip()
            parsed = _json.loads(clean)
            callee = str(parsed.get("service", "")).strip().strip('"')
            confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (_json.JSONDecodeError, ValueError, TypeError):
            # Fallback: take the first non-empty line as the service name
            callee = raw_response.replace("**", "").strip().strip('"').split('\n')[0]

        if not callee:
            return None

        return {
            "callee": callee,
            "confidence": confidence,
            "model": settings.OLLAMA_MODEL,
            "raw_response": raw_response
        }
    except Exception as e:
        print(f"LLM inference failed: {e}")
        return None


def load_to_neo4j(repository_id: UUID, tenant_id: UUID, db: Session):
    """Load dependencies to Neo4j graph database, scoped by tenant and repository."""
    try:
        from app.db.Neo4j_session import neo4j_client

        # Get all dependencies for this repository
        calls = db.execute(
            select(ExtractedCall).where(ExtractedCall.repository_id == repository_id)
        ).scalars().all()

        for call in calls:
            dependency = db.execute(
                select(InferredDependency).where(
                    InferredDependency.extracted_call_id == call.id
                )
            ).scalar_one_or_none()

            if dependency:
                neo4j_client.create_service_node(
                    dependency.caller_service,
                    tenant_id=str(tenant_id),
                    repository_id=str(repository_id),
                )
                neo4j_client.create_service_node(
                    dependency.callee_service,
                    tenant_id=str(tenant_id),
                    repository_id=str(repository_id),
                )
                neo4j_client.create_dependency_edge(
                    caller=dependency.caller_service,
                    callee=dependency.callee_service,
                    method=call.method,
                    url=call.url,
                    tenant_id=str(tenant_id),
                    repository_id=str(repository_id),
                    confidence=dependency.confidence,
                )
        print("✅ Loaded to Neo4j")
    except Exception as e:
        print(f"⚠️  Neo4j not available, skipping graph creation: {e}")


def cleanup_clone(clone_path: str):
    """Remove cloned repository."""
    if os.path.exists(clone_path):
        shutil.rmtree(clone_path)