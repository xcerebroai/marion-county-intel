"""
Framework-shared scraper adapters.

This package holds generic, county-agnostic scraping primitives that
multiple county adapters can reuse. Examples:

    _arcgis_featureserver.py — generic ArcGIS REST FeatureServer /
        MapServer pull pattern (pagination, retries, attribute
        extraction). Used by any county whose distress source is
        ArcGIS-hosted (foreclosure-notice maps, GIS parcel layers,
        etc.).

County-specific adapter modules live at the repo-root `scrapers/`
directory, NOT here, so the framework knowledge base stays
county-agnostic.
"""
