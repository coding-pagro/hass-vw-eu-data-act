"""Sensor platform: curated sensors + raw diagnostic data points."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EudaConfigEntry
from .const import raw_unique_id
from .coordinator import EudaCoordinator
from .data import (
    CURATED_BINARY_DOTTED,
    CURATED_BINARY_FLAT,
    CURATED_SENSORS_DOTTED,
    CURATED_SENSORS_FLAT,
    UNIT_RESOLVERS,
    CuratedSensor,
    DataPoint,
    detect_dataset_format,
    entity_translation_key,
    enum_option_key,
    enum_options_for_field,
    find_by_field,
    find_curated,
    friendly_name,
    is_remaining_time_sentinel,
    latest_captured_time,
    resolve_distance_unit,
    shorten_enum_label,
)
from .entity import EudaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EudaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    points: dict[str, DataPoint] = coordinator.data or {}
    present_fields = {dp.field_name for dp in points.values()}

    # Detect dataset format and select appropriate curated group
    format_type = detect_dataset_format(points)
    curated_sensors = (
        CURATED_SENSORS_DOTTED if format_type == "dotted" else CURATED_SENSORS_FLAT
    )
    curated_binary = (
        CURATED_BINARY_DOTTED if format_type == "dotted" else CURATED_BINARY_FLAT
    )

    # Build field sets for exclusion from raw sensors (aliases too: a field
    # feeding a curated sensor must not also appear as a raw diagnostic)
    binary_fields = {b.field_name for b in curated_binary}
    curated_sensor_fields = {s.field_name for s in curated_sensors} | {
        a for s in curated_sensors for a in s.aliases
    }

    entities: list[SensorEntity] = []

    # curated numeric / text sensors (one per field, if present)
    for curated in curated_sensors:
        # Special handling for timestamp sensors (e.g., "mileage.timestamp" or "mileage.value.timestamp")
        if ".timestamp" in curated.field_name:
            base_field = curated.field_name.replace(".timestamp", "")
            base_dp = find_by_field(points, base_field)
            # Only when the data point really carries a timestampUtc attribute;
            # many vehicles' datasets don't, which left a forever-unknown
            # "Last connected" sensor (Last vehicle update covers those).
            if base_dp is not None and base_dp.timestamp is not None:
                entities.append(EudaCuratedSensor(coordinator, curated))
        elif curated.field_name in present_fields or any(
            a in present_fields for a in curated.aliases
        ):
            entities.append(EudaCuratedSensor(coordinator, curated))

    # raw diagnostic sensors: every other unique key
    for key, dp in points.items():
        if dp.field_name in curated_sensor_fields or dp.field_name in binary_fields:
            continue
        entities.append(EudaRawSensor(coordinator, key))

    # dataset-level freshness sensors
    if latest_captured_time(points) is not None:
        entities.append(EudaLastVehicleUpdateSensor(coordinator))
    entities.append(EudaDatasetGeneratedSensor(coordinator))

    async_add_entities(entities)


class EudaCuratedSensor(EudaEntity, SensorEntity):
    """A curated, well-typed sensor (enabled by default)."""

    def __init__(self, coordinator: EudaCoordinator, curated: CuratedSensor) -> None:
        super().__init__(coordinator)
        self._curated = curated
        self._monotonic = curated.monotonic
        self._attr_unique_id = f"{coordinator.vin}_{curated.field_name}"
        # Name and (for enums) states come from the translation files; see
        # tools/gen_translations.py. curated.name is the English source string.
        self._attr_translation_key = entity_translation_key(curated.field_name)
        if curated.icon:
            self._attr_icon = curated.icon
        self._enum_options: list[str] | None = None
        if curated.device_class == "enum":
            # ENUM requires the option list; fall back to a plain text sensor
            # when the dictionary documents no members for this field.
            options = enum_options_for_field(curated.field_name)
            if options:
                self._enum_options = options
                self._attr_device_class = SensorDeviceClass.ENUM
                self._attr_options = options
        elif curated.device_class:
            self._attr_device_class = SensorDeviceClass(curated.device_class)
        if curated.state_class:
            self._attr_state_class = SensorStateClass(curated.state_class)
        if curated.suggested_display_precision is not None:
            self._attr_suggested_display_precision = curated.suggested_display_precision

    def _enum_state(self, raw_value) -> str | None:
        """Map a raw enum value onto the sensor's lowercase option keys."""
        if raw_value is None:
            return None
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            # protobuf index the bound data point couldn't resolve itself
            if 0 <= raw_value < len(self._enum_options):
                return self._enum_options[raw_value]
            return None
        state = enum_option_key(self._curated.field_name, str(raw_value))
        if state not in self._enum_options:
            # Live values occasionally differ from the documented members
            # (e.g. MAX_CHARGE_CURRENT_AC_MAXIMUM vs the documented
            # MAX_CHARGE_CURRENT_MAXIMUM); extend the options instead of
            # letting HA reject the state.
            self._enum_options.append(state)
        return state

    @property
    def native_value(self):
        # Special handling for timestamp fields (both "mileage.timestamp" and "mileage.value.timestamp")
        if ".timestamp" in self._curated.field_name:
            base_field = self._curated.field_name.replace(".timestamp", "")
            dp = find_by_field(self.coordinator.data or {}, base_field)
            if dp and dp.timestamp:
                return self._sticky(dp.timestamp)
            return self._sticky(None)

        dp = find_curated(self.coordinator.data or {}, self._curated)

        if not dp:
            return self._sticky(None)

        raw_value = dp.value

        # Apply transforms if specified
        if self._curated.transform:
            if self._curated.transform == "decikelvin_to_celsius":
                from .data import decikelvin_to_celsius

                transformed = decikelvin_to_celsius(dp.raw_value)
                return self._sticky(transformed)

            elif self._curated.transform == "abs":
                from .data import abs_value

                transformed = abs_value(raw_value)
                return self._sticky(transformed)

            elif self._curated.transform == "fuel_consumption":
                from .data import fuel_consumption_l_per_1000km_to_l_per_100km

                transformed = fuel_consumption_l_per_1000km_to_l_per_100km(raw_value)
                return self._sticky(transformed)

            elif self._curated.transform == "remaining_time":
                # 65535 = "no estimate" (not charging). That is a real reading
                # meaning unknown, so reset stickiness instead of freezing the
                # last estimate on the sensor forever.
                if raw_value is not None and is_remaining_time_sentinel(raw_value):
                    self._last_value = None
                    return None
                return self._sticky(raw_value)

        if self._enum_options is not None:
            return self._sticky(self._enum_state(raw_value))
        return self._sticky(shorten_enum_label(self._curated.field_name, raw_value))

    @property
    def native_unit_of_measurement(self) -> str | None:
        # When a companion unit field is declared (e.g. mileage.unit), resolve
        # the unit at runtime so miles vs km is reported correctly per vehicle;
        # otherwise use the static curated unit.
        cur = self._curated
        if cur.unit_field:
            dp = find_by_field(self.coordinator.data or {}, cur.unit_field)
            if dp is not None:
                resolver = UNIT_RESOLVERS.get(cur.unit_resolver, resolve_distance_unit)
                resolved = resolver(dp.value)
                if resolved:
                    return resolved
        return cur.unit


