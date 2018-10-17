import pytest
import os

from jsonschema import ValidationError
from sqlalchemy import create_engine, inspect
from snowflake.sqlalchemy import URL

from target_snowflake.target_snowflake import TargetSnowflake
from target_snowflake.utils.snowflake_helpers import (
    schema_exists,
    drop_snowflake_schema,
)


def load_stream(filename):
    myDir = os.path.dirname(os.path.abspath(__file__))
    stream = os.path.join(myDir, "data_files", filename)
    with open(stream) as f:
        return [line for line in f]


@pytest.fixture(scope="class")
def snowflake_engine(config):
    return create_engine(
        URL(
            user=config["username"],
            password=config["password"],
            account=config["account"],
            database=config["database"],
            role=config["role"],
            warehouse=config["warehouse"],
        )
    )


class TestTargetSnowflake:
    def test_record_before_schema(self, config):
        test_stream = "record_before_schema.stream"
        target = TargetSnowflake(config)
        stream = load_stream(test_stream)

        with pytest.raises(Exception) as excinfo:
            for line in stream:
                target.process_line(line)
        assert "encountered before a corresponding schema" in str(excinfo.value)

    def test_record_missing_key_property(self, config, snowflake_engine):
        # Before running any integration test, check if the schema defined in
        #  the config is a new one (i.e. drop it afterwards)
        #  or an existing one (i.e. keep it - it could be the public one or
        #   a production schema used by mistake)
        new_schema = not schema_exists(snowflake_engine, config["schema"])

        test_stream = "record_missing_key_property.stream"
        target = TargetSnowflake(config)
        stream = load_stream(test_stream)

        with pytest.raises(ValidationError) as excinfo:
            for line in stream:
                target.process_line(line)
        assert "is missing key property id" in str(excinfo.value)

        # Drop the Test Tables
        for stream, loader in target.loaders.items():
            loader.table.drop(loader.engine)

        # Drop the Schema if we created it and there is nothing left there
        inspector = inspect(snowflake_engine)
        all_table_names = inspector.get_table_names(config["schema"])
        if new_schema and (len(all_table_names) == 0):
            drop_snowflake_schema(
                snowflake_engine, config["database"], config["schema"]
            )

    def test_record_missing_required_property(self, config, snowflake_engine):
        # check if the schema is a new one, ... etc ..
        new_schema = not schema_exists(snowflake_engine, config["schema"])

        test_stream = "record_missing_required_property.stream"
        target = TargetSnowflake(config)
        stream = load_stream(test_stream)

        with pytest.raises(ValidationError) as excinfo:
            for line in stream:
                target.process_line(line)
        assert "'id' is a required property" in str(excinfo.value)

        # Drop the Test Tables
        for stream, loader in target.loaders.items():
            loader.table.drop(loader.engine)

        # Drop the Schema if we created it and there is nothing left there
        inspector = inspect(snowflake_engine)
        all_table_names = inspector.get_table_names(config["schema"])
        if new_schema and (len(all_table_names) == 0):
            drop_snowflake_schema(
                snowflake_engine, config["database"], config["schema"]
            )

    @pytest.mark.slow
    def test_relational_data(self, config, snowflake_engine):
        # Start with a simple initial insert for everything

        # The expected results to compare
        expected_results = {
            "state": {"test_users": 5, "test_locations": 3, "test_user_in_location": 3},
            "tables": ["test_users", "test_locations", "test_user_in_location"],
            "columns": {
                "test_users": ["id", "name", config["timestamp_column"]],
                "test_locations": ["id", "name", config["timestamp_column"]],
                "test_user_in_location": [
                    "id",
                    "user_id",
                    "location_id",
                    "info__weather",
                    "info__mood",
                    config["timestamp_column"],
                ],
            },
            "total_records": {
                "test_users": 5,
                "test_locations": 3,
                "test_user_in_location": 3,
            },
        }

        test_stream = "user_location_data.stream"

        # We are not dropping the schema after the first integration test
        #  in order to also test UPSERTing records to Snowflake
        self.integration_test(
            config, snowflake_engine, expected_results, test_stream, drop_schema=False
        )

        # And then test Upserting (Combination of Updating already available
        #   rows and inserting a couple new rows)
        expected_results["state"] = {
            "test_users": 13,
            "test_locations": 8,
            "test_user_in_location": 14,
        }

        expected_results["total_records"] = {
            "test_users": 8,
            "test_locations": 5,
            "test_user_in_location": 5,
        }
        test_stream = "user_location_upsert_data.stream"

        self.integration_test(
            config, snowflake_engine, expected_results, test_stream, drop_schema=True
        )

    @pytest.mark.slow
    def test_no_primary_keys(self, config, snowflake_engine):
        # Start with a simple initial insert for everything

        # The expected results to compare
        expected_results = {
            "state": {"test_no_pk": 3},
            "tables": ["test_no_pk"],
            "columns": {"test_no_pk": ["id", "metric", config["timestamp_column"]]},
            "total_records": {"test_no_pk": 3},
        }

        test_stream = "no_primary_keys.stream"

        # We are not dropping the schema after the first integration test
        #  in order to also test APPENDING records when no PK is defined
        self.integration_test(
            config, snowflake_engine, expected_results, test_stream, drop_schema=False
        )

        # And then test Upserting
        # The Total Records in this case should be 8 (5+3) due to the records
        #  being appended and not UPSERTed
        expected_results["state"] = {"test_no_pk": 5}
        expected_results["total_records"] = {"test_no_pk": 8}

        test_stream = "no_primary_keys_append.stream"

        self.integration_test(
            config, snowflake_engine, expected_results, test_stream, drop_schema=True
        )

    @pytest.mark.slow
    def test_array_data(self, config, snowflake_engine):
        # The expected results to compare
        expected_results = {
            "state": {"test_carts": 4},
            "tables": ["test_carts"],
            "columns": {"test_carts": ["id", "fruits", config["timestamp_column"]]},
            "total_records": {"test_carts": 4},
        }

        test_stream = "array_data.stream"

        self.integration_test(config, snowflake_engine, expected_results, test_stream)

    @pytest.mark.slow
    def test_encoded_string_data(self, config, snowflake_engine):
        # The expected results to compare
        expected_results = {
            "state": {
                "test_strings": 11,
                "test_strings_in_objects": 11,
                "test_strings_in_arrays": 6,
            },
            "tables": [
                "test_strings",
                "test_strings_in_objects",
                "test_strings_in_arrays",
            ],
            "columns": {
                "test_strings": ["id", "info", config["timestamp_column"]],
                "test_strings_in_objects": [
                    "id",
                    "info__name",
                    "info__value",
                    config["timestamp_column"],
                ],
                "test_strings_in_arrays": ["id", "strings", config["timestamp_column"]],
            },
            "total_records": {
                "test_strings": 11,
                "test_strings_in_objects": 11,
                "test_strings_in_arrays": 6,
            },
        }

        test_stream = "encoded_strings.stream"

        self.integration_test(config, snowflake_engine, expected_results, test_stream)

    def integration_test(
        self, config, snowflake_engine, expected, stream_file, drop_schema=True
    ):
        # check if the schema is a new one, ... etc ..
        new_schema = not schema_exists(snowflake_engine, config["schema"])

        # Create the TargetSnowflake and fully run it using the user_location_data
        target = TargetSnowflake(config)

        stream = load_stream(stream_file)

        for line in stream:
            target.process_line(line)

        target.flush_all_cached_records()

        # Check that the final state is the expected one
        assert target.state == expected["state"]

        # Check that the requested schema has been created
        inspector = inspect(snowflake_engine)
        all_schema_names = inspector.get_schema_names()
        assert config["schema"].lower() in all_schema_names

        all_table_names = inspector.get_table_names(config["schema"])

        with snowflake_engine.connect() as connection:
            for table in expected["tables"]:
                # Check that the Table has been created in Snowflake
                assert table in all_table_names

                # Check that the Table created has the requested attributes
                columns = inspector.get_columns(table, schema=config["schema"])
                for column in columns:
                    assert column["name"].lower() in expected["columns"][table]

                # Check that the correct number of rows were inserted
                query = f"SELECT COUNT(*) FROM {config['schema']}.{table}"

                results = connection.execute(query).fetchone()
                assert results[0] == expected["total_records"][table]

        # Drop the Test Tables
        if drop_schema:
            for stream, loader in target.loaders.items():
                loader.table.drop(loader.engine)

        # Drop the Schema if we created it and there is nothing left there
        inspector = inspect(snowflake_engine)
        all_table_names = inspector.get_table_names(config["schema"])
        if drop_schema and new_schema and (len(all_table_names) == 0):
            drop_snowflake_schema(
                snowflake_engine, config["database"], config["schema"]
            )