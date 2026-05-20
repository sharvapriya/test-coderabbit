from django.db import migrations, models


def _column_exists(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(col.name == column_name for col in description)


def add_legacy_is_cancelled_columns(apps, schema_editor):
    statements = [
        ("orders_order", "is_cancelled"),
        ("orders_orderitem", "is_cancelled"),
    ]
    for table_name, column_name in statements:
        if not _column_exists(schema_editor, table_name, column_name):
            schema_editor.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} BOOL NOT NULL DEFAULT 0"
            )


def remove_legacy_is_cancelled_columns(apps, schema_editor):
    statements = [
        ("orders_order", "is_cancelled"),
        ("orders_orderitem", "is_cancelled"),
    ]
    for table_name, column_name in statements:
        if _column_exists(schema_editor, table_name, column_name):
            schema_editor.execute(
                f"ALTER TABLE {table_name} "
                f"DROP COLUMN {column_name}"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0014_order_cancellation_audit_and_lifecycle"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_legacy_is_cancelled_columns,
                    remove_legacy_is_cancelled_columns,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="order",
                    name="is_cancelled",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="orderitem",
                    name="is_cancelled",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
