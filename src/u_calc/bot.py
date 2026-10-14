# ruff: noqa: F401
"""Telegram application facade.

Conversation handlers live in feature modules under :mod:`u_calc.handlers`.
Re-exports keep the established import surface for integrations while this
module remains the small console entry point.
"""

from .app import main, run
from .handlers.airflow import air_changes, heat_recovery
from .handlers.boundaries import (
    _advance_after_openings,
    _ask_adjacent_mode,
    ceiling_boundary,
    floor_boundary,
    ground_exterior_sides,
    ground_floor_construction,
    surface_adjacent_mode,
    surface_insulated,
    surface_insulation_material,
    surface_insulation_thickness,
    surface_material,
    surface_thickness,
)
from .handlers.climate import climate, profile_design, profile_design_source, scenario
from .handlers.result import _send_long_message, confirmation, safety_factor
from .handlers.survey import (
    Survey,
    _go_back,
    building_type,
    calculation_mode,
    dimensions,
    door_count,
    door_dimensions,
    door_method,
    door_type,
    indoor,
    insulated,
    insulation_material,
    insulation_thickness,
    object_name,
    router,
    start,
    thermal_bridges,
    wall_area,
    wall_material,
    wall_method,
    wall_thickness,
    window_count,
    window_dimensions,
    window_method,
    window_type,
)

__all__ = ["Survey", "main", "router", "run"]


if __name__ == "__main__":
    main()
