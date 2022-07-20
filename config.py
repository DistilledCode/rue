from builtins import range
from sys import exit

import yaml
from cerberus import TypeDefinition, Validator
from yaml.constructor import ConstructorError

__all__ = ["cfg", "secrets"]


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

    file_dict = {
        "config": ".rue",
        "config_schema": "./schema/rue.yaml",
        "secrets": ".secrets",
        "secrets_schema": "./schema/secrets.yaml",
    }

    config_dict = _read_files(file_dict)

    Validator.types_mapping["range"] = TypeDefinition("range", (range,), ())
    validator = Validator()
    validator.require_all = True

    _validate_config(validator, config_dict["config_schema"], config_dict["config"])
    _validate_config(validator, config_dict["secrets_schema"], config_dict["secrets"])

    return (config_dict["config"], config_dict["secrets"])


cfg, secrets = _get_config()
