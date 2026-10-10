"""Media page for the room's primary player.

Square and landscape screens up to 960 px wide: one vertical tile with
title/artist, playback buttons and a volume slider (calm in the dark;
media-control without artwork fills itself with the accent colour). Tall
(portrait) and large screens: the native media-control card, whose artwork
earns the space, with numeric rows that fill the page (``rows: "auto"`` keeps
its natural ~161 px) and a one-row "Volume" tile below. Other players follow
as small tiles; if they don't fit, the last slot shows "+N more".
"""

from __future__ import annotations

from ..const import PAGE_MEDIA
from ..layout import card_column_px
from ..models import EntityInfo, GeneratorInput, Grid
from . import cards
from .cards import Card
from .climate import below_split
from .labels import label
from .room import page_entities

VOLUME = {"type": "media-player-volume-slider"}
MIN_CONTROL_ROWS = 3
TILE_PLAYER_MAX_WIDTH = 960  # up to here a tile replaces media-control (design review #7)
PLAYER_TILE_ROWS = 4  # vertical tile: icon + name/state + playback row + volume row


def media_control(entity: EntityInfo) -> Card:
    return {"type": "media-control", "entity": entity.entity_id, "name": entity.name}


def volume_tile(entity: EntityInfo, language: str) -> Card:
    return cards.tile(
        entity.entity_id,
        label(language, "volume"),
        icon="mdi:volume-high",
        hide_state=True,
        features=[dict(VOLUME)],
        features_position="inline",
    )


def player_tile(entity: EntityInfo, vertical: bool = False) -> Card:
    card = cards.tile(entity.entity_id, entity.name)
    if vertical:
        card["vertical"] = True
    return card


def player_card(entity: EntityInfo) -> Card:
    """Calm media tile for screens up to TILE_PLAYER_MAX_WIDTH: title/artist,
    playback buttons and volume; replaces media-control and the volume tile."""
    return cards.tile(
        entity.entity_id,
        entity.name,
        state_content=["media_title", "media_artist"],
        features=[{"type": "media-player-playback"}, dict(VOLUME)],
        features_position="bottom",
        vertical=True,
    )


def media_plan(data: GeneratorInput, grid: Grid) -> tuple[list[Card], list[EntityInfo]]:
    """Cards of the media section and the players that did not fit (for More)."""
    players = page_entities(data, PAGE_MEDIA)
    if not players or grid.rows <= 0:
        return [], []
    primary, others = players[0], players[1:]
    profile = data.display.profile
    total, rows = grid.card_columns, grid.rows
    column_px = card_column_px(profile)

    if profile.width <= TILE_PLAYER_MAX_WIDTH and profile.orientation != "portrait":
        # One tile with playback and volume, then the other players.
        main_rows, fill = below_split(len(others), total, rows, column_px, PLAYER_TILE_ROWS)
        if others and not fill.count:
            more_columns = total // 3
            return [
                cards.sized(player_card(primary), total - more_columns, rows),
                cards.sized(
                    cards.more_shortcut(data.language, len(others), vertical=rows >= 2),
                    more_columns,
                    rows,
                ),
            ], others
        result = [cards.sized(player_card(primary), total, main_rows)]
    else:
        if rows <= MIN_CONTROL_ROWS:
            # Too short for the full card: the volume tile alone (one row).
            return [cards.sized(volume_tile(primary, data.language), total, 1)], others
        control_rows, fill = below_split(len(others), total, rows - 1, column_px, MIN_CONTROL_ROWS)
        result = [cards.sized(media_control(primary), total, control_rows)]
        if others and not fill.count:
            more_columns = total // 3
            result.append(cards.sized(volume_tile(primary, data.language), total - more_columns, 1))
            result.append(
                cards.sized(cards.more_shortcut(data.language, len(others)), more_columns, 1)
            )
            return result, others
        result.append(cards.sized(volume_tile(primary, data.language), total, 1))

    shown = others[: fill.count]
    placed = [cards.sized(player_tile(e, fill.rows >= 2), fill.columns, fill.rows) for e in shown]
    placed, overflow = cards.overflow_slot(placed, others[fill.count :], shown, data.language)
    return result + placed, overflow
