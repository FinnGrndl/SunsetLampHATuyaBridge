"""Read-only BlueZ and Linux Management observers for P2 advertisements."""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
import threading
from collections.abc import Callable

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from .mgmt import HCI_CHANNEL_CONTROL, MGMT_INDEX_NONE
from .protocol import P2_DP_FRAME_TYPE, P2_FRAME_LENGTH

_LOGGER = logging.getLogger(__name__)
_BLUEZ = "org.bluez"
_DBUS = "org.freedesktop.DBus"
_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
_PROPERTIES = "org.freedesktop.DBus.Properties"
_DEVICE = "org.bluez.Device1"
_ADAPTER = "org.bluez.Adapter1"
_MGMT_EV_DEVICE_FOUND = 0x0012


def _plain(value: object) -> object:
    while isinstance(value, Variant):
        value = value.value
    return value


def _normal_mac(value: str) -> str:
    return value.upper().replace("-", ":")


class BlueZObserver:
    """Observe P2 frames while owning only a per-client discovery session."""

    def __init__(
        self,
        target_mac: str,
        on_packet: Callable[[bytes, str], None],
        *,
        controller_index: int = 0,
        scan_enabled: bool = True,
    ) -> None:
        self.target_mac = _normal_mac(target_mac)
        self.on_packet = on_packet
        self.adapter_path = f"/org/bluez/hci{controller_index}"
        self.scan_enabled = scan_enabled
        self._bus: MessageBus | None = None
        self._devices: dict[str, dict[str, object]] = {}
        self._target_summaries: set[tuple[object, ...]] = set()
        self._seen_frames: set[tuple[str, bytes]] = set()

    @property
    def _controller_index(self) -> int:
        return int(self.adapter_path.removeprefix("/org/bluez/hci"))

    async def run(self) -> None:
        """Connect, load cached devices, and process future BlueZ signals."""
        stop = threading.Event()
        raw_thread = threading.Thread(
            target=self._run_management_observer,
            args=(stop,),
            name="mgmt-observer",
            daemon=True,
        )
        raw_thread.start()
        try:
            while True:
                try:
                    await self._run_once()
                except asyncio.CancelledError:
                    raise
                except (DBusError, OSError, RuntimeError) as err:
                    _LOGGER.warning("BlueZ observer unavailable: %s", err)
                    await asyncio.sleep(5)
        finally:
            stop.set()
            await asyncio.to_thread(raw_thread.join, 2)

    def _run_management_observer(self, stop: threading.Event) -> None:
        """Read raw Device Found events without changing controller state."""
        try:
            sock = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_RAW | getattr(socket, "SOCK_CLOEXEC", 0),
                socket.BTPROTO_HCI,
            )
            sock.settimeout(1.0)
            sock.bind((MGMT_INDEX_NONE, HCI_CHANNEL_CONTROL))
        except (AttributeError, OSError) as err:
            _LOGGER.warning("Raw Management event observer unavailable: %s", err)
            return
        _LOGGER.info("Raw Management Device Found observer attached")
        try:
            while not stop.is_set():
                try:
                    event = sock.recv(65535)
                except TimeoutError:
                    continue
                if len(event) < 20:
                    continue
                event_code, index, length = struct.unpack_from("<HHH", event)
                if event_code != _MGMT_EV_DEVICE_FOUND or index != self._controller_index:
                    continue
                payload = event[6 : 6 + length]
                if len(payload) < 14:
                    continue
                raw_address, _address_type, rssi, flags, eir_length = struct.unpack_from(
                    "<6sBbIH", payload
                )
                eir = payload[14 : 14 + eir_length]
                if len(eir) != eir_length:
                    continue
                address = ":".join(f"{byte:02X}" for byte in reversed(raw_address))
                self._inspect_raw_advertisement(address, rssi, flags, eir)
        except OSError as err:
            if not stop.is_set():
                _LOGGER.warning("Raw Management event observer stopped: %s", err)
        finally:
            sock.close()

    @staticmethod
    def _ad_sections(eir: bytes) -> list[tuple[int, bytes]]:
        sections: list[tuple[int, bytes]] = []
        offset = 0
        while offset < len(eir):
            length = eir[offset]
            if length == 0:
                break
            end = offset + length + 1
            if length < 1 or end > len(eir):
                break
            sections.append((eir[offset + 1], eir[offset + 2 : end]))
            offset = end
        return sections

    def _inspect_raw_advertisement(
        self, address: str, _rssi: int, _flags: int, eir: bytes
    ) -> None:
        for ad_type, packet in self._ad_sections(eir):
            if (
                ad_type not in (0x02, 0x03)
                or len(packet) != P2_FRAME_LENGTH
                or packet[0] != P2_DP_FRAME_TYPE
            ):
                continue
            identity = (address, packet)
            if identity in self._seen_frames:
                continue
            self._seen_frames.add(identity)
            if len(self._seen_frames) > 2048:
                self._seen_frames.clear()

            self.on_packet(packet, address)

    async def _run_once(self) -> None:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus = bus
        discovery_started = False
        try:
            bus.add_message_handler(self._message)
            await self._add_signal_match(bus)
            if self.scan_enabled:
                await self._adapter_call(
                    bus,
                    "SetDiscoveryFilter",
                    signature="a{sv}",
                    body=[
                        {
                            "Transport": Variant("s", "le"),
                            "DuplicateData": Variant("b", True),
                        }
                    ],
                )
                await self._adapter_call(bus, "StartDiscovery")
                discovery_started = True
                _LOGGER.info("BlueZ LE discovery session started with duplicate data enabled")

            reply = await bus.call(
                Message(
                    destination=_BLUEZ,
                    path="/",
                    interface=_OBJECT_MANAGER,
                    member="GetManagedObjects",
                )
            )
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError(reply.body[0] if reply.body else reply.error_name)
            for path, interfaces in reply.body[0].items():
                if device := interfaces.get(_DEVICE):
                    self._merge_device(path, device)
            _LOGGER.info("BlueZ observer attached")
            await bus.wait_for_disconnect()
        finally:
            if discovery_started:
                try:
                    await self._adapter_call(bus, "StopDiscovery")
                    _LOGGER.info("BlueZ discovery session released")
                except (DBusError, OSError, RuntimeError) as err:
                    _LOGGER.warning("Could not release BlueZ discovery session: %s", err)
            bus.disconnect()
            self._bus = None

    async def _add_signal_match(self, bus: MessageBus) -> None:
        reply = await bus.call(
            Message(
                destination=_DBUS,
                path="/org/freedesktop/DBus",
                interface=_DBUS,
                member="AddMatch",
                signature="s",
                body=["type='signal',sender='org.bluez'"],
            )
        )
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"D-Bus AddMatch failed: {detail}")

    async def _adapter_call(
        self,
        bus: MessageBus,
        member: str,
        *,
        signature: str | None = None,
        body: list[object] | None = None,
    ) -> None:
        reply = await bus.call(
            Message(
                destination=_BLUEZ,
                path=self.adapter_path,
                interface=_ADAPTER,
                member=member,
                signature=signature or "",
                body=body or [],
            )
        )
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"BlueZ {member} failed: {detail}")

    def _message(self, message: Message) -> bool:
        if message.message_type != MessageType.SIGNAL:
            return False
        if message.interface == _OBJECT_MANAGER and message.member == "InterfacesAdded":
            path, interfaces = message.body
            if device := interfaces.get(_DEVICE):
                self._merge_device(path, device)
        elif message.interface == _PROPERTIES and message.member == "PropertiesChanged":
            interface, changed, _invalidated = message.body
            if interface == _DEVICE and message.path:
                self._merge_device(message.path, changed)
        elif message.interface == _OBJECT_MANAGER and message.member == "InterfacesRemoved":
            path, interfaces = message.body
            if _DEVICE in interfaces:
                self._devices.pop(path, None)
        return False

    def _merge_device(self, path: str, changed: dict[str, object]) -> None:
        properties = self._devices.setdefault(path, {})
        properties.update({key: _plain(value) for key, value in changed.items()})
        address = _normal_mac(str(properties.get("Address", "")))
        if address != self.target_mac:
            return
        summary = (
            str(properties.get("AddressType", "unknown")),
            bool(properties.get("Name")),
            len(properties.get("UUIDs", [])) if isinstance(properties.get("UUIDs"), list) else 0,
        )
        if summary not in self._target_summaries:
            self._target_summaries.add(summary)
            _LOGGER.info(
                "Target advertisement seen: address_type=%s has_name=%s service_uuid_count=%d",
                summary[0],
                summary[1],
                summary[2],
            )
