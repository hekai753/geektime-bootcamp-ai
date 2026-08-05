"""Data export API endpoints (CSV / JSON file download)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlmodel import Session, select

from app.database import get_session
from app.models.database import DatabaseConnection
from app.models.query import QuerySource
from app.models.schemas import QueryInput
from app.services.exporter import to_csv, to_json
from app.services.query_wrapper import execute_query_with_service
from app.services.sql_validator import SqlValidationError

router = APIRouter(prefix="/api/v1/dbs", tags=["exports"])


@router.post("/{name}/export")
async def export_query_result(
    name: str,
    input_data: QueryInput,
    session: Session = Depends(get_session),
    format: Literal["csv", "json"] = "csv",
) -> Response:
    """Execute a read-only SQL query and return the result as a downloadable file.

    Reuses ``execute_query_with_service`` so the export inherits the same
    SELECT-only validation, query history recording, and automatic LIMIT as
    the manual query endpoint.
    """
    # Resolve connection (404 if missing) — mirrors queries.execute_sql_query
    connection = session.exec(
        select(DatabaseConnection).where(DatabaseConnection.name == name)
    ).first()
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Database connection '{name}' not found",
        )

    # Execute (auto SELECT-only validation, history, LIMIT) — reuse wrapper
    try:
        result = await execute_query_with_service(
            session,
            name,
            connection.db_type,
            connection.url,
            input_data.sql,
            QuerySource.EXPORT,
        )
    except SqlValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query execution failed: {str(e)}",
        )

    # Format payload
    if format == "json":
        content = to_json(result)
        media_type = "application/json; charset=utf-8"
    else:
        content = to_csv(result)
        media_type = "text/csv; charset=utf-8"

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    filename = f"{name}_{timestamp}.{format}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
