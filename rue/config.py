from builtins import range
from dataclasses import make_dataclass
from pathlib import Path
from sys import exit
from zoneinfo import ZoneInfoNotFoundError, available_timezones

import yaml
from cerberus import TypeDefinition, Validator
from yaml.constructor import ConstructorError

__all__ = ["cfg", "secrets"]


def _dict2dataclass(name: str, conv_dict: dict, **kwargs: dict) -> type:
    if any(not isinstance(x := key, str) or not x.isidentifier() for key in conv_dict):
        raise TypeError(f"Field names must be valid identifiers: {x!r}")
    field_list = []
    for key, val in conv_dict.items():
        if val.__class__ is dict:
            val = _dict2dataclass(key, val, **kwargs)
        field_list.append((key, val.__class__, val))
    DataClass = make_dataclass(name, field_list, **kwargs)
    return DataClass()


def _validate_config(validator: Validator, schema: dict, document: dict) -> None:
    if not validator.validate(document, schema):
        for key, val in validator.errors.items():
            x = validator.document_error_tree[key].errors[0]
            print(f"\n{str('CONFIG VALIDATION ERROR'):=^55}")
            print(f"{key}: {val}")
            if x.code in [68, 69]:
                print(f"allowed values: {x.constraint}")
            print(f"value received: {x.value!r}\n")
            exit()
    return


def _read_files(file_dict: dict) -> dict:
    config_dict = dict()
    for file in file_dict:
        try:
            with open(file_dict[file], "r") as f:
                file_obj = yaml.load(f, Loader=yaml.UnsafeLoader)
        except FileNotFoundError:
            # TODO initialize the default file automatically?
            raise
        except ConstructorError:
            print("\nArgument for 'sleep_time:' in '.rue' must be wrapped in '[]'.\n")
            raise
        else:
            config_dict[file] = file_obj
    return config_dict


def _get_config() -> tuple[dict]:
    dir = Path(__file__).resolve().parents[1]
    file_dict = {
        "config": dir.joinpath(".rue"),
        "config_schema": dir.joinpath("schema/rue.yaml"),
        "secrets": dir.joinpath(".rue.secrets"),
        "secrets_schema": dir.joinpath("schema/secrets.yaml"),
    }
    config_dict = _read_files(file_dict)

    time_zone = config_dict["config"]["schedule"]["tz"]
    if time_zone not in available_timezones():
        raise ZoneInfoNotFoundError(f"No time zone found with key {time_zone!r}")

    Validator.types_mapping["range"] = TypeDefinition("range", (range,), ())
    validator = Validator()
    validator.require_all = True
    _validate_config(validator, config_dict["config_schema"], config_dict["config"])
    _validate_config(validator, config_dict["secrets_schema"], config_dict["secrets"])
    return (config_dict["config"], config_dict["secrets"])


cfg, secrets = _get_config()
cfg = _dict2dataclass("Cfg", cfg)
secrets = _dict2dataclass("Secrets", secrets)
