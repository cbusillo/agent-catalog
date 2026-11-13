from sqlalchemy import text

DANGLING = text("SELECT id FROM people WHERE")
