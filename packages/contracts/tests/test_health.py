import pytest
from ntc_contracts import LivenessResponse
from pydantic import ValidationError


def test_liveness_contract_preserves_vietnamese_unicode() -> None:
    response = LivenessResponse(service="dịch-vụ-rag", version="0.1.0")

    assert response.model_dump(mode="json") == {
        "status": "ok",
        "service": "dịch-vụ-rag",
        "version": "0.1.0",
    }


def test_liveness_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LivenessResponse(service="ntc-api", version="0.1.0", unexpected=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(("field", "value"), [("service", "   "), ("version", "\t")])
def test_liveness_contract_rejects_blank_strings(field: str, value: str) -> None:
    payload = {"service": "ntc-api", "version": "0.1.0", field: value}

    with pytest.raises(ValidationError):
        LivenessResponse(**payload)  # type: ignore[arg-type]
