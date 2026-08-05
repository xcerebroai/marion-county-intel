"""
Translator registry — hybrid framework + county adapter pattern (v5.1.2-beta+).

The framework provides:
  - Generic protocol clients (ArcGIS REST, public-records search
    portals, court e-portals, CSV static lists, static HTML tables)
    in scaffold/scrapers/. These handle pagination, retries, error
    envelopes, and other protocol-level concerns county-agnostically.
  - This registry, which maps a string name to a translator implementation.

Counties provide:
  - A `translator` string in each source's config block, picking a
    registered translator name.
  - A `translator_config` dict per source, containing the county-specific
    schema mapping the chosen translator needs (layer IDs, field maps,
    doc-type synonyms, parcel ID prefixes, etc.).

The orchestrator (build_leads.py) reads county config, looks up the
named translator, calls translator.translate(raw_records, config) to
get (signals, parcels, per_signal_metadata).

Registered translators MUST:
  - Be county-agnostic. No county name, statute reference, or
    municipality list in the translator code.
  - Read all county-specific data from the `config` dict passed at
    call time.
  - Return signals + parcels + per_signal_metadata in the framework's
    canonical shape (see scaffold/pipeline/normalize.py).
  - Honor geography.sale_date_rule, geography.accepted_municipalities,
    geography.cross_county_policy, and sources.<id>.parcel_id_prefix
    from the county config when relevant.

If a county needs translator logic that doesn't fit a registered
translator, it can register a custom translator via county adapter
code in scrapers/. The registry supports late registration.

API:

    from scaffold.pipeline.translators import registry, register, lookup

    # Decorator pattern for built-in translators:
    @register("foreclosure_notices")
    def translate_foreclosure_notices(raw_records, county_config,
                                      source_config):
        ...
        return signals, parcels, per_signal_meta

    # Lookup:
    translator_fn = lookup("foreclosure_notices")
    signals, parcels, meta = translator_fn(raw_records, county_config,
                                            source_config)

The registry refuses to overwrite an existing name unless `force=True`
is passed. County adapters that need to override a built-in translator
must do so explicitly.

CONTRACT (v5.1.2-beta-r2+): Translators consume the framework-canonical
WRAPPED RAW RECORD shape declared in MASTER_PROMPT §4.32:

    {
        "raw_record_id": "<unique id>",
        "source_id": "<source id>",
        "source_url": "<url if applicable>",
        "source_fetched_at": "<ISO ts>",
        "raw_payload": {<normalized scraper-output fields>}
    }

Scrapers normalize source fields (lowercase, framework-canonical names)
BEFORE writing JSONL. Translators read normalized raw_payload, apply
source_config (parcel_id_prefix, layer_doc_type_map, field_map, etc.),
and emit framework signals. Translators MUST NOT contain portal-specific
code paths (no ArcGIS attribute names, no portal hostnames, no protocol
parsing). Portal protocol knowledge lives in scaffold/scrapers/ or in
county-side scrapers/.
"""

from __future__ import annotations
from typing import Callable, Any


# Internal registry. Module-level so import-time registration works.
_REGISTRY: dict[str, Callable] = {}


class TranslatorNotFound(KeyError):
    """Raised when lookup() asks for a name that wasn't registered."""


class TranslatorAlreadyRegistered(ValueError):
    """Raised when register() is called twice for the same name without force=True."""


def register(name: str, force: bool = False) -> Callable[[Callable], Callable]:
    """
    Decorator to register a translator function under a string name.

    Args:
        name: The string name counties use in their config. Must match
              an enum value in config/counties/_schema.json sources.<id>.translator.
        force: If True, overwrite any existing registration. Default False;
               framework built-ins should never need force=True.

    Returns:
        Decorator that registers the function and returns it unchanged.
    """
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY and not force:
            raise TranslatorAlreadyRegistered(
                f"Translator '{name}' is already registered. "
                f"Pass force=True to override."
            )
        _REGISTRY[name] = fn
        return fn
    return decorator


def lookup(name: str) -> Callable:
    """
    Find a registered translator by name. Raises TranslatorNotFound if missing.

    Args:
        name: Translator name from county config.

    Returns:
        The translator function.

    Raises:
        TranslatorNotFound: if no translator is registered under `name`.
    """
    if name not in _REGISTRY:
        available = sorted(_REGISTRY.keys())
        raise TranslatorNotFound(
            f"Translator '{name}' is not registered. "
            f"Available: {available}"
        )
    return _REGISTRY[name]


def registered_names() -> list[str]:
    """Return sorted list of currently registered translator names."""
    return sorted(_REGISTRY.keys())


def unregister(name: str) -> None:
    """Remove a registration. Used in tests."""
    _REGISTRY.pop(name, None)


def clear() -> None:
    """Clear all registrations. Used in tests."""
    _REGISTRY.clear()


# Import the built-in translators so their @register decorators run.
# Counties that need custom translators import their own modules
# (typically from scrapers/) at config-load time.
from scaffold.pipeline.translators import foreclosure_notices  # noqa: E402, F401
from scaffold.pipeline.translators import parcel_master  # noqa: E402, F401
from scaffold.pipeline.translators import csv_static_list  # noqa: E402, F401
