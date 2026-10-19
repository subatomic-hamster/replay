"""AWS Lambda entry (D-80): the API behind a Function URL, through Mangum.

The app is built once per cold start (SSM secrets included); lifespan is off because
the app has no startup work and Lambda has no shutdown hook to run one.
"""

from mangum import Mangum

from .main import create_app

handler = Mangum(create_app(), lifespan="off")
