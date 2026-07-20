from ntc_shared import LogLevel, RuntimeEnvironment


def test_runtime_enums_have_stable_wire_values() -> None:
    assert RuntimeEnvironment.PRODUCTION == "production"
    assert LogLevel.WARNING == "warning"
