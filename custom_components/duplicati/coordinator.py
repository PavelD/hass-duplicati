"""Coordinator for Duplicati backup software."""

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import ApiResponseError, CannotConnect, DuplicatiBackendAPI
from .config_flow import InvalidAuth
from .const import (
    DOMAIN,
    METRIC_DURATION,
    METRIC_ERROR_MESSAGE,
    METRIC_EXECUTION,
    METRIC_SOURCE_FILES,
    METRIC_SOURCE_SIZE,
    METRIC_STATUS,
    METRIC_TARGET_FILES,
    METRIC_TARGET_SIZE,
    STATUS_ERROR,
    STATUS_OK,
)
from .sensor import SENSORS

_LOGGER = logging.getLogger(__name__)


class DuplicatiDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to manage Duplicati data update coordination."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DuplicatiBackendAPI,
        backup_id: str,
        update_interval: int,
    ) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.backup_id = backup_id

    async def _async_update_data(self):
        """Fetch data from Duplicati API."""
        try:
            # Get backup info
            backup_info = await self.api.get_backup(self.backup_id)
            if "Error" in backup_info:
                raise ApiResponseError(backup_info["Error"])
            # Process metrics for sensors and return sensor data
            return self._process_data(backup_info)
        except CannotConnect as e:
            _LOGGER.error("Failed to connect: %s", str(e))
        except InvalidAuth as e:
            _LOGGER.error("Authentication failed: %s", str(e))
        except ApiResponseError as e:
            _LOGGER.error("API response error: %s", str(e))
        except Exception:
            _LOGGER.exception("Unexpected exception")

    def _process_data(self, data):
        """Process raw data into sensor values."""

        if "LastBackupDate" in data["data"]["Backup"]["Metadata"]:
            last_backup_date = data["data"]["Backup"]["Metadata"]["LastBackupDate"]
            last_backup_date = datetime.strptime(last_backup_date, "%Y%m%dT%H%M%SZ")
            last_backup_date = last_backup_date.replace(tzinfo=dt_util.UTC)
        else:
            last_backup_date = None

        if "LastErrorDate" in data["data"]["Backup"]["Metadata"]:
            last_error_date = data["data"]["Backup"]["Metadata"]["LastErrorDate"]
            last_error_date = datetime.strptime(last_error_date, "%Y%m%dT%H%M%SZ")
            last_error_date = last_error_date.replace(tzinfo=dt_util.UTC)
        else:
            last_error_date = None

        # Check backup state
        if last_error_date and not last_backup_date:
            error = True
        elif last_error_date and last_backup_date:
            if last_error_date > last_backup_date:
                error = True
            else:
                error = False
        elif not last_error_date and last_backup_date:
            error = False

        if error:
            last_backup_execution = last_error_date
            last_backup_status = STATUS_ERROR
            if "LastErrorMessage" in data["data"]["Backup"]["Metadata"]:
                last_backup_error_message = data["data"]["Backup"]["Metadata"][
                    "LastErrorMessage"
                ]
                last_backup_duration = None
                last_backup_source_size = None
                last_backup_source_files_count = None
                last_backup_target_size = None
                last_backup_target_files_count = None
        else:
            last_backup_execution = last_backup_date
            last_backup_status = STATUS_OK
            last_backup_error_message = "-"
            if "LastBackupDuration" in data["data"]["Backup"]["Metadata"]:
                last_backup_duration = data["data"]["Backup"]["Metadata"][
                    "LastBackupDuration"
                ]
                # Split the duration string into hours, minutes, seconds, and microseconds
                parts = last_backup_duration.split(":")
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds, microseconds = map(float, parts[2].split("."))
                microseconds = int(
                    f"{microseconds:.6f}".replace(".", "").ljust(6, "0")[:6]
                )
                milliseconds = round(microseconds / 1000)
                # Calculate the total duration in seconds
                last_backup_duration = (
                    (hours * 3600) + (minutes * 60) + seconds + (milliseconds / 1000)
                )

            if "SourceFilesSize" in data["data"]["Backup"]["Metadata"]:
                last_backup_source_size = data["data"]["Backup"]["Metadata"][
                    "SourceFilesSize"
                ]

            if "SourceFilesCount" in data["data"]["Backup"]["Metadata"]:
                last_backup_source_files_count = data["data"]["Backup"]["Metadata"][
                    "SourceFilesCount"
                ]

            if "TargetFilesSize" in data["data"]["Backup"]["Metadata"]:
                last_backup_target_size = data["data"]["Backup"]["Metadata"][
                    "TargetFilesSize"
                ]

            if "TargetFilesCount" in data["data"]["Backup"]["Metadata"]:
                last_backup_target_files_count = data["data"]["Backup"]["Metadata"][
                    "TargetFilesCount"
                ]

        processed_data = {}

        for sensor_type in SENSORS:
            # Process data according to sensor type
            if sensor_type == METRIC_STATUS:
                processed_data[sensor_type] = last_backup_status
            elif sensor_type == METRIC_EXECUTION:
                processed_data[sensor_type] = last_backup_execution
            elif sensor_type == METRIC_DURATION:
                processed_data[sensor_type] = last_backup_duration
            elif sensor_type == METRIC_TARGET_SIZE:
                processed_data[sensor_type] = last_backup_target_size
            elif sensor_type == METRIC_TARGET_FILES:
                processed_data[sensor_type] = last_backup_target_files_count
            elif sensor_type == METRIC_SOURCE_SIZE:
                processed_data[sensor_type] = last_backup_source_size
            elif sensor_type == METRIC_SOURCE_FILES:
                processed_data[sensor_type] = last_backup_source_files_count
            elif sensor_type == METRIC_ERROR_MESSAGE:
                processed_data[sensor_type] = last_backup_error_message

        return processed_data
