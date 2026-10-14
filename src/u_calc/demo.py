from .calculator import calculate_climate_scenarios, calculate_heat_loss
from .catalog import CLIMATES, WINDOWS
from .models import Airflow, Boundary, Building, Layer, OpaqueSurface, Opening, SurfaceKind
from .report import format_report


def main() -> None:
    climate = CLIMATES["tashkent"]
    building = Building(
        indoor_temperature_c=24,
        outdoor_temperature_c=climate.outdoor_temperature("design"),
        volume_m3=240,
        heated_area_m2=80,
        length_m=10,
        width_m=8,
        height_m=3,
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
        openings=(
            Opening(
                "Окна",
                12,
                WINDOWS["double"].u_value,
                value_status="passport_user_input",
                source_note="Демонстрационный паспортный U",
            ),
        ),
        airflow=Airflow(
            mechanical_m3_h=80,
            natural_m3_h=40,
            infiltration_m3_h=30,
            heat_recovery_efficiency=0.75,
        ),
        safety_factor=1.15,
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
