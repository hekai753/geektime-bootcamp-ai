"""Unit tests for resilience and observability integration (AC3/AC4).

Verifies that the rate limiter, metrics collector, and tracing context are
actually enforced inside the request flow instead of being dormant modules.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from pg_mcp.config.settings import ResilienceConfig, ValidationConfig
from pg_mcp.models.query import QueryRequest, ResultValidationResult, ReturnType
from pg_mcp.observability.metrics import MetricsCollector
from pg_mcp.resilience.rate_limiter import MultiRateLimiter
from pg_mcp.services.orchestrator import QueryOrchestrator


def _sample(name: str, **labels: str) -> float | None:
    """Read a Prometheus sample value from the default registry."""
    return REGISTRY.get_sample_value(name, labels)


@pytest.fixture
def metrics() -> MetricsCollector:
    """Fresh (reset) singleton metrics collector."""
    collector = MetricsCollector()
    collector.reset_all_metrics()
    return collector


def _build_pipeline_orchestrator(metrics: MetricsCollector) -> QueryOrchestrator:
    """Build an orchestrator whose pipeline mocks produce a successful result path."""
    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT 1")

    validator = MagicMock()
    validator.validate_or_raise = MagicMock(return_value=None)

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=([{"id": 1}], 1))

    result_validator = MagicMock()
    result_validator.validate = AsyncMock(
        return_value=ResultValidationResult(
            confidence=95,
            explanation="ok",
            is_acceptable=True,
        )
    )

    schema_cache = MagicMock()
    schema_cache.get = MagicMock(return_value=MagicMock(tables=[]))

    return QueryOrchestrator(
        sql_generator=generator,
        sql_validator=validator,
        sql_executor=executor,
        result_validator=result_validator,
        schema_cache=schema_cache,
        pools={"db1": MagicMock()},
        resilience_config=ResilienceConfig(),
        validation_config=ValidationConfig(),
        rate_limiter=MultiRateLimiter(query_limit=2, llm_limit=2),
        metrics=metrics,
    )


@pytest.fixture
def pipeline_orchestrator(metrics: MetricsCollector) -> QueryOrchestrator:
    """Orchestrator with mocked successful pipeline, shared via fixture."""
    return _build_pipeline_orchestrator(metrics)


@pytest.mark.asyncio
async def test_rate_limited_request_returns_rate_limit_error(
    metrics: MetricsCollector,
) -> None:
    """A request that cannot obtain a limiter slot is rejected with rate_limit_exceeded."""
    orchestrator = _build_pipeline_orchestrator(metrics)
    # Exhaust ALL query limiter slots before issuing the request.
    limiter = orchestrator.rate_limiter
    assert limiter is not None
    for _ in range(limiter.query_limiter.max_concurrent):
        assert await limiter.query_limiter.acquire()

    response = await orchestrator.execute_query(
        QueryRequest(question="how many users?", database="db1")
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_successful_request_increments_query_metric(
    pipeline_orchestrator: QueryOrchestrator,
) -> None:
    """A successful query is counted in pg_mcp_query_requests_total{status=success}."""
    before = _sample("pg_mcp_query_requests_total", status="success", database="db1") or 0.0

    response = await pipeline_orchestrator.execute_query(
        QueryRequest(question="how many users?", database="db1")
    )

    assert response.success is True
    after = _sample("pg_mcp_query_requests_total", status="success", database="db1") or 0.0
    assert after == pytest.approx(before + 1)


@pytest.mark.asyncio
async def test_llm_call_metric_increments_on_generation(
    pipeline_orchestrator: QueryOrchestrator,
) -> None:
    """Each SQL generation increments pg_mcp_llm_calls_total{operation=sql_generation}."""
    before = _sample("pg_mcp_llm_calls_total", operation="sql_generation") or 0.0

    await pipeline_orchestrator.execute_query(
        QueryRequest(question="how many users?", database="db1")
    )

    after = _sample("pg_mcp_llm_calls_total", operation="sql_generation") or 0.0
    assert after == pytest.approx(before + 1)


@pytest.mark.asyncio
async def test_db_duration_observed_on_execution(
    pipeline_orchestrator: QueryOrchestrator,
) -> None:
    """Executing SQL records a db query duration observation."""
    before = _sample("pg_mcp_db_query_duration_seconds_count") or 0.0

    await pipeline_orchestrator.execute_query(
        QueryRequest(question="how many users?", database="db1")
    )

    after = _sample("pg_mcp_db_query_duration_seconds_count") or 0.0
    assert after == pytest.approx(before + 1)


@pytest.mark.asyncio
async def test_rate_limiter_released_after_request(
    pipeline_orchestrator: QueryOrchestrator,
) -> None:
    """The query limiter slot is released so subsequent requests still pass."""
    for _ in range(3):
        response = await pipeline_orchestrator.execute_query(
            QueryRequest(question="how many users?", database="db1")
        )
        assert response.success is True


@pytest.mark.asyncio
async def test_sql_only_mode_records_metric(
    pipeline_orchestrator: QueryOrchestrator,
) -> None:
    """return_type=sql skips execution but still counts the request."""
    before = _sample("pg_mcp_query_requests_total", status="success", database="db1") or 0.0

    response = await pipeline_orchestrator.execute_query(
        QueryRequest(question="show tables", database="db1", return_type=ReturnType.SQL)
    )

    assert response.success is True
    assert response.data is None
    after = _sample("pg_mcp_query_requests_total", status="success", database="db1") or 0.0
    assert after == pytest.approx(before + 1)
