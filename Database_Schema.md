# Database Schema - Complete Overview

## 📊 Entity Relationship Diagram

```
┌──────────────────┐
│     Tenant       │
│ ================ │
│ id (PK)          │
│ name             │
│ api_key          │
│ rate_limit_rpm   │
│ max_repositories │
│ is_active        │
└──────────────────┘
         │
         │ 1:N (has many)
         ├─────────────────────────────────────┐
         ↓                                     ↓
┌──────────────────┐                 ┌──────────────────┐
│      User        │                 │   Repository     │
│ ================ │                 │ ================ │
│ id (PK)          │                 │ id (PK)          │
│ tenant_id (FK)   │                 │ tenant_id (FK)   │
│ email            │                 │ url              │
│ hashed_password  │                 │ name             │
│ full_name        │                 │ branch           │
│ is_admin         │                 │ status           │
│ is_active        │                 │ error_message    │
└──────────────────┘                 │ clone_path       │
                                     │ commit_hash      │
                                     │ file_count       │
                                     └──────────────────┘
                                              │
                                              │ 1:N (has many)
                                              ├─────────────────────────┐
                                              ↓                         ↓
                                     ┌──────────────────┐     ┌──────────────────┐
                                     │  AnalysisJob     │     │ ExtractedCall    │
                                     │ ================ │     │ ================ │
                                     │ id (PK)          │     │ id (PK)          │
                                     │ repository_id FK │     │ repository_id FK │
                                     │ status           │     │ service_name     │
                                     │ progress         │     │ method           │
                                     │ started_at       │     │ url              │
                                     │ completed_at     │     │ file_path        │
                                     │ error_message    │     │ line_number      │
                                     │ result_summary   │     └──────────────────┘
                                     └──────────────────┘              │
                                                                       │ 1:1 (has one)
                                                                       ↓
                                                              ┌──────────────────────┐
                                                              │ InferredDependency   │
                                                              │ ==================== │
                                                              │ id (PK)              │
                                                              │ extracted_call_id FK │
                                                              │ caller_service       │
                                                              │ callee_service       │
                                                              │ confidence           │
                                                              │ llm_model            │
                                                              │ llm_response         │
                                                              └──────────────────────┘
```

## 🔗 Relationships Summary

| From | To | Type | Description |
|------|-----|------|-------------|
| Tenant | User | 1:N | Tenant has many users |
| Tenant | Repository | 1:N | Tenant has many repositories |
| Repository | AnalysisJob | 1:N | Repo can be analyzed multiple times |
| Repository | ExtractedCall | 1:N | Repo contains many API calls |
| ExtractedCall | InferredDependency | 1:1 | Each call gets one inference |

## 📝 Table Details

### tenants
**Purpose**: Multi-tenant organizations

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique tenant identifier |
| name | VARCHAR(255) | NOT NULL | Organization name |
| api_key | VARCHAR(64) | UNIQUE, NOT NULL | API authentication key |
| rate_limit_rpm | INTEGER | DEFAULT 60 | API rate limit (requests/minute) |
| max_repositories | INTEGER | DEFAULT 10 | Max repos tenant can create |
| is_active | BOOLEAN | DEFAULT TRUE | Account status |
| created_at | TIMESTAMP | NOT NULL | Account creation time |
| updated_at | TIMESTAMP | NOT NULL | Last modification time |

**Indexes**:
- `idx_tenants_api_key` on (api_key)

---

### users
**Purpose**: Individual users within tenants

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique user identifier |
| tenant_id | UUID | FOREIGN KEY, NOT NULL | References tenants(id) |
| email | VARCHAR(255) | UNIQUE, NOT NULL | Login email |
| hashed_password | VARCHAR(255) | NOT NULL | bcrypt hash |
| full_name | VARCHAR(255) | | Display name |
| is_active | BOOLEAN | DEFAULT TRUE | Account enabled |
| is_admin | BOOLEAN | DEFAULT FALSE | Tenant admin privileges |
| created_at | TIMESTAMP | NOT NULL | User creation time |
| updated_at | TIMESTAMP | NOT NULL | Last modification time |

**Indexes**:
- `idx_users_tenant_id` on (tenant_id)
- `idx_users_email` on (email)

---

### repositories
**Purpose**: Git repositories to analyze

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique repo identifier |
| tenant_id | UUID | FOREIGN KEY, NOT NULL | References tenants(id) |
| url | VARCHAR(512) | NOT NULL | Git repository URL |
| name | VARCHAR(255) | | Extracted repo name |
| branch | VARCHAR(100) | DEFAULT 'main' | Git branch to analyze |
| status | ENUM | NOT NULL | PENDING, CLONING, ANALYZING, COMPLETED, FAILED |
| error_message | TEXT | | Error details if failed |
| clone_path | VARCHAR(512) | | Local filesystem path |
| commit_hash | VARCHAR(40) | | Git SHA analyzed |
| file_count | INTEGER | | Number of Python files |
| created_at | TIMESTAMP | NOT NULL | Repo submission time |
| updated_at | TIMESTAMP | NOT NULL | Last status update |

**Indexes**:
- `idx_repositories_tenant_id` on (tenant_id)
- `idx_repositories_status` on (status)

---

