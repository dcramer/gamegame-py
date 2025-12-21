"""BoardGameGeek API service with caching, retry logic, and rate limiting."""

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.config import settings
from gamegame.models.bgg_game import BGGGame, is_cache_stale

logger = logging.getLogger(__name__)

T = TypeVar("T")

# BGG API configuration
BGG_API_BASE = "https://boardgamegeek.com/xmlapi2"
BGG_MIN_REQUEST_DELAY_MS = 5000  # 5 seconds between requests (BGG recommendation)
BGG_RATE_LIMIT_KEY = "bgg:ratelimit"
BGG_MAX_WAIT_MS = 30000  # Maximum wait time for rate limit
BGG_USER_AGENT = "GameGame/1.0 (https://github.com/gamegame; contact@example.com)"

# Retry configuration
DEFAULT_MAX_RETRIES = 2
DEFAULT_INITIAL_DELAY_MS = 3000
IMAGE_MAX_RETRIES = 3
IMAGE_INITIAL_DELAY_MS = 1000

# Shared httpx client headers
BGG_HEADERS = {"User-Agent": BGG_USER_AGENT}


@dataclass
class BGGGameInfo:
    """Game information from BoardGameGeek."""

    bgg_id: int
    name: str
    year: int | None
    image_url: str | None
    thumbnail_url: str | None
    description: str | None
    min_players: int | None
    max_players: int | None
    playing_time: int | None
    publishers: list[str] | None = None
    designers: list[str] | None = None
    categories: list[str] | None = None
    mechanics: list[str] | None = None


@dataclass
class BGGSearchResult:
    """Basic search result from BoardGameGeek."""

    bgg_id: int
    name: str
    year: int | None
    game_type: str  # boardgame, boardgameexpansion, etc.


class BGGRateLimiter:
    """Rate limiter for BGG API requests using Redis for distributed locking."""

    def __init__(self):
        self._redis = None
        self._last_request_time: float = 0
        self._fallback_mode = False
        self._local_lock = asyncio.Lock()  # Protect local rate limiter state

    async def _get_redis(self):
        """Get Redis connection, lazily initialized."""
        if self._redis is None:
            try:
                import redis.asyncio as redis

                self._redis = redis.from_url(settings.redis_url)
                # Test connection
                await self._redis.ping()
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for rate limiting: {e!r}")
                self._fallback_mode = True
                return None
        return self._redis

    async def close(self) -> None:
        """Close Redis connection if open."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def acquire(self) -> None:
        """Acquire rate limit slot, waiting if necessary."""
        redis_client = await self._get_redis()

        if redis_client is None or self._fallback_mode:
            # Fallback to in-memory rate limiting
            await self._acquire_local()
            return

        # Try distributed rate limiting with Redis
        start_time = asyncio.get_running_loop().time() * 1000
        while True:
            try:
                # Check if we can acquire the lock
                last_request = await redis_client.get(BGG_RATE_LIMIT_KEY)

                if last_request is None:
                    # No recent request, set lock and proceed
                    now_ms = int(datetime.now().timestamp() * 1000)
                    await redis_client.set(BGG_RATE_LIMIT_KEY, now_ms, ex=60)
                    return

                last_request_ms = int(last_request)
                now_ms = int(datetime.now().timestamp() * 1000)
                time_since_last = now_ms - last_request_ms

                if time_since_last >= BGG_MIN_REQUEST_DELAY_MS:
                    # Enough time has passed, set new lock and proceed
                    await redis_client.set(BGG_RATE_LIMIT_KEY, now_ms, ex=60)
                    return

                # Check if we've waited too long
                elapsed = asyncio.get_running_loop().time() * 1000 - start_time
                if elapsed > BGG_MAX_WAIT_MS:
                    logger.warning("Rate limit wait timeout, falling back to local rate limiting")
                    self._fallback_mode = True
                    await self._acquire_local()
                    return

                # Wait a bit and retry
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.warning(f"Redis rate limit error, falling back to local: {e!r}")
                self._fallback_mode = True
                await self._acquire_local()
                return

    async def _acquire_local(self) -> None:
        """Fallback in-memory rate limiting with lock to prevent race conditions."""
        async with self._local_lock:
            now = asyncio.get_running_loop().time()
            time_since_last = (now - self._last_request_time) * 1000

            if time_since_last < BGG_MIN_REQUEST_DELAY_MS:
                wait_time = (BGG_MIN_REQUEST_DELAY_MS - time_since_last) / 1000
                await asyncio.sleep(wait_time)

            self._last_request_time = asyncio.get_running_loop().time()


# Global rate limiter instance
_rate_limiter = BGGRateLimiter()


async def close_rate_limiter() -> None:
    """Close the global rate limiter's Redis connection."""
    await _rate_limiter.close()


