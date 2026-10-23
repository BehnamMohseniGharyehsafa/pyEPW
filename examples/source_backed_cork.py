"""Export Cork's actual year and inspect real source gaps."""

from pyEPW import EPW


def main() -> None:
    weather = EPW("Cork, Ireland", 2025, ".epw", output_dir="cork_2025")
    print(weather.path)
    print(weather.to_csv())
    print(weather.to_analysis_csv())
    print(weather.quality_report())
    print("Complete:", weather.is_complete)
    print("Missing hours by field:", weather.missing_fields)
    # Published METARs have minimal archive QC. To exclude this fallback, use
    # allow_metar_fallback=False. Missing source values are never fabricated.
    # require_complete=True rejects any remaining missing weather field before
    # writing. Cork 2025 does not meet that strict requirement.


if __name__ == "__main__":
    main()
