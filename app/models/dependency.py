"""
Inferred Dependency Model

Stores the results of LLM inference on service names.

Flow:
1. ExtractedCall found: "http://payment-gateway.internal/api/charge"
2. LLM analyzes URL
3. LLM response: "This is likely the 'payment_gateway' service"
4. Store as InferredDependency with confidence score

Example:
    dependency = InferredDependency(
        extracted_call_id=call.id,
        caller_service="service_a",
        callee_service="payment_gateway",
        confidence=0.95,
        llm_model="gemma2:latest"
    )
"""

from sqlalchemy import Column, String, Float, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base, UUIDMixin, TimestampMixin


class InferredDependency(Base, UUIDMixin, TimestampMixin):
    """
    LLM-inferred service dependency.

    This is the INTERPRETED data after LLM analysis.

    Relationship:
    ExtractedCall (1) ←→ (1) InferredDependency

    One extracted call = one inferred dependency
    """
    __tablename__ = "inferred_dependencies"

    # === Foreign Key (One-to-One) ===
    extracted_call_id = Column(
        UUID(as_uuid=True),
        ForeignKey("extracted_calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # Enforces one-to-one relationship
        index=True,
        comment="Which extracted call this inference is for"
    )

    # === Dependency Info ===
    caller_service = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Service making the call (from extraction)"
    )

    callee_service = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Service being called (LLM inferred)"
    )
    # This is what the LLM figured out!
    # Input:  "http://payment-gateway.internal/api/charge"
    # Output: "payment_gateway" or "payment_service"

    # === LLM Metadata ===
    confidence = Column(
        Float,
        comment="Confidence score from LLM (0.0 to 1.0)"
    )
    # Not all LLMs provide this, but useful when available

    llm_model = Column(
        String(100),
        comment="Which LLM model was used"
    )
    # Examples: "gemma2:latest", "gpt-4", "claude-3-sonnet"

    llm_response = Column(
        Text,
        comment="Raw LLM response (for debugging)"
    )
    # Store the full response in case we need to re-parse it

    # === Relationships ===
    extracted_call = relationship(
        "ExtractedCall",
        back_populates="inferred_dependency"
    )

    def __repr__(self):
        return f"<InferredDependency {self.caller_service} → {self.callee_service}>"

    @property
    def is_high_confidence(self) -> bool:
        """Check if inference is high confidence (>80%)"""
        return self.confidence and self.confidence > 0.8

    @property
    def is_low_confidence(self) -> bool:
        """Check if inference is low confidence (<50%)"""
        return self.confidence and self.confidence < 0.5

    def to_neo4j_edge(self) -> dict:
        """
        Convert to Neo4j relationship format.

        Returns:
            Dict suitable for Neo4j MERGE query

        Example output:
            {
                "caller": "service_a",
                "callee": "payment_gateway",
                "method": "POST",
                "url": "http://payment-gateway/api/charge",
                "confidence": 0.95,
                "file": "service_a/payment.py",
                "line": 42
            }
        """
        return {
            "caller": self.caller_service,
            "callee": self.callee_service,
            "method": self.extracted_call.method.upper(),
            "url": self.extracted_call.url,
            "confidence": self.confidence,
            "file": self.extracted_call.file_path,
            "line": self.extracted_call.line_number
        }

# Example: Complete Flow
#
# Step 1: Code Analysis
# ----------------------
# File: service_a/api/orders.py
# ```python
# def create_order(user_id, items):
#     # Line 15: Call payment service
#     payment_response = requests.post(
#         "http://payment-svc.prod.internal:8080/api/v1/charge",
#         json={"user": user_id, "amount": total}
#     )
# ```
#
# Step 2: AST Extraction
# ----------------------
# extracted_call = ExtractedCall(
#     service_name="service_a",
#     method="post",
#     url="http://payment-svc.prod.internal:8080/api/v1/charge",
#     file_path="service_a/api/orders.py",
#     line_number=15
# )
# db.add(extracted_call)
# db.commit()
#
# Step 3: LLM Inference
# ---------------------
# prompt = f"""
# Given this URL: {extracted_call.url}
# What is the service name?
# Only respond with the service name.
# """
#
# llm_response = ollama.generate(prompt=prompt)
# # Response: "payment_service" or "payment_svc"
#
# Step 4: Store Inference
# ------------------------
# inferred = InferredDependency(
#     extracted_call_id=extracted_call.id,
#     caller_service="service_a",
#     callee_service="payment_service",  # ← From LLM
#     confidence=0.92,
#     llm_model="gemma2:latest",
#     llm_response=llm_response
# )
# db.add(inferred)
# db.commit()
#
# Step 5: Load to Neo4j
# ---------------------
# cypher = """
# MERGE (caller:Service {name: $caller})
# MERGE (callee:Service {name: $callee})
# CREATE (caller)-[:CALLS {
#     method: $method,
#     url: $url,
#     confidence: $confidence
# }]->(callee)
# """
# neo4j.run(cypher, **inferred.to_neo4j_edge())