async def with_retry(
    fn,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay_ms: int = DEFAULT_INITIAL_DELAY_MS,
    operation_name: str = "operation",
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        fn: Async function to execute
        max_retries: Maximum number of retry attempts
        initial_delay_ms: Initial delay in milliseconds
        operation_name: Name for logging

    Returns:
        Result of the function

    Raises:
        Last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay_ms = initial_delay_ms * (2**attempt)
                logger.warning(
                    f"BGG {operation_name} attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay_ms}ms ({max_retries - attempt} retries left)"
                )
                await asyncio.sleep(delay_ms / 1000)
            else:
                logger.error(f"BGG {operation_name} failed after {max_retries + 1} attempts: {e}")

    raise last_exception  # type: ignore[misc]


def _parse_game_xml(item: ET.Element, bgg_id: int) -> BGGGameInfo | None:
    """Parse a game item from BGG XML response."""
    # Extract primary name
    name = None
    for name_elem in item.findall("name"):
        if name_elem.get("type") == "primary":
            name = name_elem.get("value")
            break

    if not name:
        return None

    # Extract year
    year_elem = item.find("yearpublished")
    year_val = year_elem.get("value") if year_elem is not None else None
    year = int(year_val) if year_val else None

    # Extract image URLs
    image_elem = item.find("image")
    image_url = image_elem.text if image_elem is not None else None

    thumbnail_elem = item.find("thumbnail")
    thumbnail_url = thumbnail_elem.text if thumbnail_elem is not None else None

    # Extract description
    desc_elem = item.find("description")
    description = desc_elem.text if desc_elem is not None else None

    # Clean up description (remove HTML entities)
    if description:
        description = (
            description.replace("&#10;", "\n")
            .replace("&mdash;", "\u2014")
            .replace("&ndash;", "\u2013")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )

    # Extract player count
    min_players_elem = item.find("minplayers")
    min_players_val = min_players_elem.get("value") if min_players_elem is not None else None
    min_players = int(min_players_val) if min_players_val else None

    max_players_elem = item.find("maxplayers")
    max_players_val = max_players_elem.get("value") if max_players_elem is not None else None
    max_players = int(max_players_val) if max_players_val else None

    # Extract playing time
    playtime_elem = item.find("playingtime")
    playtime_val = playtime_elem.get("value") if playtime_elem is not None else None
    playing_time = int(playtime_val) if playtime_val else None

    # Extract links (publishers, designers, categories, mechanics)
    publishers = []
    designers = []
    categories = []
    mechanics = []

    for link in item.findall("link"):
        link_type = link.get("type")
        link_value = link.get("value")
        if link_value:
            if link_type == "boardgamepublisher":
                publishers.append(link_value)
            elif link_type == "boardgamedesigner":
                designers.append(link_value)
            elif link_type == "boardgamecategory":
                categories.append(link_value)
            elif link_type == "boardgamemechanic":
                mechanics.append(link_value)

    return BGGGameInfo(
        bgg_id=bgg_id,
        name=name,
        year=year,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        description=description,
        min_players=min_players,
        max_players=max_players,
        playing_time=playing_time,
        publishers=publishers or None,
        designers=designers or None,
        categories=categories or None,
        mechanics=mechanics or None,
    )


async def _fetch_game_from_api(bgg_id: int) -> BGGGameInfo | None:
    """Fetch game information directly from BGG API (no caching)."""
    url = f"{BGG_API_BASE}/thing?id={bgg_id}&stats=1"

    # Apply rate limiting
    await _rate_limiter.acquire()

    async with httpx.AsyncClient(headers=BGG_HEADERS) as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()

    # Parse XML response
    root = ET.fromstring(response.text)
    item = root.find("item")
    if item is None:
        return None

    return _parse_game_xml(item, bgg_id)


async def fetch_game_info(
    bgg_id: int,
    session: AsyncSession | None = None,
    bypass_cache: bool = False,
) -> BGGGameInfo | None:
    """Fetch game information from BoardGameGeek API with caching.

    Args:
        bgg_id: BoardGameGeek game ID
        session: Database session for caching (optional)
        bypass_cache: If True, always fetch from API

    Returns:
        BGGGameInfo if found, None otherwise
    """
    # Check cache if session provided and not bypassing
    if session is not None and not bypass_cache:
        stmt = select(BGGGame).where(BGGGame.id == bgg_id)
        result = await session.execute(stmt)
        cached = result.scalar_one_or_none()

        if cached is not None and not is_cache_stale(cached.cached_at):
            logger.debug(f"BGG cache hit for game {bgg_id}")
            return BGGGameInfo(
                bgg_id=cached.id,
                name=cached.name,
                year=cached.year_published,
                image_url=cached.image_url,
                thumbnail_url=cached.thumbnail_url,
                description=cached.description,
                min_players=cached.min_players,
                max_players=cached.max_players,
                playing_time=cached.playing_time,
                publishers=cached.publishers,
                designers=cached.designers,
                categories=cached.categories,
                mechanics=cached.mechanics,
            )

    # Fetch from API with retry
    try:
        info = await with_retry(
            lambda: _fetch_game_from_api(bgg_id),
            operation_name=f"fetch_game({bgg_id})",
        )
    except Exception:
        # with_retry already logs the error
        return None

    if info is None:
        return None

    # Update cache if session provided
    if session is not None:
        await _update_cache(session, info)

    return info


async def _update_cache(session: AsyncSession, info: BGGGameInfo) -> None:
    """Update the BGG game cache."""
    now_ms = int(datetime.now().timestamp() * 1000)

    # Use PostgreSQL upsert
    stmt = pg_insert(BGGGame).values(
        id=info.bgg_id,
        name=info.name,
        year_published=info.year,
        min_players=info.min_players,
        max_players=info.max_players,
        playing_time=info.playing_time,
        thumbnail_url=info.thumbnail_url,
        image_url=info.image_url,
        description=info.description,
        publishers=info.publishers,
        designers=info.designers,
        categories=info.categories,
        mechanics=info.mechanics,
        cached_at=now_ms,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "name": info.name,
            "year_published": info.year,
            "min_players": info.min_players,
            "max_players": info.max_players,
            "playing_time": info.playing_time,
            "thumbnail_url": info.thumbnail_url,
            "image_url": info.image_url,
            "description": info.description,
            "publishers": info.publishers,
            "designers": info.designers,
            "categories": info.categories,
            "mechanics": info.mechanics,
            "cached_at": now_ms,
        },
    )
    await session.execute(stmt)
    await session.commit()
    logger.debug(f"BGG cache updated for game {info.bgg_id}")


