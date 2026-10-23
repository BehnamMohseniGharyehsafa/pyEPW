"""Run after installing the project with: python -m pip install ."""

from pyEPW import EPW


def main() -> None:
    weather = EPW("Dublin, Ireland", "2024", ".epw", output_dir="output")
    print(weather.path)
    print(f"{weather.hours:,} hours; {weather.location}")
    print(weather.to_csv())
    print(weather.to_txt())
    print(weather.to_analysis_csv())
    print(weather.quality_report())


if __name__ == "__main__":
    main()
