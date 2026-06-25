import os
import tempfile
import yaml
from app.extraction.manifest_parser import (
    render_helm_template,
    parse_yaml_file,
    extract_env_from_manifests,
)

def test_render_helm_template():
    context = {
        "Values": {
            "image": {
                "repository": "test-repo",
                "tag": "v1"
            },
            "service": {
                "name": "test-svc",
                "port": 8080
            },
            "database": {
                "type": "postgres",
                "connection": "db-conn"
            }
        },
        "Chart": {
            "AppVersion": "latest"
        },
        "Release": {
            "Namespace": "prod"
        }
    }

    template = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.service.name }}
  namespace: {{ .Release.Namespace }}
spec:
  containers:
  - name: app
    image: {{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
    env:
    {{- if eq .Values.database.type "spanner" }}
    - name: SPANNER_URL
      value: spanner-val
    {{- else }}
    - name: DB_URL
      value: {{ .Values.database.connection | quote }}
    {{- end }}
    - name: PORT
      value: "{{ .Values.service.port }}"
"""

    rendered = render_helm_template(template, context)
    assert "name: test-svc" in rendered
    assert "namespace: prod" in rendered
    assert "image: test-repo:v1" in rendered
    assert "SPANNER_URL" not in rendered or "#" in rendered.split("SPANNER_URL")[0].splitlines()[-1]
    assert "name: DB_URL" in rendered
    assert 'value: "db-conn"' in rendered or "value: db-conn" in rendered
    assert 'value: "8080"' in rendered

def test_extract_env_from_manifests():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock Helm chart structure
        chart_dir = os.path.join(tmpdir, "my-chart")
        os.makedirs(os.path.join(chart_dir, "templates"))
        
        # Write Chart.yaml
        with open(os.path.join(chart_dir, "Chart.yaml"), "w") as f:
            yaml.dump({"apiVersion": "v2", "name": "my-chart", "version": "1.0"}, f)
            
        # Write values.yaml
        with open(os.path.join(chart_dir, "values.yaml"), "w") as f:
            yaml.dump({
                "service": {"name": "hello-service"},
                "config": {"host": "hello-host"}
            }, f)
            
        # Write a template file
        template_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.service.name }}
spec:
  template:
    spec:
      containers:
      - name: hello
        env:
        - name: HELLO_HOST
          value: {{ .Values.config.host }}
        - name: STATIC_VAL
          value: "static"
"""
        with open(os.path.join(chart_dir, "templates", "hello.yaml"), "w") as f:
            f.write(template_content)

        # Write a mock configmap and raw deployment
        raw_manifest_content = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-cm
data:
  DB_PORT: "5432"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: raw-service
spec:
  template:
    spec:
      containers:
      - name: raw
        env:
        - name: DB_PORT
          valueFrom:
            configMapKeyRef:
              name: app-cm
              key: DB_PORT
        - name: DIRECT_VAL
          value: "direct"
"""
        with open(os.path.join(tmpdir, "raw-manifest.yaml"), "w") as f:
            f.write(raw_manifest_content)

        # Parse environments
        env_map = extract_env_from_manifests(tmpdir)
        
        assert "hello-service" in env_map
        assert env_map["hello-service"]["HELLO_HOST"] == "hello-host"
        assert env_map["hello-service"]["STATIC_VAL"] == "static"
        
        assert "raw-service" in env_map
        assert env_map["raw-service"]["DB_PORT"] == "5432"
        assert env_map["raw-service"]["DIRECT_VAL"] == "direct"

def test_real_microservices_demo_manifests():
    # Verify parsing on the actual microservices-demo checkout
    demo_dir = "benchmark/repos/microservices-demo"
    if os.path.exists(demo_dir):
        env_map = extract_env_from_manifests(demo_dir)
        
        # Test checkoutservice env vars
        assert "checkoutservice" in env_map
        checkout_env = env_map["checkoutservice"]
        assert checkout_env.get("PORT") == "5050"
        assert checkout_env.get("PRODUCT_CATALOG_SERVICE_ADDR") == "productcatalogservice:3550"
        assert checkout_env.get("PAYMENT_SERVICE_ADDR") == "paymentservice:50051"
        assert checkout_env.get("CART_SERVICE_ADDR") == "cartservice:7070"
        
        # Test cartservice env vars
        assert "cartservice" in env_map
        cart_env = env_map["cartservice"]
        assert cart_env.get("REDIS_ADDR") == "redis-cart:6379"
