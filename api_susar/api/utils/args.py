import json


def get_string(args, key, required=False, default=None):
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    if args[key] is None:
        if required:
            raise ValueError({"message": 'field "{0}" is null.'.format(key)})
        else:
            return default
    return args[key]

def get_list(args, key, required=False, default=None):
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    if args[key] is None:
        if required:
            raise ValueError({"message": 'field "{0}" is null.'.format(key)})
        else:
            return default
    return args[key]


def get_int(args, key, required=False, default=None):
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    try:
        integer = int(args[key])
    except ValueError:
        raise ValueError(
            {"message": "wrong {0} format, should be integer.".format(key)}
        )
    except TypeError:
        return default
    return integer


def get_float(args, key, required=False, default=None):
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    try:
        float_value = float(args[key])
    except ValueError:
        raise ValueError(
            {"message": "wrong {0} format, should be float.".format(key)}
        )
    except TypeError:
        return default
    return float_value


def get_bool(args, key, required=False, default=None):
    possible_values = ["true", "True", "yes", "1", "false", "False", "no", "0", False, True]
    positive_values = ["true", "True", "yes", "1", True]
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    value = args[key]
    if value not in possible_values:
        raise ValueError(
            {"message": "wrong {0} format, should be boolean.".format(key)}
        )
    return value in positive_values


def get_args(request):
    if request.headers.get('Content-Type') == 'application/json' or request.headers.get('Content-Type') == 'application/json;charset=utf-8':
        return {**request.args, **request.form, **request.json}
    return {**request.args, **request.form}


def get_json(args, key, required=False, default=None):
    if key not in args:
        if required:
            raise ValueError({"message": 'field "{0}" not specified.'.format(key)})
        return default
    return json.loads(args.get(key))
