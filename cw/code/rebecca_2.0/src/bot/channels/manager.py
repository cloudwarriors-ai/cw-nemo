"""
Channel Manager - routes messages to delivery channels.

Manages registration of channel adapters and handles message routing.
"""

import logging
from typing import Optional

from .base import ChannelAdapter, ChannelType, Message, DeliveryResult


class ChannelManager:
    """
    Manages message routing to multiple channels.

    Responsibilities:
    - Register/unregister channel adapters
    - Route messages to appropriate channel(s)
    - Handle multi-channel delivery (broadcast)
    - Track delivery status

    Thread Safety Note (Council fix M2):
        Adapter registration is NOT thread-safe. All adapters MUST be
        registered during application startup (in create_app) before
        handling any requests. The send() method is safe for concurrent
        use once adapters are registered.
    """

    def __init__(self, logger: logging.Logger = None):
        """
        Initialize the channel manager.

        Args:
            logger: Logger instance
        """
        self._adapters: dict[ChannelType, ChannelAdapter] = {}
        self._default_destinations: dict[ChannelType, str] = {}
        self.logger = logger or logging.getLogger("qa_agent")

    def register_adapter(
        self,
        adapter: ChannelAdapter,
        default_destination: str = None
    ) -> None:
        """
        Register a channel adapter.

        Args:
            adapter: Channel adapter instance
            default_destination: Default destination for this channel
        """
        self._adapters[adapter.channel_type] = adapter
        if default_destination:
            self._default_destinations[adapter.channel_type] = default_destination
        self.logger.info(f"Registered channel adapter: {adapter.channel_type.value}")

    def unregister_adapter(self, channel_type: ChannelType) -> bool:
        """
        Unregister a channel adapter.

        Args:
            channel_type: Channel type to unregister

        Returns:
            True if adapter was removed, False if not found
        """
        if channel_type in self._adapters:
            del self._adapters[channel_type]
            self._default_destinations.pop(channel_type, None)
            self.logger.info(f"Unregistered channel adapter: {channel_type.value}")
            return True
        return False

    def set_default_destination(self, channel_type: ChannelType, destination: str) -> None:
        """Set default destination for a channel."""
        self._default_destinations[channel_type] = destination

    def send(
        self,
        message: Message,
        channel: ChannelType,
        destination: str = None,
        **kwargs
    ) -> DeliveryResult:
        """
        Send message to a specific channel.

        Args:
            message: Message to send
            channel: Target channel type
            destination: Override default destination
            **kwargs: Channel-specific options

        Returns:
            DeliveryResult with success status
        """
        adapter = self._adapters.get(channel)

        if not adapter:
            self.logger.warning(f"No adapter registered for {channel.value}")
            return DeliveryResult(
                success=False,
                channel=channel,
                error=f"No adapter registered for {channel.value}"
            )

        if not adapter.is_available():
            self.logger.warning(f"Channel {channel.value} not available")
            return DeliveryResult(
                success=False,
                channel=channel,
                error=f"Channel {channel.value} not available"
            )

        dest = destination or self._default_destinations.get(channel)
        if not dest:
            self.logger.warning(f"No destination configured for {channel.value}")
            return DeliveryResult(
                success=False,
                channel=channel,
                error=f"No destination configured for {channel.value}"
            )

        try:
            formatted = adapter.format(message)
            result = adapter.send(formatted, dest, **kwargs)

            if result.success:
                self.logger.info(
                    f"Message delivered via {channel.value} to {dest[:20]}..."
                )
            else:
                self.logger.warning(
                    f"Message delivery failed via {channel.value}: {result.error}"
                )

            return result

        except Exception as e:
            # Log full error internally but return sanitized message (Council fix M3)
            self.logger.error(f"Channel send error ({channel.value}): {e}", exc_info=True)
            return DeliveryResult(
                success=False,
                channel=channel,
                error=f"Channel delivery failed: {channel.value}"
            )

    def broadcast(
        self,
        message: Message,
        channels: list[ChannelType] = None,
        destinations: dict[ChannelType, str] = None
    ) -> dict[ChannelType, DeliveryResult]:
        """
        Send message to multiple channels.

        Args:
            message: Message to send
            channels: List of channels to send to (default: all registered)
            destinations: Override destinations per channel

        Returns:
            Dictionary mapping channel type to delivery result
        """
        channels = channels or list(self._adapters.keys())
        destinations = destinations or {}

        results = {}
        for channel in channels:
            dest = destinations.get(channel)
            results[channel] = self.send(message, channel, dest)

        success_count = sum(1 for r in results.values() if r.success)
        self.logger.info(
            f"Broadcast complete: {success_count}/{len(results)} channels succeeded"
        )

        return results

    def get_available_channels(self) -> list[ChannelType]:
        """Return list of configured and available channels."""
        return [
            ct for ct, adapter in self._adapters.items()
            if adapter.is_available()
        ]

    def get_registered_channels(self) -> list[ChannelType]:
        """Return list of all registered channels."""
        return list(self._adapters.keys())

    def has_channel(self, channel_type: ChannelType) -> bool:
        """Check if a channel is registered."""
        return channel_type in self._adapters
