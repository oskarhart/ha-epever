"""Simple Modbus communication for Epever devices."""

import logging
from typing import Any

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

_LOGGER = logging.getLogger(__name__)

def get_pv_voltage(
    host: str, port: int, unit_id: int = 1
) -> float | None:
    """Retrieve the current PV voltage from the Epever device over Modbus TCP.

    Args:
        host: IP address of the Epever device.
        port: Modbus TCP port of the device.
        unit_id: Modbus unit ID of the device.

    Returns:
        PV voltage in volts, or None if an error occurs.
    """
    # Use RTU framer over TCP if available (as per Epever protocol)
    client = ModbusTcpClient(host=host, port=port, retries=1, framer=FramerType.RTU)

    try:
        if not client.connect():
            return None

        _LOGGER.debug("Connected to Epever device")

        # Send initialization sequence (required by Epever devices)
        client.send(bytes.fromhex("20020000"))

        _LOGGER.debug("Sent initialization sequence")

        # Read input register 0x3100 for PV voltage
        result = client.read_input_registers(address=0x3100, count=19, device_id=unit_id)

        _LOGGER.debug("PV voltage register response: %s", result)

        if result.isError():
            return None

        # PV voltage is scaled by dividing by 100 (register value / 100 = volts)
        return result.registers[0] / 100.0

    except (ConnectionError, TimeoutError, ValueError):
        _LOGGER.exception("Failed to read PV voltage")
        return None
    finally:
        client.close()


def _value16(value: int) -> float:
    """Convert 16-bit signed value to float, scaled by 100."""
    return (value if value < 32768 else value - 65536) / 100.0


def _value32(low: int, high: int) -> float:
    """Convert 32-bit signed value to float, scaled by 100."""
    combined = low + (high << 16)
    return (combined if combined < 2147483648 else combined - 4294967296) / 100.0


def get_all_data(
    host: str, port: int, unit_id: int = 1
) -> dict[str, Any] | None:
    """Retrieve all data from the Epever device over Modbus TCP.

    Args:
        host: IP address of the Epever device.
        port: Modbus TCP port of the device.
        unit_id: Modbus unit ID of the device.

    Returns:
        Dictionary with all device data, or None if an error occurs.
    """
    client = ModbusTcpClient(host=host, port=port, retries=1, framer=FramerType.RTU)

    try:
        if not client.connect():
            return None

        # Send initialization sequence (required by Epever devices)
        client.send(bytes.fromhex("20020000"))

        data: dict[str, Any] = {}

        # Read realtime data registers (0x3100 - 0x311D)
        try:
            result = client.read_input_registers(address=0x3100, count=19, device_id=unit_id)
            if not result.isError():
                registers = result.registers

                # PV array data (offset from 0x3100)
                data["pv_voltage"] = _value16(registers[0])  # 0x3100
                data["pv_current"] = _value16(registers[1])  # 0x3101
                data["pv_power"] = _value32(registers[2], registers[3])  # 0x3102-0x3103

                # Battery data (BATT1)
                data["battery_voltage"] = _value16(registers[4])  # 0x3104
                data["battery_current"] = _value16(registers[5])  # 0x3105
                data["battery_power"] = _value32(registers[6], registers[7])  # 0x3106-0x3107

                # Load data
                data["load_voltage"] = _value16(registers[12])  # 0x310C
                data["load_current"] = _value16(registers[13])  # 0x310D
                data["load_power"] = _value32(registers[14], registers[15])  # 0x310E-0x310F

                # Device temperature
                data["device_temperature"] = _value16(registers[17])  # 0x3111
            else:
                _LOGGER.warning(f"Kunne ikke lese realtime blokk 0x3100: {result}")
        except Exception as e:
            _LOGGER.error(f"Feil i realtime blokk 0x3100: {e}")
                

        # 1. BATT2 Realtime (0x3130)
        try:
            result = client.read_input_registers(address=0x3130, count=5, device_id=unit_id)
            if not result.isError():
                registers = result.registers
                data["battery_2_voltage"] = _value16(registers[0])
                data["battery_2_current"] = _value16(registers[1])
                data["battery_2_power"] = _value32(registers[2], registers[3])
                data["battery_2_soc"] = registers[4]
        except Exception as e:
            _LOGGER.error(f"Feil ved lesing av BATT2 realtime: {e}")

        # 2. Status registre (0x3200)
        try:
            result = client.read_input_registers(address=0x3200, count=3, device_id=unit_id)
            if not result.isError():
                status_registers = result.registers
                # Her kan du legge inn bitmask-logikken din igjen hvis du vil ha den aktiv
        except Exception as e:
            _LOGGER.error(f"Feil ved lesing av status: {e}")

        # 3. Maks/Min BATT1 i dag (0x3302)
        try:
            result = client.read_input_registers(address=0x3302, count=2, device_id=unit_id)
            if not result.isError():
                energy_registers = result.registers
                data["maximum_battery_1_voltage_today"] = _value16(energy_registers[0])
                data["minimum_battery_1_voltage_today"] = _value16(energy_registers[1])
        except Exception as e:
            _LOGGER.error(f"Feil ved lesing av BATT1 max/min: {e}")

        # 4. Energistatistikk (0x330C)
        try:
            result = client.read_input_registers(address=0x330C, count=8, device_id=unit_id)
            if not result.isError():
                energy_registers = result.registers
                data["generated_energy_today"] = _value32(energy_registers[0], energy_registers[1])
                data["generated_energy_month"] = _value32(energy_registers[2], energy_registers[3])
                data["generated_energy_year"] = _value32(energy_registers[4], energy_registers[5])
                data["generated_energy_total"] = _value32(energy_registers[6], energy_registers[7])
        except Exception as e:
            _LOGGER.error(f"Feil ved lesing av energi: {e}")

        # 5. Maks/Min BATT2 i dag (0x3320)
        try:
            result = client.read_input_registers(address=0x3320, count=2, device_id=unit_id)
            if not result.isError():
                energy_registers = result.registers
                data["maximum_battery_2_voltage_today"] = _value16(energy_registers[0])
                data["minimum_battery_2_voltage_today"] = _value16(energy_registers[1])
        except Exception as e:
            _LOGGER.error(f"Feil ved lesing av BATT2 max/min: {e}")

        return data

    except Exception as e:
        _LOGGER.error(f"Kritisk feil i get_all_data: {e}")
        return None
    finally:
        client.close()
