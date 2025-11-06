"""
Data models for database entities.

This module defines the structure of objects representing database tables:
- Ticket: Represents a ticket/request from the tickets table
- User: Represents a user from the users table
- Building: Represents a building from the buildings table
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Ticket:
    """Represents a ticket/request entry."""

    id: int
    user_id: Optional[int]
    specialist_id: Optional[int]
    building_id: Optional[int]
    description: Optional[str]
    cabinet: Optional[str]
    status: str
    department_id: int

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        """Create a Ticket instance from a dictionary (e.g., from database query)."""
        return cls(
            id=data.get("id"),
            user_id=data.get("user_id"),
            specialist_id=data.get("specialist_id"),
            building_id=data.get("building_id"),
            description=data.get("description"),
            cabinet=data.get("cabinet"),
            status=data.get("status"),
            department_id=data.get("department_id"),
        )


@dataclass
class User:
    """Represents a user entry."""

    id: int
    firstname: Optional[str]
    lastname: Optional[str]
    phone: Optional[str]

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create a User instance from a dictionary (e.g., from database query)."""
        return cls(
            id=data.get("id"),
            firstname=data.get("firstname"),
            lastname=data.get("lastname"),
            phone=data.get("phone"),
        )

    @property
    def full_name(self) -> str:
        """Returns the full name of the user, or 'ID {id}' if name is not available."""
        name = f"{self.firstname or ''} {self.lastname or ''}".strip()
        return name if name else f"ID {self.id}"


@dataclass
class Building:
    """Represents a building entry."""

    id: int
    name: Optional[str]
    description: Optional[str]

    @classmethod
    def from_dict(cls, data: dict) -> "Building":
        """Create a Building instance from a dictionary (e.g., from database query)."""
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            description=data.get("description"),
        )

    @property
    def display_name(self) -> str:
        """Returns the description if available, otherwise name, otherwise id as string."""
        return self.description or self.name or str(self.id)
