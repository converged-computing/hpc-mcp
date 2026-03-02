import os
import time
from typing import Annotated, Any, Dict, List, Optional, Union

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    text,
)

# Stores { database_name: { "engine": engine, "metadata": metadata } }
DATABASES: Dict[str, Dict[str, Any]] = {}

# Type Mapping for dynamic schema creation
TYPE_MAP = {
    "integer": Integer,
    "string": String(255),
    "text": Text,
    "float": Float,
    "json": JSON,
    "boolean": Integer,  # SQLite handles boolean as integers (0 or 1)
}

DatabaseOperationResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool) and a 'message' or 'error' string.",
]

DatabaseQueryResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'results' (as dictionaries), and a 'count'.",
]


def _get_resources(name: str):
    if name not in DATABASES:
        raise ValueError(f"Database '{name}' not found. You must call 'database_create' first.")
    return DATABASES[name]


def database_create(
    name: Annotated[str, "A unique name to identify this database instance."],
    schema: Annotated[
        Dict[str, Dict[str, str]],
        "A dictionary defining the relational structure. Keys are table names. "
        "Values are dictionaries mapping column names to types ('integer', 'string', 'text', 'float', 'json'). "
        "Example: {'benchmarks': {'nodes': 'integer', 'score': 'float'}}",
    ],
    db_type: Annotated[
        str, "The storage backend: 'memory' (ephemeral) or 'file' (persistent)."
    ] = "memory",
    path: Annotated[
        Optional[str], "The filesystem path for the .db file. Required if db_type is 'file'."
    ] = None,
) -> DatabaseOperationResult:
    """
    Creates a new, isolated relational database with a custom schema defined by the agent.

    This is the primary setup tool. The agent defines the tables and columns.
    An 'id' column (autoincrementing integer primary key) is automatically added
    to every table for record identification.

    Args:
        name: The name used to reference this database in future calls.
        schema: A map of table names to their column definitions and data types.
        db_type: Either 'memory' for temporary process-local storage or 'file' for disk persistence.
        path: The file path used if db_type is 'file'.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the database and all tables were created.
            - 'message' (str): A summary of the created tables.
            - 'error' (str, optional): Details if the schema definition was invalid.
    """
    try:
        if name in DATABASES:
            return {"success": False, "error": f"Database '{name}' already exists."}

        connection_url = (
            "sqlite:///:memory:" if db_type == "memory" else f"sqlite:///{os.path.abspath(path)}"
        )

        # Connect_args needed for SQLite multi-threading in async MCP
        engine = create_engine(
            connection_url, echo=False, connect_args={"check_same_thread": False}
        )
        metadata = MetaData()

        # Iterate through the schema and build SQLAlchemy Table objects
        for table_name, columns in schema.items():
            cols = [Column("id", Integer, primary_key=True, autoincrement=True)]
            for col_name, col_type in columns.items():
                # Default to String if type is unrecognized
                sa_type = TYPE_MAP.get(col_type.lower(), String(255))
                cols.append(Column(col_name, sa_type))

            # Register table in metadata
            Table(table_name, metadata, *cols)

        # Physically create all tables in the SQLite instance
        metadata.create_all(engine)

        DATABASES[name] = {"engine": engine, "metadata": metadata}
        return {
            "success": True,
            "message": f"Database '{name}' created with tables: {list(schema.keys())}",
        }

    except Exception as e:
        return {"success": False, "error": f"Database creation failed: {str(e)}"}


def database_insert(
    database: Annotated[str, "The name of the target database."],
    table: Annotated[str, "The table name where the row will be inserted."],
    data: Annotated[
        Dict[str, Any], "The data to insert. Keys must match the columns defined in the schema."
    ],
) -> DatabaseOperationResult:
    """
    Inserts a single row of data into a specific table within a managed database.

    Use this tool to record experimental results, metrics, or state transitions
    following the schema established during database creation.

    Args:
        database: The name of the database instance.
        table: The specific table name.
        data: Key-value pairs representing the row data.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the row was successfully inserted.
            - 'message' (str): Confirmation of insertion and the generated primary key ID.
            - 'error' (str, optional): Details if the table is missing or data format is wrong.
    """
    try:
        res = _get_resources(database)
        engine, metadata = res["engine"], res["metadata"]

        target_table = metadata.tables.get(table)
        if target_table is None:
            return {
                "success": False,
                "error": f"Table '{table}' not found in database '{database}'.",
            }

        with engine.begin() as conn:
            result = conn.execute(insert(target_table).values(**data))
            new_id = result.inserted_primary_key[0]

        return {"success": True, "message": f"Inserted row into {table} with ID {new_id}."}
    except Exception as e:
        return {"success": False, "error": f"Insert failed: {str(e)}"}


def database_query(
    database: Annotated[str, "The name of the database instance to query."],
    sql: Annotated[str, "A raw SQL SELECT statement."],
    params: Annotated[
        Optional[Dict[str, Any]], "Parameters for the SQL query to prevent injection."
    ] = None,
) -> DatabaseQueryResult:
    """
    Executes a raw SQL SELECT query against a managed database.

    The agent has full read access to the tables it created. This allows for
    complex analytics, such as computing averages, filtering by performance
    metrics, or joining data.

    Args:
        database: The database instance name.
        sql: The SQL query string (e.g., 'SELECT * FROM results WHERE nodes > 2').
        params: Optional mapping of parameters for the query.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the query was valid and executed.
            - 'results' (list[dict]): A list of rows, where each row is a dictionary of columns.
            - 'count' (int): The number of rows returned.
            - 'error' (str, optional): SQL syntax error details.
    """
    try:
        res = _get_resources(database)
        engine = res["engine"]

        with engine.connect() as conn:
            # We use text() to wrap the raw SQL for SQLAlchemy
            result = conn.execute(text(sql), params or {})
            # Map the Row objects to standard dictionaries
            rows = [dict(row._mapping) for row in result]

        return {"success": True, "results": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": f"SQL Query failed: {str(e)}"}


def database_list_schemas(
    database: Annotated[str, "The database name to inspect."],
) -> DatabaseOperationResult:
    """
    Provides a technical summary of the tables and columns within a specific database.

    Use this tool to 're-discover' the schema if the context history is lost
    or to verify the structure before performing inserts or queries.

    Args:
        database: The name of the database instance.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the database was found.
            - 'message' (str): A stringified dictionary representation of the schema.
    """
    try:
        res = _get_resources(database)
        metadata = res["metadata"]

        details = {}
        for name, table in metadata.tables.items():
            details[name] = {c.name: str(c.type) for c in table.columns}

        return {"success": True, "message": str(details)}
    except Exception as e:
        return {"success": False, "error": str(e)}
