import json
import time
from typing import Annotated, Any, Dict, List, Optional, Union

from sqlalchemy import JSON, Column, Float, Integer, String, create_engine, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

# Use a global engine and SessionLocal to ensure the :memory: database
# persists for the entire duration of the process.
# check_same_thread=False is required for SQLite when used in async/multithreaded environments.
engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class DocumentStore(Base):
    """
    Internal ORM model for storing arbitrary JSON data partitioned by namespace.
    """

    __tablename__ = "document_store"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # This should act as a "named table" akin to a topic string for an agent to query.
    namespace = Column(String, index=True)
    # This should be a metadata blob that the agent can set and query.
    data = Column(JSON)
    timestamp = Column(Float, default=time.time)


# Initialize schema immediately
Base.metadata.create_all(engine)

DatabaseOperationResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), the 'id' of the created/updated record, "
    "and a 'message' describing the outcome or an 'error' string if it failed.",
]

DatabaseQueryResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'results' (dictionaries), "
    "and a 'count' of the items found.",
]


def database_save(
    table: Annotated[
        str,
        "The name of the collection or topic to save to (e.g., 'results', 'learned_regex', 'metadata').",
    ],
    data: Annotated[Dict[str, Any], "The dictionary of data to store. Must be JSON serializable."],
) -> DatabaseOperationResult:
    """
    Saves a JSON document to a specified 'table' (namespace).

    Use this tool to persist information that needs to be remembered across
    multiple steps in a plan or to cache expensive results (like a parsed figured of merit).
    If the 'data' dictionary contains an 'id' key that matches an existing record
    in the same table, that record will be updated.

    Args:
        table: The virtual table/category name.
        data: The key-value pairs to store.

    Returns:
        A result dictionary indicating if the save was successful and the record ID.
    """
    try:
        session = SessionLocal()
        record_id = data.get("id")

        if record_id:
            # Attempt to update existing
            existing = (
                session.query(DocumentStore)
                .filter(DocumentStore.namespace == table, DocumentStore.id == record_id)
                .first()
            )
            if existing:
                existing.data = data
                existing.timestamp = time.time()
                session.commit()
                return {
                    "success": True,
                    "id": existing.id,
                    "message": f"Updated existing record {existing.id} in table '{table}'.",
                }

        # Create new entry
        new_entry = DocumentStore(namespace=table, data=data, timestamp=time.time())
        session.add(new_entry)
        session.commit()
        generated_id = new_entry.id
        session.close()

        return {
            "success": True,
            "id": generated_id,
            "message": f"Successfully saved new record to table '{table}'.",
        }
    except Exception as e:
        return {"success": False, "id": None, "error": f"Database save error: {str(e)}"}


def database_get(
    table: Annotated[str, "The name of the collection/table where the record is stored."],
    record_id: Annotated[int, "The unique integer ID of the record to retrieve."],
) -> DatabaseQueryResult:
    """
    Retrieves a single record by its unique ID from a specific table.

    Use this when you know the exact ID of a piece of information you stored previously.

    Args:
        table: The virtual table/category name.
        record_id: The integer primary key.

    Returns:
        A dictionary containing the 'success' status and a list with the single result
        if found. The result will include an 'id' field.
    """
    try:
        session = SessionLocal()
        record = (
            session.query(DocumentStore)
            .filter(DocumentStore.namespace == table, DocumentStore.id == record_id)
            .first()
        )
        session.close()

        if record:
            res = record.data
            res["id"] = record.id
            return {"success": True, "results": [res], "count": 1}

        return {
            "success": False,
            "results": [],
            "count": 0,
            "error": f"Record {record_id} not found.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def database_query(
    table: Annotated[str, "The name of the collection/table to query."],
    query_key: Annotated[
        Optional[str], "Optional: A specific key within the stored JSON to filter by."
    ] = None,
    query_value: Annotated[
        Optional[Any], "Optional: The value that the query_key must match."
    ] = None,
    limit: Annotated[int, "The maximum number of results to return."] = 10,
) -> DatabaseQueryResult:
    """
    Performs a search for records within a specified table, optionally filtering by a key-value pair.

    Use this tool to find information when you don't know the exact ID. For example,
    you can search the 'results' table where 'metric_name' equals 'lammps_performance'.
    If no query_key is provided, it returns the most recent records in that table.

    Args:
        table: The virtual table/category name to search.
        query_key: A top-level key inside the JSON document to match against.
        query_value: The value expected at query_key.
        limit: Max results (default 10).

    Returns:
        A dictionary with 'success' status, a list of matching 'results', and the 'count'.
    """
    try:
        session = SessionLocal()
        base_query = session.query(DocumentStore).filter(DocumentStore.namespace == table)

        if query_key and query_value is not None:
            base_query = base_query.filter(DocumentStore.data[query_key].astext == str(query_value))

        # Order by most recent first
        records = base_query.order_by(DocumentStore.timestamp.desc()).limit(limit).all()

        results = []
        for r in records:
            item = r.data
            item["id"] = r.id
            results.append(item)

        session.close()
        return {"success": True, "results": results, "count": len(results)}

    except Exception as e:
        return {"success": False, "error": f"Database query failed: {str(e)}"}
