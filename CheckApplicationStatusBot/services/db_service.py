import os
from typing import Any, Dict, List, Tuple, Optional

from dotenv import load_dotenv
from mysql.connector import connect
from mysql.connector import pooling
from mysql.connector.connection import MySQLConnection

from models import Ticket, User, Building, Category, SubCategory

# taken - status for active tickets
# Load environment variables (safe if already loaded elsewhere)
load_dotenv()


class MySQLTicketService:

    def __init__(self, pool_name: str = "tickets_pool", pool_size: int = 5) -> None:
        self.db_host: str = os.getenv("DB_HOST", "localhost")
        self.db_port: int = int(os.getenv("DB_PORT", "3306"))
        self.db_user: str = os.getenv("DB_USER", "root")
        self.db_password: str = os.getenv("DB_PASSWORD", "")
        self.db_name: str = os.getenv("DB_NAME", "")
        self.tickets_table: str = os.getenv("TICKETS_TABLE_NAME", "DB_TICKETS")
        self.buildings_table: str = os.getenv("BUILDINGS_TABLE_NAME", "cat_building")
        self.users_table: str = os.getenv("USERS_TABLE_NAME", "users")
        self.categories_table: str = os.getenv(
            "CATEGORIES_TABLE_NAME", "helpdesk_categories"
        )
        self.subcategories_table: str = os.getenv(
            "SUBCATEGORIES_TABLE_NAME", "helpdesk_subcategories"
        )

        # Basic validation to avoid unsafe identifiers
        if not self._is_safe_identifier(self.tickets_table):
            raise ValueError(
                "TICKETS_TABLE_NAME contains invalid characters. Allowed: letters, digits, underscore."
            )
        if not self._is_safe_identifier(self.buildings_table):
            raise ValueError(
                "BUILDINGS_TABLE_NAME contains invalid characters. Allowed: letters, digits, underscore."
            )
        if not self._is_safe_identifier(self.categories_table):
            raise ValueError(
                "CATEGORIES_TABLE_NAME contains invalid characters. Allowed: letters, digits, underscore."
            )
        if not self._is_safe_identifier(self.subcategories_table):
            raise ValueError(
                "SUBCATEGORIES_TABLE_NAME contains invalid characters. Allowed: letters, digits, underscore."
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

    def fetch_building_descriptions(self) -> Dict[str, str]:
        """
        Return mapping of building id (as string) -> description from cat_building table.
        If description is NULL or empty, falls back to building name or id string.
        """
        query = f"SELECT id, description, name FROM {self.buildings_table}"
        rows = self._execute_query(query, tuple())
        id_to_desc: Dict[str, str] = {}
        for row in rows:
            bid = row.get("id")
            # Prefer description, then name, then id string
            desc = row.get("description")
            if bid is not None:
                id_to_desc[str(bid)] = str(desc) if desc is not None else str(bid)
        return id_to_desc

    def fetch_tickets_by_status(
        self,
        status: str = "new",
        department_id: int = 33,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        query = (
            f"SELECT * FROM {self.tickets_table} WHERE `status` = %s AND department_id = %s"
            " ORDER BY id DESC LIMIT %s OFFSET %s"
        )
        params: Tuple[Any, ...] = (status, department_id, limit, offset)
        rows = self._execute_query(query, params)
        return [Ticket.from_dict(row) for row in rows]

    def fetch_users_by_id(
        self,
        user_id: int,
    ) -> Optional[User]:
        query = f"SELECT * FROM {self.users_table} WHERE id = %s"
        params: Tuple[Any, ...] = (user_id,)
        rows = self._execute_query(query, params)
        return User.from_dict(rows[0]) if rows else None

    def fetch_users_by_ids(
        self,
        user_ids: List[int],
    ) -> Dict[int, User]:
        """
        Fetch multiple users by their IDs.
        Returns a dictionary mapping user_id -> User object.
        """
        if not user_ids:
            return {}
        # Create placeholders for IN clause
        placeholders = ",".join(["%s"] * len(user_ids))
        query = f"SELECT * FROM {self.users_table} WHERE id IN ({placeholders})"
        params: Tuple[Any, ...] = tuple(user_ids)
        rows = self._execute_query(query, params)
        # Return as dict mapping id -> User object
        return {
            row.get("id"): User.from_dict(row)
            for row in rows
            if row.get("id") is not None
        }

    def fetch_categories_by_department_id(self, department_id: int) -> List[Category]:
        query = f"SELECT * FROM {self.categories_table} WHERE department_id = %s"
        params: Tuple[Any, ...] = (department_id,)
        rows = self._execute_query(query, params)
        return [Category.from_dict(row) for row in rows]

    def fetch_subcategories_by_category_id(self, category_id: int) -> List[SubCategory]:
        query = f"SELECT * FROM {self.subcategories_table} WHERE category_id = %s"
        params: Tuple[Any, ...] = (category_id,)
        rows = self._execute_query(query, params)
        return [SubCategory.from_dict(row) for row in rows]

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
