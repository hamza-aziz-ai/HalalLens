"""API package for Halal-Lens services.

Nothing is imported here: uvicorn loads ``api.app:app`` directly, and jobs
import ``api.billing`` / ``api.razorpay_client`` without starting the app.
"""
