"""Tuya Beacon HAOS app entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

from tuya_beacon_bridge.bridge import BridgeConfig, TuyaBeaconBridge
from tuya_beacon_bridge.http_api import BridgeHTTPServer
from tuya_beacon_bridge.scanner import BlueZObserver


async def async_main() -> None:
    options_path = Path("/data/options.json")
    options = json.loads(options_path.read_text(encoding="utf-8"))
    config = BridgeConfig.from_options(options)
    level_name = str(options.get("log_level", "info")).upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger = logging.getLogger("tuya_beacon_bridge")
    bridge = TuyaBeaconBridge(config)
    server = BridgeHTTPServer((config.listen_host, config.listen_port), bridge)
    thread = threading.Thread(target=server.serve_forever, name="http-api", daemon=True)
    thread.start()
    logger.info("Bridge API listening on %s:%d", config.listen_host, config.listen_port)
    logger.info(
        "Diagnostic mode=%s; target=%s; controller=hci%d; scan=%s; instance=%d",
        not config.control_enabled,
        config.target_mac,
        config.controller_index,
        config.scan_enabled,
        config.advertising_instance,
    )
    try:
        capabilities = await asyncio.to_thread(bridge.capabilities)
        logger.info(
            "Adapter advertising: max_instances=%d active=%s max_adv_len=%d",
            capabilities["max_instances"],
            capabilities["active_instances"],
            capabilities["max_advertising_length"],
        )
    except (OSError, RuntimeError, ValueError) as err:
        logger.warning("Advertising capability check failed: %s", err)

    observer = BlueZObserver(
        config.target_mac,
        bridge.on_packet,
        controller_index=config.controller_index,
        scan_enabled=config.scan_enabled,
    )
    try:
        await observer.run()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(async_main())
