"""Generate actual-year Maynooth weather and inspect field coverage."""

from pyEPW import EPW


def main() -> None:
    weather = EPW("Maynooth, Ireland", 2025, ".epw", output_dir="maynooth_2025")
    print(weather.path)
    print(weather.to_csv())
    print(weather.to_txt())
    print(weather.to_analysis_csv())
    print(weather.quality_report())
    # Keep each *.metadata.json: it identifies models, stations and real gaps.


if __name__ == "__main__":
    main()
