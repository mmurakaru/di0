"""di0's adapter conformance kit: per-port contract checks any adapter author runs."""

from di0.testing.conformance import (
    CheckOutcome,
    check_authoring,
    check_capabilities,
    check_combine_port,
    check_dialect_port,
    check_execution_port,
    check_refuses_before_side_effect,
    check_schema_port,
    check_validation_port,
    load_adapter,
    run_cli_checks,
)

__all__ = [
    "CheckOutcome",
    "check_authoring",
    "check_capabilities",
    "check_combine_port",
    "check_dialect_port",
    "check_execution_port",
    "check_refuses_before_side_effect",
    "check_schema_port",
    "check_validation_port",
    "load_adapter",
    "run_cli_checks",
]
