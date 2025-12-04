"""
Text-to-SQL Evaluation Metrics.

Two orthogonal metrics:
1. valid_sql: Is the generated SQL syntactically valid?
2. execution_accuracy: Does it return the same results as the gold SQL?
"""

import sqlite3
from typing import Any, Dict


def _clean_sql(sql: str) -> str:
    """Remove markdown code blocks if present."""
    sql = sql.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        sql = "\n".join(lines).strip()
    return sql


def valid_sql(output: Any, expected: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if the generated SQL is syntactically valid.

    Uses sqlglot to parse the SQL. Returns 1.0 if valid, 0.0 if not.

    Args:
        output: The generated SQL query
        expected: The ground truth SQL (not used)
        input_data: Dict containing 'schema' (not used for validation)

    Returns:
        Dict with score (0.0 or 1.0) and metadata
    """
    if output is None or str(output).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "Empty output", "is_valid": False}
        }

    output = _clean_sql(str(output))

    try:
        import sqlglot
        sqlglot.parse(output)
        return {
            "score": 1.0,
            "metadata": {"is_valid": True}
        }
    except ImportError:
        # Fallback: basic syntax check
        sql_upper = output.upper()
        has_select = "SELECT" in sql_upper
        has_from = "FROM" in sql_upper
        is_valid = has_select and has_from
        return {
            "score": 1.0 if is_valid else 0.0,
            "metadata": {
                "is_valid": is_valid,
                "note": "sqlglot not installed, using basic check"
            }
        }
    except Exception as e:
        return {
            "score": 0.0,
            "metadata": {
                "is_valid": False,
                "error": str(e)
            }
        }


def execution_accuracy(output: Any, expected: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if the generated SQL produces the same results as the expected SQL.

    Creates an in-memory SQLite database from the schema, executes both queries,
    and compares the results.

    Args:
        output: The generated SQL query
        expected: The ground truth SQL query
        input_data: Dict containing 'schema' with CREATE TABLE statements

    Returns:
        Dict with score (0.0 or 1.0) and metadata
    """
    if output is None or str(output).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "Empty output", "execution_match": False}
        }

    if expected is None or str(expected).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "Empty expected SQL", "execution_match": False}
        }

    output = _clean_sql(str(output))
    expected = str(expected).strip()

    # Extract schema from input_data
    schema = None
    if isinstance(input_data, dict):
        schema = input_data.get("schema")

    if schema is None or str(schema).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "No schema found in input_data", "execution_match": False}
        }

    schema = str(schema)

    try:
        # Create in-memory database and set up schema
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()

        # Execute schema (CREATE TABLE statements)
        for stmt in schema.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cursor.execute(stmt)
                except sqlite3.Error:
                    pass

        conn.commit()

        # Execute expected SQL
        try:
            cursor.execute(expected)
            expected_results = set(cursor.fetchall())
        except sqlite3.Error as e:
            conn.close()
            return {
                "score": 0.0,
                "metadata": {
                    "error": f"Expected SQL failed: {e}",
                    "execution_match": False
                }
            }

        # Execute generated SQL
        try:
            cursor.execute(output)
            output_results = set(cursor.fetchall())
        except sqlite3.Error as e:
            conn.close()
            return {
                "score": 0.0,
                "metadata": {
                    "error": f"Generated SQL failed: {e}",
                    "execution_match": False
                }
            }

        conn.close()

        # Compare results
        match = expected_results == output_results

        return {
            "score": 1.0 if match else 0.0,
            "metadata": {
                "execution_match": match,
                "expected_rows": len(expected_results),
                "output_rows": len(output_results),
            }
        }

    except Exception as e:
        return {
            "score": 0.0,
            "metadata": {
                "error": str(e),
                "execution_match": False
            }
        }
