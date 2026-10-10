"""Build the Lovelace dashboard for one wall display. Pure Python.

The layout rules live in layout.py (see its docstring); this package turns a
GeneratorInput into views of one grid section each. Pages exist only when
enabled and they have something to show; nav order is fixed (Home, Climate,
Media, Scenes). Entities that don't fit end on a "more" view reached through
a "+N more" slot; it is not in the pill. With Home as the only page there is
no pill and Home gains the footer band.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..const import NAV, PAGE_CLIMATE, PAGE_HOME, PAGE_MEDIA, PAGE_MORE, PAGE_SCENES
from ..layout import (
    card_column_px,
    compute_grid,
    fill_block,
    pack,
    tile_max_columns,
    tile_max_rows,
)
from ..models import DashboardBudget, EntityInfo, GeneratorInput, Grid, ViewBudget
from . import cards
from .cards import Card
from .climate import climate_plan
from .home import home_plan
from .labels import label
from .media import media_plan
from .nav import nav_footer
from .room import active_pages, primary
from .scenes import scene_plan

_LOGGER = logging.getLogger(__name__)

Plan = Callable[[GeneratorInput, Grid], tuple[list[Card], list[EntityInfo]]]


def _home(data: GeneratorInput, grid: Grid) -> tuple[list[Card], list[EntityInfo]]:
    plan = home_plan(data, grid)
    return plan.cards, plan.overflow


PAGE_PLANS: dict[str, Plan] = {
    PAGE_HOME: _home,
    PAGE_CLIMATE: climate_plan,
    PAGE_MEDIA: media_plan,
    PAGE_SCENES: scene_plan,
}


__all__ = ["PAGE_PLANS", "build_dashboard", "dashboard_budget", "fit_to_rows"]


def fit_to_rows(card_list: list[Card], grid: Grid, page: str = "") -> list[Card]:
    """Drop cards that CSS auto-placement would put below the row budget."""
    spans = [(cards.card_columns(c, grid.card_columns), cards.card_rows(c)) for c in card_list]
    placements = pack(spans, grid.card_columns, grid.rows)
    kept = [card for card, place in zip(card_list, placements, strict=True) if place is not None]
    if len(kept) < len(card_list):
        _LOGGER.debug(
            "Page %s: %d of %d cards do not fit in %d rows and were left out",
            page,
            len(card_list) - len(kept),
            len(card_list),
            grid.rows,
        )
    return kept


def _entity_index(data: GeneratorInput) -> dict[str, EntityInfo]:
    index: dict[str, EntityInfo] = {}
    for group in (
        data.area_entities,
        data.climates,
        data.media_players,
        data.scenes,
        data.house_scenes,
        data.persons,
        data.house_secure,
        data.leave_home,
    ):
        for entity in group:
            index.setdefault(entity.entity_id, entity)
    return index


def dedupe_names(card_list: list[Card], data: GeneratorInput) -> list[Card]:
    """Names that clash within a view get their area back ("Speaker" -> "Kitchen Speaker")."""
    index = _entity_index(data)
    seen: dict[str, int] = {}
    for card in card_list:
        if card.get("type") == "tile" and card.get("entity") in index and card.get("name"):
            seen[card["name"]] = seen.get(card["name"], 0) + 1
    result = []
    for card in card_list:
        name = card.get("name")
        entity = index.get(card.get("entity", ""))
        if card.get("type") == "tile" and entity and name and seen.get(name, 0) > 1:
            area = data.area_names.get(entity.area_id or "")
            if area and name == entity.name:
                card = {**card, "name": f"{area} {name}"}
        result.append(card)
    return result


def _more_cards(data: GeneratorInput, grid: Grid, overflow: list[EntityInfo]) -> list[Card]:
    """The More view: everything that did not fit elsewhere, with the Home tile
    rules (capped size, then growth), filling the page."""
    profile = data.display.profile
    column_px = card_column_px(profile)
    fill = fill_block(
        len(overflow),
        grid.card_columns,
        grid.rows,
        column_px,
        max_columns=tile_max_columns(profile),
        max_rows=tile_max_rows(profile),
    )
    if fill.count < len(overflow):
        _LOGGER.debug("More view: %d entities do not fit", len(overflow) - fill.count)
    features = profile.orientation != "square"
    shown = overflow[: fill.count]
    last_start = (fill.lines - 1) * fill.per_row
    placed = []
    for index, entity in enumerate(shown):
        rows = fill.rows + (fill.last_extra if index >= last_start else 0)
        card = cards.entity_card(entity, rows, features=features)
        placed.append(cards.sized(card, fill.columns, rows))
    return cards.widen_block(placed, grid.card_columns)


def _view(
    page: str,
    section_cards: list[Card],
    grid: Grid,
    footer: dict[str, Any] | None,
    language: str,
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "type": "sections",
        "title": label(language, page),
        "path": page,
        "icon": NAV[page][1],
        "max_columns": grid.section_columns,
        "top_margin": False,
    }
    if footer is not None:
        view["footer"] = footer
    view["sections"] = [
        {"type": "grid", "column_span": grid.section_columns, "cards": section_cards}
    ]
    return view


def _build_pages(
    data: GeneratorInput, footer: bool
) -> tuple[Grid, list[tuple[str, list[Card]]], list[EntityInfo]]:
    grid = compute_grid(data.display.profile, footer=footer)
    pages: list[tuple[str, list[Card]]] = []
    overflow: list[EntityInfo] = []
    for page in (PAGE_HOME, *active_pages(data)):
        page_cards, left_over = PAGE_PLANS[page](data, grid)
        page_cards = fit_to_rows(dedupe_names(page_cards, data), grid, page)
        if page != PAGE_HOME and not page_cards:
            continue
        pages.append((page, page_cards))
        overflow += left_over
    return grid, pages, overflow


def build_dashboard(data: GeneratorInput) -> dict[str, Any]:
    """Full dashboard config: {"title", "views"}."""
    profile, language = data.display.profile, data.language
    grid, pages, overflow = _build_pages(data, footer=True)
    if len(pages) < 2:
        grid, pages, overflow = _build_pages(data, footer=False)
    nav_pages = [page for page, _ in pages]
    has_footer = len(nav_pages) >= 2
    live: dict[str, str] = {
        page: entity.entity_id
        for page in (PAGE_CLIMATE, PAGE_MEDIA)
        if page in nav_pages and (entity := primary(data, page)) is not None
    }

    def footer() -> dict[str, Any]:
        return nav_footer(
            nav_pages, profile, language, live, data.display.overrides.temperature_entity
        )

    views = [
        _view(page, page_cards, grid, footer() if has_footer else None, language)
        for page, page_cards in pages
    ]

    reachable = any(
        card.get("tap_action", {}).get("navigation_path") == PAGE_MORE
        for _, page_cards in pages
        for card in page_cards
    )
    if overflow and reachable:
        more_grid = compute_grid(profile, footer=True)
        unique = list({e.entity_id: e for e in overflow}.values())
        more = fit_to_rows(dedupe_names(_more_cards(data, more_grid, unique), data), more_grid)
        views.append(_view(PAGE_MORE, more, more_grid, footer(), language))
    elif overflow:
        _LOGGER.debug("%d entities do not fit and have no More slot", len(overflow))
    return {"title": data.display.name, "views": views}


def dashboard_budget(
    data: GeneratorInput, dashboard: dict[str, Any] | None = None
) -> DashboardBudget:
    """Row budget for walldisplay.js (websocket `list`), from the built dashboard.

    `rows`/`footer` describe Home; `views` has the same per view path, because
    the More view has the pill even when Home has none.
    """
    dashboard = dashboard if dashboard is not None else build_dashboard(data)
    profile = data.display.profile
    views: dict[str, ViewBudget] = {}
    for view in dashboard["views"]:
        footer = "footer" in view
        views[view["path"]] = {"rows": compute_grid(profile, footer=footer).rows, "footer": footer}
    home = views.get(PAGE_HOME) or ViewBudget(rows=compute_grid(profile).rows, footer=True)
    return {"rows": home["rows"], "footer": home["footer"], "views": views}
