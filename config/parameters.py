#!/usr/bin/env python3
"""
Project configurations
"""

import os
from dotenv import load_dotenv

load_dotenv()

POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = "Halal-Lens"
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

MINIO_HOST = "localhost"
MINIO_PORT = 9000
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
