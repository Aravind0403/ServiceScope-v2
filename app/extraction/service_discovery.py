"""
Service Discovery Utility
==========================
Heuristically scans repository directories to detect the known list
of microservices/packages, ignoring common metadata/build folders.
"""

from pathlib import Path
from app.analysis.blast_radius import normalise

IGNORE_DIRS = {
    # Testing & docs
    'tests', 'test', 'docs', 'scripts', 'config', 'git', 'github', 'devcontainer',
    # Dependencies & caches
    'vendor', 'node_modules', 'pycache', 'migrations', 'venv',
    # Build & distribution
    'build', 'dist', 'release', 'bin',
    # Infrastructure, deployment & container config
    'kubernetes', 'helm', 'docker', 'k8s', 'manifests', 'deployments', 'deployment',
    'deploy', 'terraform', 'istiomanifests', 'kubernetesmanifests', 'kustomize',
    'helmchart', 'loadgenerator',
    # Databases & assets
    'db', 'database', 'sql', 'assets', 'static', 'templates',
    # API specs, protos, third-party
    'pb', 'proto', 'protos', 'thirdparty', 'tools', 'benchmark', 'examples',
    # Generic folders that are structural rather than services
    'src', 'cmd', 'pkg', 'internal', 'api'
}

def discover_services(repo_path: str, min_files: int = 1) -> list:
    """
    Scans the repository path for microservice folders.
    To support various structures:
    - Checks top-level folders (excluding ignore list).
    - Checks folders inside src/ (if present).
    - Checks folders inside cmd/ (if present).
    
    A folder qualifies as a service if it is a directory and contains
    at least `min_files` files (of any type) recursively.
    Service names are returned normalized and sorted.
    """
    repo_path = Path(repo_path)
    if not repo_path.exists() or not repo_path.is_dir():
        return []
        
    candidate_dirs = []
    
    def is_ignored(name: str) -> bool:
        if name.startswith('.'):
            return True
        clean_name = name.lower().replace("-", "").replace("_", "").replace(".", "")
        return clean_name in IGNORE_DIRS
    
    # 1. Scan top-level folders
    try:
        for entry in repo_path.iterdir():
            if entry.is_dir() and not is_ignored(entry.name):
                candidate_dirs.append(entry)
    except OSError:
        pass
        
    # 2. Scan src/ if it exists
    src_dir = repo_path / "src"
    if src_dir.is_dir():
        try:
            for entry in src_dir.iterdir():
                if entry.is_dir() and not is_ignored(entry.name):
                    candidate_dirs.append(entry)
        except OSError:
            pass
            
    # 3. Scan cmd/ if it exists
    cmd_dir = repo_path / "cmd"
    if cmd_dir.is_dir():
        try:
            for entry in cmd_dir.iterdir():
                if entry.is_dir() and not is_ignored(entry.name):
                    candidate_dirs.append(entry)
        except OSError:
            pass
            
    services = set()
    for directory in candidate_dirs:
        try:
            # Count any file recursively to support multi-language/polyglot service structures
            file_count = sum(1 for item in directory.rglob('*') if item.is_file())
            
            if file_count >= min_files:
                norm_name = normalise(directory.name)
                if norm_name:
                    services.add(norm_name)
        except OSError:
            pass
            
    return sorted(list(services))
