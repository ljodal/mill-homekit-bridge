import logging
import signal
import argparse
import httpx
import asyncio

from pyhap.iid_manager import IIDManager
from pyhap.accessory import Accessory, Bridge
from pyhap.accessory_driver import AccessoryDriver
from pyhap.const import CATEGORY_HEATER
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="[%(module)s] %(message)s")


@dataclass(kw_only=True)
class HeaterStatus:
    current_temperature: float
    target_temperature: float


class Client:
    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port

        self.client = httpx.AsyncClient(base_url=f"http://{host}:{port}")

    async def get_status(self) -> HeaterStatus:
        response = await self.client.get("/control-status")
        data = response.json()

        return HeaterStatus(
            current_temperature=data["ambient_temperature"],
            target_temperature=data["set_temperature"],
        )

    async def close(self) -> None:
        await self.client.aclose()


class MillHeater(Accessory):
    """Fake Temperature sensor, measuring every 3 seconds."""

    category = CATEGORY_HEATER

    def __init__(
        self,
        driver: AccessoryDriver,
        display_name: str | None = None,
        aid: int | None = None,
        iid_manager: IIDManager | None = None,
        *,
        host: str,
        port: int,
    ) -> None:
        super().__init__(driver, display_name, aid, iid_manager)

        print(f"Creating accessory: {display_name}")

        self.client = Client(host=host, port=port)

        self.service = self.add_preload_service(
            "HeaterCooler",
            chars=[
                "Active",
                "CurrentHeaterCoolerState",
                "TargetHeaterCoolerState",
                "CurrentTemperature",
                "HeatingThresholdTemperature",
            ],
        )

        target_state = self.service.get_characteristic("TargetHeaterCoolerState")
        target_state.set_value(1)  # Heat

    def set_current_temperature(self, temperature: float) -> None:
        char = self.service.get_characteristic("CurrentTemperature")
        char.set_value(temperature)

    def set_target_temperature(self, temperature: float) -> None:
        char = self.service.get_characteristic("HeatingThresholdTemperature")
        char.set_value(temperature)

        # TODO: Call heater API to set target temperature

    @Accessory.run_at_interval(5)
    async def run(self) -> None:
        status = await self.client.get_status()
        self.set_current_temperature(status.current_temperature)
        self.set_target_temperature(status.target_temperature)

    async def stop(self) -> None:
        await asyncio.gather(
            super().stop(),
            self.client.close(),
        )


def create_bridge(driver: AccessoryDriver) -> Bridge:
    """Configure the bridge based on the supplied command line arguments"""

    parser = argparse.ArgumentParser("mill_homekit_bridge")
    # parser.add_argument("--state-file", help="Path to state file")
    parser.add_argument(
        "--heater",
        dest="heaters",
        action="append",
        required=True,
        nargs=2,
        metavar=("name", "host[:port]"),
        help="Name and connection details for each heater to control",
    )

    args = parser.parse_args()

    heaters = []
    for name, address in args.heaters:
        try:
            host, port = address.split(":", 1)
        except ValueError:
            host, port = address, "80"

        heaters.append((name, host, int(port)))

    bridge = Bridge(driver, display_name="Mill Heater Bridge")
    for name, host, port in heaters:
        heater = MillHeater(driver, display_name=name, host=host, port=port)
        bridge.add_accessory(heater)

    return bridge


def main() -> None:
    # Start the accessory on port 51826
    driver = AccessoryDriver(port=51826)

    # Change `get_accessory` to `get_bridge` if you want to run a Bridge.
    driver.add_accessory(accessory=create_bridge(driver))

    # We want SIGTERM (terminate) to be handled by the driver itself,
    # so that it can gracefully stop the accessory, server and advertising.
    signal.signal(signal.SIGTERM, driver.signal_handler)

    # Start it!
    driver.start()


if __name__ == "__main__":
    main()
