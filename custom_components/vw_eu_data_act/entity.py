"""Base entity for the VW EU Data Act integration."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NICKNAME, DOMAIN
from .coordinator import EudaCoordinator


class EudaEntity(CoordinatorEntity[EudaCoordinator]):
    """Common base: shares one device per VIN."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EudaCoordinator) -> None:
        super().__init__(coordinator)
        vin = coordinator.vin
        name = coordinator.entry.data.get(CONF_NICKNAME) or vin
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, vin)},
            name=name,
            manufacturer="Volkswagen",
            model="EU Data Act vehicle",
            serial_number=vin,
        )
