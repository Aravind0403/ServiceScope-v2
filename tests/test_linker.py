import os
import tempfile
import yaml
from app.analysis.linker import extract_host, CrossLayerLinker

def test_extract_host():
    assert extract_host("http://paymentservice:50051/charge") == "paymentservice"
    assert extract_host("paymentservice:50051") == "paymentservice"
    assert extract_host("paymentservice.default.svc.cluster.local:50051") == "paymentservice"
    assert extract_host("http://localhost:8080") == "localhost"
    assert extract_host("shippingservice") == "shippingservice"

def test_cross_layer_linker_resolves_dynamic():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock values.yaml and templates directory for a Helm chart
        chart_dir = os.path.join(tmpdir, "onlineboutique")
        os.makedirs(os.path.join(chart_dir, "templates"))
        
        with open(os.path.join(chart_dir, "Chart.yaml"), "w") as f:
            yaml.dump({"apiVersion": "v2", "name": "onlineboutique", "version": "1.0"}, f)
            
        with open(os.path.join(chart_dir, "values.yaml"), "w") as f:
            yaml.dump({
                "checkoutService": {"name": "checkoutservice"},
                "paymentService": {"name": "paymentservice"},
                "shippingService": {"name": "shippingservice"}
            }, f)
            
        template_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.checkoutService.name }}
spec:
  template:
    spec:
      containers:
      - name: server
        env:
        - name: PAYMENT_SERVICE_ADDR
          value: "{{ .Values.paymentService.name }}:50051"
        - name: SHIPPING_SERVICE_ADDR
          value: "{{ .Values.shippingService.name }}:50051"
"""
        with open(os.path.join(chart_dir, "templates", "checkoutservice.yaml"), "w") as f:
            f.write(template_content)

        known_services = ["checkoutservice", "paymentservice", "shippingservice"]
        linker = CrossLayerLinker(tmpdir, known_services)
        
        # Test dynamic environment variable resolution
        res1 = linker.resolve_call("checkoutservice", "<dynamic:PAYMENT_SERVICE_ADDR>")
        assert res1 is not None
        assert res1[0] == "paymentservice"
        assert res1[1] == 1.0
        
        res2 = linker.resolve_call("checkoutservice", "<dynamic:SHIPPING_SERVICE_ADDR>")
        assert res2 is not None
        assert res2[0] == "shippingservice"
        assert res2[1] == 1.0
        
        # Test static URL resolution
        res3 = linker.resolve_call("checkoutservice", "http://paymentservice:50051")
        assert res3 is not None
        assert res3[0] == "paymentservice"
        assert res3[1] == 1.0
        
        # Test unresolved
        res_unresolved = linker.resolve_call("checkoutservice", "<dynamic:UNKNOWN_VAR>")
        assert res_unresolved is None
        
        res_external = linker.resolve_call("checkoutservice", "http://api.stripe.com/v1")
        assert res_external is None
