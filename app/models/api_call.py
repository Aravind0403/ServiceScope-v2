"""
Extracted Call Model

Stores HTTP API calls found during AST analysis.

Example:
    File: service_a/payment.py
    Line 42: requests.post("http://payment-gateway/api/charge", ...)

    Creates:
    ExtractedCall(
        repository_id=repo.id,
        service_name="service_a",
        method="post",
        url="http://payment-gateway/api/charge",
        file_path="service_a/payment.py",
        line_number=42
    )
"""

from sqlalchemy import Column, String, Integer, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base, UUIDMixin, TimestampMixin


class ExtractedCall(Base, UUIDMixin, TimestampMixin):
    """
    HTTP API call extracted from source code.

    This is the RAW data before LLM inference.
    We know:
    - WHAT: HTTP method (GET, POST, etc.)
    - WHERE: URL being called
    - WHO: Which service is making the call
    - LOCATION: File and line number

    We DON'T know yet:
    - Target service name (comes from LLM inference)
    """
    __tablename__ = "extracted_calls"

    # === Foreign Key ===
    repository_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Which repository this call was found in"
    )

    # === Call Details ===
    service_name = Column(
        String(255),
        index=True,
        comment="Caller service name (from directory/package name)"
    )
    # Example: "service_a", "payment_service", "api_gateway"

    method = Column(
        String(10),
        nullable=False,
        comment="HTTP method (GET, POST, PUT, DELETE, PATCH)"
    )

    url = Column(
        Text,
        nullable=False,
        index=True,  # For searching: "Which services call this URL?"
        comment="Full URL being called"
    )
    # Examples:
    # - "http://payment-gateway.internal/api/charge"
    # - "https://api.stripe.com/v1/charges"
    # - "http://localhost:5001/api/pay"

    # === Source Location ===
    file_path = Column(
        String(512),
        nullable=False,
        comment="Relative path to source file"
    )
    # Example: "service_a/handlers/payment.py"

    line_number = Column(
        Integer,
        nullable=False,
        comment="Line number in source file"
    )

    # === Relationships ===
    repository = relationship("Repository", back_populates="api_calls")

    # One-to-one: Each extracted call gets ONE inferred dependency
    inferred_dependency = relationship(
        "InferredDependency",
        back_populates="extracted_call",
        uselist=False,  # Not a list, just a single object
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ExtractedCall {self.method.upper()} {self.url}>"

    @property
    def source_location(self) -> str:
        """Human-readable source location"""
        return f"{self.file_path}:{self.line_number}"

    @property
    def is_external(self) -> bool:
        """Check if this is an external API call (not internal microservice)"""
        external_domains = [
            "stripe.com",
            "github.com",
            "googleapis.com",
            "amazonaws.com",
            "twilio.com",
            "sendgrid.com"
        ]
        return any(domain in self.url.lower() for domain in external_domains)

    @property
    def is_local(self) -> bool:
        """Check if this is a localhost/development URL"""
        return "localhost" in self.url or "127.0.0.1" in self.url

# Example: How extraction works
#
# Source Code:
# ```python
# # service_a/payment.py (line 42)
# import requests
#
# def charge_customer(amount):
#     response = requests.post(
#         "http://payment-gateway.internal/api/charge",
#         json={"amount": amount}
#     )
#     return response.json()
# ```
#
# AST Analysis extracts:
# ExtractedCall(
#     repository_id=repo_id,
#     service_name="service_a",      # From directory structure
#     method="post",                  # From requests.post
#     url="http://payment-gateway.internal/api/charge",  # From first arg
#     file_path="service_a/payment.py",
#     line_number=42
# )
#
# Then LLM inference creates:
# InferredDependency(
#     extracted_call_id=call.id,
#     caller_service="service_a",
#     callee_service="payment_gateway",  # ← LLM inferred this!
#     confidence=0.95
# )