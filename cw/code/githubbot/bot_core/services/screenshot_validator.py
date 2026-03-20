"""Screenshot URL validator with SSRF protection"""
import logging
import ipaddress
import socket
from urllib.parse import urlparse
from typing import List, Tuple
import httpx

logger = logging.getLogger(__name__)


class ScreenshotURLValidator:
    """
    Validates screenshot URLs to prevent SSRF attacks.

    Security checks:
    1. HTTPS-only (except for allowed HTTP domains)
    2. Domain allowlisting
    3. IP address blocking (localhost, private networks, AWS metadata)
    4. Content-Type validation
    5. File size validation
    6. Redirect chain validation
    """

    # Allowed domains for screenshot URLs
    ALLOWED_DOMAINS = [
        'imgur.com',
        'i.imgur.com',
        'github.com',
        'user-images.githubusercontent.com',
        'raw.githubusercontent.com',
        'drive.google.com',
        'docs.google.com',
        'storage.googleapis.com',
        'cloudinary.com',
        'res.cloudinary.com',
    ]

    # Blocked IP ranges (CIDR notation)
    BLOCKED_IP_RANGES = [
        '127.0.0.0/8',      # Localhost
        '10.0.0.0/8',       # Private network
        '172.16.0.0/12',    # Private network
        '192.168.0.0/16',   # Private network
        '169.254.0.0/16',   # Link-local (AWS metadata)
        '0.0.0.0/8',        # Current network
        '100.64.0.0/10',    # Shared address space
        '224.0.0.0/4',      # Multicast
        '240.0.0.0/4',      # Reserved
        '::1/128',          # IPv6 localhost
        'fc00::/7',         # IPv6 private
        'fe80::/10',        # IPv6 link-local
    ]

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']

    def __init__(self):
        """Initialize validator with compiled IP ranges"""
        self.blocked_networks = [
            ipaddress.ip_network(cidr) for cidr in self.BLOCKED_IP_RANGES
        ]

    async def validate(self, url: str) -> Tuple[bool, str]:
        """
        Validate a screenshot URL.

        Args:
            url: The URL to validate

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message will be empty string
        """
        if not url or not url.strip():
            return False, "URL cannot be empty"

        url = url.strip()

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            logger.warning(f"Failed to parse URL {url}: {e}")
            return False, "Invalid URL format"

        # Check scheme (must be https, or http for allowed domains)
        if parsed.scheme not in ['http', 'https']:
            return False, f"Invalid URL scheme '{parsed.scheme}'. Only HTTP/HTTPS allowed."

        # Prefer HTTPS
        if parsed.scheme != 'https':
            logger.warning(f"HTTP URL provided: {url}")

        # Check domain allowlist
        hostname = parsed.hostname
        if not hostname:
            return False, "URL must have a hostname"

        if not self._is_domain_allowed(hostname):
            return False, f"Domain '{hostname}' not allowed. Use imgur.com, GitHub, or Google Drive."

        # Resolve hostname to IP and check against blocked ranges
        try:
            ip_addresses = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            logger.warning(f"Failed to resolve hostname {hostname}: {e}")
            return False, f"Cannot resolve hostname '{hostname}'"

        for addr_info in ip_addresses:
            ip_str = addr_info[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if self._is_ip_blocked(ip_obj):
                    logger.warning(f"Blocked IP address {ip_str} for hostname {hostname}")
                    return False, f"IP address {ip_str} is blocked (private/local network)"
            except ValueError:
                continue

        # Perform HEAD request to validate content type and size
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                response = await client.head(url)

                # Check if we were redirected to a different domain
                final_url = str(response.url)
                final_hostname = urlparse(final_url).hostname
                if final_hostname != hostname:
                    if not self._is_domain_allowed(final_hostname):
                        return False, f"Redirect to unauthorized domain '{final_hostname}'"

                # Check content type
                content_type = response.headers.get('content-type', '').lower().split(';')[0].strip()
                if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
                    return False, f"Invalid content type '{content_type}'. Must be an image."

                # Check content length
                content_length = response.headers.get('content-length')
                if content_length:
                    try:
                        size = int(content_length)
                        if size > self.MAX_FILE_SIZE:
                            return False, f"File too large ({size} bytes). Max size is {self.MAX_FILE_SIZE} bytes."
                    except ValueError:
                        pass

        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching URL {url}")
            return False, "URL request timeout. Please try a different image host."
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching URL {url}: {e}")
            return False, f"Failed to fetch URL: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error validating URL {url}: {e}", exc_info=True)
            return False, f"Error validating URL: {str(e)}"

        return True, ""

    def _is_domain_allowed(self, hostname: str) -> bool:
        """Check if domain is in allowlist"""
        hostname_lower = hostname.lower()

        # Exact match
        if hostname_lower in self.ALLOWED_DOMAINS:
            return True

        # Subdomain match (e.g., cdn.example.com matches example.com)
        for allowed_domain in self.ALLOWED_DOMAINS:
            if hostname_lower.endswith(f'.{allowed_domain}') or hostname_lower == allowed_domain:
                return True

        return False

    def _is_ip_blocked(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Check if IP is in blocked ranges"""
        for network in self.blocked_networks:
            if ip in network:
                return True
        return False


async def validate_screenshot_urls(urls: List[str]) -> Tuple[bool, str]:
    """
    Validate a list of screenshot URLs.

    Args:
        urls: List of URLs to validate

    Returns:
        Tuple of (all_valid, error_message)
    """
    if not urls:
        return True, ""  # Empty list is valid

    validator = ScreenshotURLValidator()

    for i, url in enumerate(urls):
        is_valid, error = await validator.validate(url)
        if not is_valid:
            return False, f"Screenshot #{i+1}: {error}"

    return True, ""


# Singleton instance
screenshot_validator = ScreenshotURLValidator()
