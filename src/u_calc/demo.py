from dataclasses import replace

from .calculator import calculate_climate_scenarios, calculate_heat_loss
from .catalog import CLIMATES, WINDOWS
from .models import Boundary, Building, Layer, OpaqueSurface, Opening, SurfaceKind
from .report import format_report


def main() -> None:
    climate = replace(
        CLIMATES["tashkent"],
        design_c=-14,
        source_note="Демонстрационное значение -14 °C задано явно, не взято из каталога",
    )
    building = Building(
        indoor_temperature_c=24,
        outdoor_temperature_c=climate.outdoor_temperature("design"),
        volume_m3=240,
        heated_area_m2=80,
        opaque_surfaces=(
            OpaqueSurface(
                "Наружные стены",
                90,
                (Layer("brick_solid", 0.25), Layer("mineral_wool", 0.05)),
            ),
            OpaqueSurface(
                "Пол над подвалом",
                80,
                (Layer("concrete", 0.20),),
                Boundary.UNHEATED,
                kind=SurfaceKind.FLOOR,
            ),
            OpaqueSurface("Потолок", 80, (), Boundary.HEATED, kind=SurfaceKind.CEILING),
        ),
        openings=(Opening("Окна", 12, WINDOWS["double"].u_value),),
    )
    print(
        format_report(
            building,
            calculate_heat_loss(building),
            climate,
            scenario_results=calculate_climate_scenarios(building, climate),
        )
    )


if __name__ == "__main__":
    main()
