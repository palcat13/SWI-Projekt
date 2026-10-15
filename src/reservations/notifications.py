import logging

from .models import Reservation

logger = logging.getLogger(__name__)

AWAITING_APPROVAL = "reservation.awaiting_approval"
CONFIRMED = "reservation.confirmed"
CANCELLED = "reservation.cancelled"
DECIDED = "reservation.decided"


class NotificationPort:
    def notify(self, event: str, reservation: Reservation) -> None:
        raise NotImplementedError


class LoggingNotificationPort(NotificationPort):
    def notify(self, event: str, reservation: Reservation) -> None:
        logger.info("notification %s for reservation %s", event, reservation.id)


_port: NotificationPort = LoggingNotificationPort()


def get_port() -> NotificationPort:
    return _port


def set_port(port: NotificationPort) -> NotificationPort:
    global _port
    previous = _port
    _port = port
    return previous
