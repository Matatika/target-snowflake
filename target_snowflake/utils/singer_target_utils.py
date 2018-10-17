import collections
import inflection
import itertools
import re

from sqlalchemy import MetaData, Table, Column
from sqlalchemy.types import TIMESTAMP, Float, String, BigInteger, Boolean
from snowflake.sqlalchemy import ARRAY, OBJECT

# Set of helper functions for flattening records and schemas.
# The core ones are:
# + flatten(record) --> flatten a given data record.
#  e.g. {"id": 3, "info": {"weather": "sunny", "mood": "happy"}}}
#     --> {"id": 3, "info__weather": "sunny", "info__mood": "happy"}
# + flatten_schema(json_schema_definition) --> flatten a given json schema.
# + generate_sqlalchemy_table(stream, key_properties, json_schema, timestamp_column)
#    --> Generate an sqlalchemy Table based on a SCHEMA message


def generate_sqlalchemy_table(stream, key_properties, json_schema, timestamp_column):
    flat_schema = flatten_schema(json_schema)
    schema_dict = {
        Column(name, sqlalchemy_column_type(schema), primary_key=True)
        for (name, schema) in flat_schema.items()
    }

    columns = []
    for (name, schema) in flat_schema.items():
        pk = name in key_properties
        column = Column(name, sqlalchemy_column_type(schema), primary_key=pk)
        columns.append(column)

    if timestamp_column and timestamp_column not in flat_schema:
        column = Column(timestamp_column, TIMESTAMP)
        columns.append(column)

    table = Table(stream, MetaData(), *columns)

    return table


def flatten(d, parent_key="", sep="__"):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, str(v) if type(v) is list else v))
    return dict(items)


def inflect_column_name(name):
    name = re.sub(r"([A-Z]+)_([A-Z][a-z])", r"\1__\2", name)
    name = re.sub(r"([a-z\d])_([A-Z])", r"\1__\2", name)
    return inflection.underscore(name)


def flatten_key(k, parent_key, sep):
    full_key = parent_key + [k]
    inflected_key = [inflect_column_name(n) for n in full_key]
    reducer_index = 0
    while len(sep.join(inflected_key)) >= 63 and reducer_index < len(inflected_key):
        reduced_key = re.sub(
            r"[a-z]", "", inflection.camelize(inflected_key[reducer_index])
        )
        inflected_key[reducer_index] = (
            reduced_key if len(reduced_key) > 1 else inflected_key[reducer_index][0:3]
        ).lower()
        reducer_index += 1

    return sep.join(inflected_key)


def flatten_schema(d, parent_key=[], sep="__"):
    items = []
    for k, v in d["properties"].items():
        new_key = flatten_key(k, parent_key, sep)

        if not v:
            logger.warn("Empty definition for {}.".format(new_key))
            continue

        if "type" in v.keys():
            if "object" in v["type"]:
                items.extend(flatten_schema(v, parent_key + [k], sep=sep).items())
            else:
                items.append((new_key, v))
        else:
            property = list(v.values())[0][0]
            if property["type"] == "string":
                property["type"] = ["null", "string"]
                items.append((new_key, property))
            elif property["type"] == "array":
                property["type"] = ["null", "array"]
                items.append((new_key, property))

    key_func = lambda item: item[0]
    sorted_items = sorted(items, key=key_func)
    for k, g in itertools.groupby(sorted_items, key=key_func):
        if len(list(g)) > 1:
            raise ValueError("Duplicate column name produced in schema: {}".format(k))

    return dict(sorted_items)


def sqlalchemy_column_type(schema_property):
    property_type = schema_property["type"]
    property_format = schema_property["format"] if "format" in schema_property else None

    # At the moment there is no proper support for Snowflake's semi-structured
    #  data types (VARIANT, ARRAY and OBJECT) in snowflake.sqlalchemy
    # and no support for using sqlalchemy.types.JSON
    # Until it is fixed, we are going to store semi-structured data (mainly JSON arrays)
    #  as strings and depend on a transformation step (e.g. using dbt) to
    #  convert those strings to proper snowflake VARIANT or ARRAY types.
    if "object" in property_type:
        return String  # OBJECT
    elif "array" in property_type:
        return String  # ARRAY
    elif property_format == "date-time":
        return TIMESTAMP
    elif "number" in property_type:
        return Float
    elif "integer" in property_type and "string" in property_type:
        return String
    elif "integer" in property_type:
        return BigInteger
    elif "boolean" in property_type:
        return Boolean
    else:
        return String