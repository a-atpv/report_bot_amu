import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from mysql.connector import connect
from mysql.connector import pooling
from mysql.connector.connection import MySQLConnection


# Load environment variables (safe if already loaded elsewhere)
load_dotenv()


class MySQLTicketService:
    """
    Service for retrieving data from a MySQL tickets table.

    Expects the following environment variables:
      - DB_HOST
      - DB_PORT
      - DB_USER
      - DB_PASSWORD
      - DB_NAME
      - TICKETS_TABLE_NAME (optional, defaults to DB_TICKETS)
    """

    def __init__(self, pool_name: str = "tickets_pool", pool_size: int = 5) -> None:
        self.db_host: str = os.getenv("DB_HOST", "localhost")
        self.db_port: int = int(os.getenv("DB_PORT", "3306"))
        self.db_user: str = os.getenv("DB_USER", "root")
        self.db_password: str = os.getenv("DB_PASSWORD", "")
        self.db_name: str = os.getenv("DB_NAME", "")
        self.tickets_table: str = os.getenv("TICKETS_TABLE_NAME", "DB_TICKETS")

        # Basic validation to avoid unsafe identifiers
        if not self._is_safe_identifier(self.tickets_table):
            raise ValueError(
                "TICKETS_TABLE_NAME contains invalid characters. Allowed: letters, digits, underscore."
            )

        if not self.db_name:
            raise ValueError("DB_NAME is not set in environment variables")

        self.pool: pooling.MySQLConnectionPool = pooling.MySQLConnectionPool(
            pool_name=pool_name,
            pool_size=pool_size,
            pool_reset_session=True,
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_password,
            database=self.db_name,
        )

    def _get_connection(self) -> MySQLConnection:
        return self.pool.get_connection()

    def fetch_all_tickets(
        self, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = (
            f"SELECT * FROM {self.tickets_table} ORDER BY id DESC LIMIT %s OFFSET %s"
        )
        params: Tuple[int, int] = (limit, offset)
        return self._execute_query(query, params)

    def fetch_ticket_by_id(self, ticket_id: Any) -> Optional[Dict[str, Any]]:
        query = f"SELECT * FROM {self.tickets_table} WHERE id = %s"
        rows = self._execute_query(query, (ticket_id,))
        return rows[0] if rows else None

    def fetch_tickets_by_status(
        self, status: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = f"SELECT * FROM {self.tickets_table} WHERE status = %s ORDER BY id DESC LIMIT %s OFFSET %s"
        params: Tuple[Any, int, int] = (status, limit, offset)
        return self._execute_query(query, params)

    def _execute_query(
        self, query: str, params: Tuple[Any, ...]
    ) -> List[Dict[str, Any]]:
        connection = self._get_connection()
        try:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return rows or []
        finally:
            connection.close()

    @staticmethod
    def _is_safe_identifier(identifier: str) -> bool:
        return identifier.replace("_", "").isalnum()


# Convenience factory
def get_ticket_service() -> MySQLTicketService:
    return MySQLTicketService()