### analysis_jobs
**Purpose**: Track background analysis progress

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique job identifier |
| repository_id | UUID | FOREIGN KEY, NOT NULL | References repositories(id) |
| status | ENUM | NOT NULL | QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED |
| progress | FLOAT | DEFAULT 0.0 | Percentage complete (0-100) |
| started_at | TIMESTAMP | | When Celery started processing |
| completed_at | TIMESTAMP | | When job finished |
| error_message | TEXT | | Error details if failed |
| result_summary | JSONB | | JSON summary of results |
| created_at | TIMESTAMP | NOT NULL | Job creation time |
| updated_at | TIMESTAMP | NOT NULL | Last progress update |

**Indexes**:
- `idx_jobs_repository_id` on (repository_id)
- `idx_jobs_status` on (status)

**Example result_summary**:
```json
{
  "services_found": 5,
  "api_calls_extracted": 23,
  "dependencies_inferred": 18,
  "neo4j_nodes_created": 5,
  "neo4j_edges_created": 18,
  "duration_seconds": 45.3
}
```

---

### extracted_calls
**Purpose**: HTTP API calls found in code

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique call identifier |
| repository_id | UUID | FOREIGN KEY, NOT NULL | References repositories(id) |
| service_name | VARCHAR(255) | | Caller service (from directory) |
| method | VARCHAR(10) | NOT NULL | HTTP method (GET, POST, etc.) |
| url | TEXT | NOT NULL | Full URL being called |
| file_path | VARCHAR(512) | NOT NULL | Source file path |
| line_number | INTEGER | NOT NULL | Line number in source |
| created_at | TIMESTAMP | NOT NULL | Extraction time |
| updated_at | TIMESTAMP | NOT NULL | Last modification |

**Indexes**:
- `idx_extracted_calls_repository_id` on (repository_id)
- `idx_extracted_calls_url` on (url)

**Example row**:
```
service_name: "service_a"
method:       "post"
url:          "http://payment-gateway.internal/api/charge"
file_path:    "service_a/api/orders.py"
line_number:  42
```

---

### inferred_dependencies
**Purpose**: LLM-inferred service names

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Unique dependency identifier |
| extracted_call_id | UUID | FOREIGN KEY, UNIQUE, NOT NULL | References extracted_calls(id) |
| caller_service | VARCHAR(255) | NOT NULL | Service making the call |
| callee_service | VARCHAR(255) | NOT NULL | Service being called (LLM inferred) |
| confidence | FLOAT | | LLM confidence score (0.0-1.0) |
| llm_model | VARCHAR(100) | | Which LLM was used |
| llm_response | TEXT | | Raw LLM response |
| created_at | TIMESTAMP | NOT NULL | Inference time |
| updated_at | TIMESTAMP | NOT NULL | Last modification |

**Indexes**:
- `idx_inferred_deps_extracted_call_id` on (extracted_call_id)
- `idx_inferred_deps_caller` on (caller_service)
- `idx_inferred_deps_callee` on (callee_service)

**Example row**:
```
caller_service: "service_a"
callee_service: "payment_gateway"  # ← LLM figured this out!
confidence:     0.95
llm_model:      "gemma2:latest"
llm_response:   "Based on the URL pattern, this is the payment_gateway service"
```

---

## 🔍 Common Queries

### Get all repositories for a tenant
```sql
SELECT * FROM repositories 
WHERE tenant_id = 'tenant-uuid'
ORDER BY created_at DESC;
```

### Get analysis job status
```sql
SELECT 
    r.name AS repo_name,
    j.status,
    j.progress,
    j.created_at,
    j.completed_at
FROM analysis_jobs j
JOIN repositories r ON j.repository_id = r.id
WHERE j.id = 'job-uuid';
```

### Get all dependencies for a repository
```sql
SELECT 
    id.caller_service,
    id.callee_service,
    ec.method,
    ec.url,
    id.confidence
FROM inferred_dependencies id
JOIN extracted_calls ec ON id.extracted_call_id = ec.id
WHERE ec.repository_id = 'repo-uuid'
ORDER BY id.caller_service, id.callee_service;
```

### Find services with most outgoing dependencies
```sql
SELECT 
    caller_service,
    COUNT(DISTINCT callee_service) as dependency_count
FROM inferred_dependencies id
JOIN extracted_calls ec ON id.extracted_call_id = ec.id
WHERE ec.repository_id = 'repo-uuid'
GROUP BY caller_service
ORDER BY dependency_count DESC;
```

---

## 🎯 Data Flow Example

**Scenario**: Analyze `github.com/acme/microservices-app`

1. **User submits repository**
   ```sql
   INSERT INTO repositories (tenant_id, url, status)
   VALUES ('tenant-123', 'github.com/acme/microservices-app', 'PENDING');
   ```

2. **Job created**
   ```sql
   INSERT INTO analysis_jobs (repository_id, status, progress)
   VALUES ('repo-456', 'QUEUED', 0.0);
   ```

3. **Celery worker extracts calls**
   ```sql
   INSERT INTO extracted_calls (repository_id, service_name, method, url, file_path, line_number)
   VALUES 
     ('repo-456', 'order_service', 'post', 'http://payment/charge', 'orders/api.py', 42),
     ('repo-456', 'order_service', 'get', 'http://inventory/check', 'orders/api.py', 55);
   ```

4. **LLM infers service names**
   ```sql
   INSERT INTO inferred_dependencies (extracted_call_id, caller_service, callee_service, confidence)
   VALUES 
     ('call-789', 'order_service', 'payment_service', 0.95),
     ('call-790', 'order_service', 'inventory_service', 0.92);
   ```

5. **Job completes**
   ```sql
   UPDATE analysis_jobs 
   SET status = 'COMPLETED', progress = 100.0, completed_at = NOW()
   WHERE id = 'job-789';
   ```

---
