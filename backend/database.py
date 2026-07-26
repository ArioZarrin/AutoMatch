from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .config import DatabaseConfig
from .domain import VEHICLE_FIELDS, VehicleRecord


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
def _table_identifier(table_name: str) -> sql.Composed:
    parts = table_name.split(".")
    if len(parts) not in {1, 2} or any(not IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise ValueError(f"Invalid PostgreSQL table name: {table_name!r}")
    return sql.SQL(".").join(sql.Identifier(part) for part in parts)


def _connection_kwargs(config: DatabaseConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": config.effective_host,
        "port": config.port,
        "sslmode": config.ssl_mode,
        "connect_timeout": 5,
        "row_factory": dict_row,
    }
    if config.database:
        kwargs["dbname"] = config.database
    if config.username:
        kwargs["user"] = config.username
    if config.password:
        kwargs["password"] = config.password
    return kwargs


def connect(config: DatabaseConfig) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(**_connection_kwargs(config))


def test_connection(config: DatabaseConfig) -> dict[str, Any]:
    with connect(config) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database, current_user AS username")
            row = cursor.fetchone()
    return {
        "database": row["database"],
        "username": row["username"],
        "host": config.effective_host,
    }


def load_catalogue(
    config: DatabaseConfig,
) -> tuple[list[VehicleRecord], dict[str, dict[str, str]]]:
    vehicle_table = _table_identifier(config.vehicle_table)
    listing_table = _table_identifier(config.listing_table)
    query = sql.SQL(
        """
        SELECT
            vi.id,
            vi.make,
            vi.model,
            vi.badge,
            vi.transmission_type,
            vi.fuel_type,
            vi.drive_type,
            COUNT(li.vehicle_id)::bigint AS listing_count
        FROM {vehicle_table} AS vi
        LEFT JOIN {listing_table} AS li ON li.vehicle_id = vi.id
        GROUP BY
            vi.id,
            vi.make,
            vi.model,
            vi.badge,
            vi.transmission_type,
            vi.fuel_type,
            vi.drive_type
        """
    ).format(vehicle_table=vehicle_table, listing_table=listing_table)

    with connect(config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            aliases = _load_aliases(cursor, config.alias_table)

    records = [
        VehicleRecord(
            id=str(row["id"]),
            make=str(row["make"]),
            model=str(row["model"]),
            badge=str(row["badge"]),
            transmission_type=str(row["transmission_type"]),
            fuel_type=str(row["fuel_type"]),
            drive_type=str(row["drive_type"]),
            listing_count=int(row["listing_count"] or 0),
        )
        for row in rows
    ]
    return records, aliases


def _load_aliases(
    cursor: psycopg.Cursor[dict[str, Any]], alias_table: str | None
) -> dict[str, dict[str, str]]:
    aliases = {field: {} for field in VEHICLE_FIELDS}
    if not alias_table:
        return aliases

    query = sql.SQL(
        "SELECT field_name, alias, canonical_value FROM {alias_table}"
    ).format(alias_table=_table_identifier(alias_table))
    cursor.execute(query)
    for row in cursor.fetchall():
        field = str(row["field_name"]).strip()
        alias = str(row["alias"]).strip()
        canonical = str(row["canonical_value"]).strip()
        if field in aliases and alias and canonical:
            aliases[field][alias] = canonical
    return aliases
