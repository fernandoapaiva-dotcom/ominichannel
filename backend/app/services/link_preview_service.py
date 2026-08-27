import re
import html
import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urljoin, parse_qs
import httpx

logger = logging.getLogger("link_preview_service")

# In-memory cache for fast repeated lookups
_PREVIEW_CACHE: Dict[str, Dict[str, Any]] = {}

class LinkPreviewService:
    def _normalize_url(self, url: str) -> str:
        clean = url.strip()
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = f"https://{clean}"

        # Special normalization for known services
        if "bible.com" in clean:
            clean = clean.replace("https://bible.com", "https://www.bible.com").replace("http://bible.com", "https://www.bible.com")
            if "/videos/" in clean and "/pt/videos/" not in clean:
                clean = clean.replace("/videos/", "/pt/videos/")
            elif "/verse-of-the-day/" in clean and "/pt/verse-of-the-day/" not in clean:
                clean = clean.replace("/verse-of-the-day/", "/pt/verse-of-the-day/")

        return clean

    async def get_preview(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetches OpenGraph metadata, title, description, and preview image for a URL.
        Returns cached result if available.
        """
        if not url or not isinstance(url, str):
            return None

        clean_url = self._normalize_url(url)
        cache_key = url.strip()

        if cache_key in _PREVIEW_CACHE:
            cached = _PREVIEW_CACHE[cache_key]
            if cached.get("image") or (cached.get("title") and cached.get("title") != cached.get("domain")):
                return cached

        parsed = urlparse(clean_url)
        domain = parsed.netloc.replace("www.", "") or parsed.netloc

        headers = {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, verify=False) as client:
                resp = await client.get(clean_url, headers=headers)
                if resp.status_code >= 400:
                    result = {
                        "url": url,
                        "title": domain,
                        "description": None,
                        "image": None,
                        "domain": domain
                    }
                    return result

                raw_html = resp.text # Full HTML

                # 1. Extract Title
                title = None
                m_title = (
                    re.search(r'<meta[^>]+property=[\'"](?:og:title|twitter:title)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+property=[\'"](?:og:title|twitter:title)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+name=[\'"](?:twitter:title|title)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<title[^>]*>([^<]+)</title>', raw_html, re.IGNORECASE)
                )
                if m_title:
                    title = html.unescape(m_title.group(1).strip())

                # 2. Extract Description
                description = None
                m_desc = (
                    re.search(r'<meta[^>]+property=[\'"](?:og:description|twitter:description)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+property=[\'"](?:og:description|twitter:description)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+name=[\'"](?:description|twitter:description)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE)
                )
                if m_desc:
                    description = html.unescape(m_desc.group(1).strip())

                # 3. Extract Image
                image = None
                m_img = (
                    re.search(r'<meta[^>]+property=[\'"](?:og:image|og:image:url|twitter:image|twitter:image:src)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+property=[\'"](?:og:image|og:image:url|twitter:image|twitter:image:src)[\'"]', raw_html, re.IGNORECASE) or
                    re.search(r'<meta[^>]+name=[\'"](?:twitter:image|twitter:image:src)[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', raw_html, re.IGNORECASE)
                )
                if m_img:
                    raw_img = html.unescape(m_img.group(1).strip())
                    image = urljoin(clean_url, raw_img)

                # 4. Fallback: Parse Next.js __NEXT_DATA__ or JSON-LD if present
                if not image or not title:
                    try:
                        m_next = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', raw_html)
                        if m_next:
                            next_json = json.loads(m_next.group(1))
                            p_props = next_json.get("props", {}).get("pageProps", {})
                            # Check story/video/verse
                            clip = p_props.get("clip") or p_props.get("video") or p_props.get("verseOfTheDay") or {}
                            if clip:
                                if not title and clip.get("title"):
                                    title = clip.get("title")
                                if not image and clip.get("thumbnail_url"):
                                    image = clip.get("thumbnail_url")
                                elif not image and clip.get("image_url"):
                                    image = clip.get("image_url")
                                elif not image and clip.get("images"):
                                    images = clip.get("images")
                                    if isinstance(images, list) and len(images) > 0:
                                        image = images[0].get("url") or images[0]
                                    elif isinstance(images, dict):
                                        image = images.get("url")
                    except Exception:
                        pass

                # Fallback to domain if title is empty
                if not title:
                    title = domain

                result = {
                    "url": url,
                    "title": title,
                    "description": description,
                    "image": image,
                    "domain": domain
                }

                if len(_PREVIEW_CACHE) > 2000:
                    _PREVIEW_CACHE.clear()

                _PREVIEW_CACHE[cache_key] = result
                _PREVIEW_CACHE[clean_url] = result
                return result

        except Exception as e:
            logger.debug(f"Error fetching link preview for {clean_url}: {e}")
            result = {
                "url": url,
                "title": domain,
                "description": None,
                "image": None,
                "domain": domain
            }
            return result

link_preview_service = LinkPreviewService()