class EudaLastVehicleUpdateSensor(EudaEntity, SensorEntity):
    """Newest car-to-backend timestamp in the data: how fresh the values are.

    Distinct from the entity's own last_updated (which only tracks portal
    polls): the portal keeps producing datasets while a parked car stays
    silent, so only the car_captured_time fields say when the vehicle itself
    last reported.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:car-clock"
    _attr_translation_key = "last_vehicle_update"

    def __init__(self, coordinator: EudaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_last_vehicle_update"

    @property
    def native_value(self):
        return self._sticky(latest_captured_time(self.coordinator.data or {}))


class EudaDatasetGeneratedSensor(EudaEntity, SensorEntity):
    """When the portal generated the newest downloaded dataset."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:database-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "dataset_generated"

    def __init__(self, coordinator: EudaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_dataset_generated"

    @property
    def native_value(self):
        return self._sticky(self.coordinator.dataset_created_at)


class EudaRawSensor(EudaEntity, SensorEntity):
    """A raw data point exposed as a disabled-by-default diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: EudaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        dp = coordinator.data[key]
        self._key = key
        # Namespace by VIN: dataset keys are shared across vehicles, so a bare
        # key collides between config entries (see raw_unique_id / migration).
        self._attr_unique_id = raw_unique_id(coordinator.vin, key)
        self._attr_name = friendly_name(dp.field_name, dp.description)
        # only attach a unit when the value is numeric
        if dp.unit and dp.type_hint in ("int", "float"):
            self._attr_native_unit_of_measurement = dp.unit

    @property
    def native_value(self):
        dp = (self.coordinator.data or {}).get(self._key)
        return self._sticky(
            shorten_enum_label(dp.field_name, dp.value) if dp else None
        )

    @property
    def extra_state_attributes(self) -> dict:
        dp = (self.coordinator.data or {}).get(self._key)
        if not dp:
            return {}
        attrs = {"key": dp.key, "field_name": dp.field_name}
        if dp.description:
            attrs["description"] = dp.description
        if dp.cluster:
            attrs["cluster"] = dp.cluster
        return attrs
