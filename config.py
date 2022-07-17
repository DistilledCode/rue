from builtins import range
from sys import exit
from traceback import print_exc

import yaml
from cerberus import TypeDefinition, Validator
from yaml.constructor import ConstructorError

_config_fname = ".rue"
_config_schema_fname = "./schema/rue.yaml"
_secrets_fname = ".secrets"
_secrets_schema_fname = "./schema/secrets.yaml"


_file_dict = {
    "config": _config_fname,
    "config_schema": _config_schema_fname,
    "secrets": _secrets_fname,
    "secrets_schema": _secrets_schema_fname,
}


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


_config_dict = _read_files(_file_dict)

Validator.types_mapping["range"] = TypeDefinition("range", (range,), ())
_validator = Validator()
_validator.require_all = True

_validate_config(_validator, _config_dict["config_schema"], _config_dict["config"])
_validate_config(_validator, _config_dict["secrets_schema"], _config_dict["secrets"])

config: dict = _config_dict["config"]
secrets: dict = _config_dict["secrets"]
