from sqlalchemy import inspect, text

from app.db.session import engine


def run_startup_migrations() -> None:
    with engine.connect() as conn:
        inspector = inspect(conn)
        table_names = inspector.get_table_names()
        if "users" not in table_names:
            return

        user_columns = {column["name"] for column in inspector.get_columns("users")}

        if "reset_password_token_hash" not in user_columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN reset_password_token_hash VARCHAR(64)")
            )

        if "reset_password_expires_at" not in user_columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN reset_password_expires_at TIMESTAMP")
            )

        conn.commit()
