from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import BinaryIO

from PIL import Image

from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.target import UITarget


class ColorSwatchDetector:
    """Find compact regions matching a requested colour inside a supplied palette region.

    This detector deliberately requires a search region. It does not scan the entire
    desktop and guess that arbitrary red artwork is a toolbar colour swatch.
    """

    def detect(
        self,
        image: str | Path | Image.Image,
        *,
        observation_id: str,
        search_region: Rect,
        color_name: str,
        rgb: tuple[int, int, int],
        tolerance: int = 28,
        minimum_area: int = 16,
        maximum_area_fraction: float = 0.08,
        maximum_results: int = 8,
    ) -> list[UITarget]:
        if not observation_id or not color_name.strip():
            raise ValueError("observation_id and color_name are required")
        if len(rgb) != 3 or any(not 0 <= channel <= 255 for channel in rgb):
            raise ValueError("rgb must contain three channels between 0 and 255")
        if not 0 <= tolerance <= 255:
            raise ValueError("tolerance must be between 0 and 255")
        if minimum_area < 1 or maximum_results < 1:
            raise ValueError("minimum_area and maximum_results must be positive")
        if not 0.0 < maximum_area_fraction <= 1.0:
            raise ValueError("maximum_area_fraction must be between 0 and 1")

        owns_image = not isinstance(image, Image.Image)
        opened = Image.open(image) if owns_image else image
        try:
            source = opened.convert("RGB")
            width, height = source.size
            if (
                search_region.x < 0 or search_region.y < 0
                or search_region.width <= 0 or search_region.height <= 0
                or search_region.x + search_region.width > width
                or search_region.y + search_region.height > height
            ):
                raise ValueError("search_region must lie inside the screenshot")
            pixels = source.load()
            x0, y0 = search_region.x, search_region.y
            region_width, region_height = search_region.width, search_region.height
            mask = bytearray(region_width * region_height)
            for local_y in range(region_height):
                for local_x in range(region_width):
                    pixel = pixels[x0 + local_x, y0 + local_y]
                    if max(abs(pixel[index] - rgb[index]) for index in range(3)) <= tolerance:
                        mask[local_y * region_width + local_x] = 1

            visited = bytearray(len(mask))
            candidates: list[tuple[int, int, int, int, int]] = []
            for start in range(len(mask)):
                if not mask[start] or visited[start]:
                    continue
                queue = deque([start])
                visited[start] = 1
                min_x = max_x = start % region_width
                min_y = max_y = start // region_width
                area = 0
                while queue:
                    index = queue.popleft()
                    local_x, local_y = index % region_width, index // region_width
                    area += 1
                    min_x, max_x = min(min_x, local_x), max(max_x, local_x)
                    min_y, max_y = min(min_y, local_y), max(max_y, local_y)
                    for nx, ny in (
                        (local_x - 1, local_y), (local_x + 1, local_y),
                        (local_x, local_y - 1), (local_x, local_y + 1),
                    ):
                        if 0 <= nx < region_width and 0 <= ny < region_height:
                            neighbor = ny * region_width + nx
                            if mask[neighbor] and not visited[neighbor]:
                                visited[neighbor] = 1
                                queue.append(neighbor)
                box_area = (max_x - min_x + 1) * (max_y - min_y + 1)
                if area >= minimum_area and area / max(box_area, 1) >= 0.55:
                    if area <= region_width * region_height * maximum_area_fraction:
                        candidates.append((
                            area, x0 + min_x, y0 + min_y,
                            max_x - min_x + 1, max_y - min_y + 1,
                        ))

            candidates.sort(key=lambda item: item[0], reverse=True)
            results: list[UITarget] = []
            for index, (area, left, top, box_width, box_height) in enumerate(candidates[:maximum_results], start=1):
                confidence = min(0.99, 0.70 + 0.29 * (area / max(box_width * box_height, 1)))
                suffix = "" if index == 1 else f".{index}"
                results.append(UITarget(
                    target_id=f"paint.color.{color_name.casefold().replace(' ', '-')}{suffix}",
                    label=f"{color_name.title()} colour swatch",
                    kind="color",
                    bounds=Rect(x=left, y=top, width=box_width, height=box_height),
                    observation_id=observation_id,
                    confidence=confidence,
                    source="vision",
                    metadata={
                        "rgb": list(rgb),
                        "matching_pixels": area,
                        "palette_region": search_region.model_dump(),
                    },
                ))
            return results
        finally:
            if owns_image:
                opened.close()
