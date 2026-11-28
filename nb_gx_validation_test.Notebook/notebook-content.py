# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "environment": {
# META       "environmentId": "6c9732e3-e471-ab0f-485e-0e22f138c1eb",
# META       "workspaceId": "00000000-0000-0000-0000-000000000000"
# META     }
# META   }
# META }

# CELL ********************

# nb_gx_validation_test

import great_expectations as gx

# 1. Print GX version to confirm parity with local
print(f"Great Expectations version: {gx.__version__}")

# 2. Create a sample Spark DataFrame
data = [("TXN-001", 100.50), ("TXN-002", 250.00), ("TXN-003", 75.25)]
df = spark.createDataFrame(data, ["transaction_id", "amount"])

# 3. Initialize ephemeral GX context & Spark data source (GX 1.x API)
context = gx.get_context()
data_source = context.data_sources.add_spark(name="spark_ds")
data_asset = data_source.add_dataframe_asset(name="transactions_asset")
batch_definition = data_asset.add_batch_definition_whole_dataframe("batch_def")

batch = batch_definition.get_batch(batch_parameters={"dataframe": df})

# 4. Run a single expectation
expectation = gx.expectations.ExpectColumnValuesToNotBeNull(column="transaction_id")
validation_result = batch.validate(expectation)

print(f"Validation success: {validation_result.success}")
assert validation_result.success, "Expected transaction_id to have no nulls"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
