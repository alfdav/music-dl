from typing import ClassVar


class SingletonMeta(type):
    """Singleton metaclass — ensures only one instance of each class is created."""

    _instances: ClassVar[dict] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance

        return cls._instances[cls]
