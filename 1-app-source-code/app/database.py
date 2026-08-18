"""
Database configuration for Project Fosu.

Uses SQLite for the MVP so it runs with zero setup.

Swap DATABASE_URL for a PostgreSQL+PostGIS connection string later, 
    e.g.:
        postgresql+psycopg2://user:password@localhost:5432/fosu
and 
    add GeoAlchemy2 for real spatial columns/queries.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


"""
    sqlite:/// : Tells SQLAlchemy that you are using an SQLite database.
    ./fosu.db : Specifies the file path for the database. In this case, it will create a file named fosu.db in the current working directory where your script is running.
"""

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fosu.db")

"""
    create_engine(): The core interface to the database. It manages the actual connection pool.
    connect_args={"check_same_thread": False} : allowing multiple threads to safely share the database connection
"""
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

"""
    sessionmaker: Creates a factory for generating database sessions (SessionLocal). A session is what you use to write, read, update, and delete records (queries).
    autocommit=False: Ensures that changes aren't automatically saved to the database. You have to explicitly call db.commit() so you have control over transactions.

    autoflush=False: Prevents the session from automatically flushing changes to the database before every query, giving you more control over when queries are executed.

    bind=engine: Connects this session factory to the database engine created earlier.
"""
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

"""
    declarative_base(): Returns a class registry. All your database models (tables) will inherit from this Base class (e.g., class User(Base): ...), allowing SQLAlchemy to map your Python classes to SQL database tables.
"""
Base = declarative_base()

def get_db():
    """
        get_db(): A generator function commonly used as a dependency in web frameworks (like FastAPI's Depends(get_db)).

        db = SessionLocal(): Opens a new database session for an incoming request.

        yield db: Temporarily hands the session over to the API endpoint so it can perform database operations.

        finally: db.close(): Ensures that the database session is always closed after the request finishes, even if an error or exception occurs, preventing connection leaks.
    """
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()