async def _search_games_api(query: str, limit: int) -> list[BGGSearchResult]:
    """Search for games directly from BGG API."""
    url = f"{BGG_API_BASE}/search?query={query}&type=boardgame,boardgameexpansion"

    # Apply rate limiting
    await _rate_limiter.acquire()

    async with httpx.AsyncClient(headers=BGG_HEADERS) as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()

    # Parse XML response
    root = ET.fromstring(response.text)

    # Collect basic info from search results
    results: list[BGGSearchResult] = []
    for item in root.findall("item"):
        item_id = item.get("id")
        item_type = item.get("type", "boardgame")
        if not item_id:
            continue

        # Get name
        name_elem = item.find("name")
        name = name_elem.get("value") if name_elem is not None else None
        if not name:
            continue

        # Get year
        year_elem = item.find("yearpublished")
        year_val = year_elem.get("value") if year_elem is not None else None
        year = int(year_val) if year_val else None

        results.append(
            BGGSearchResult(
                bgg_id=int(item_id),
                name=name,
                year=year,
                game_type=item_type,
            )
        )

        if len(results) >= limit:
            break

    return results


async def search_games_basic(query: str, limit: int = 10) -> list[BGGSearchResult]:
    """Search for games on BoardGameGeek (basic info only, faster).

    Note: Search results are NOT cached to ensure fresh results.

    Args:
        query: Search query
        limit: Maximum number of results

    Returns:
        List of BGGSearchResult objects with basic info
    """
    try:
        return await with_retry(
            lambda: _search_games_api(query, limit),
            max_retries=DEFAULT_MAX_RETRIES,
            initial_delay_ms=DEFAULT_INITIAL_DELAY_MS,
            operation_name=f"search({query})",
        )
    except Exception:
        # with_retry already logs the error
        return []


async def search_games(
    query: str,
    limit: int = 10,
    session: AsyncSession | None = None,
) -> list[BGGGameInfo]:
    """Search for games on BoardGameGeek with full details.

    Args:
        query: Search query
        limit: Maximum number of results
        session: Database session for caching

    Returns:
        List of BGGGameInfo objects
    """
    # Get basic search results
    search_results = await search_games_basic(query, limit)

    # Fetch full details for each game (uses cache if available)
    results: list[BGGGameInfo] = []
    for result in search_results:
        info = await fetch_game_info(result.bgg_id, session=session)
        if info:
            results.append(info)

    return results


async def _download_image_direct(url: str) -> bytes:
    """Download an image directly (no retry wrapper)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.content


async def download_image(url: str) -> bytes | None:
    """Download an image from a URL with retry.

    Args:
        url: Image URL

    Returns:
        Image bytes or None if download failed
    """
    try:
        return await with_retry(
            lambda: _download_image_direct(url),
            max_retries=IMAGE_MAX_RETRIES,
            initial_delay_ms=IMAGE_INITIAL_DELAY_MS,
            operation_name="download_image",
        )
    except Exception:
        # with_retry already logs the error
        return None
